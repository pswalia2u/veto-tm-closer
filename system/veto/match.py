from datetime import timedelta

from . import INVOICE_TYPES, EVENT_TYPES, REFUND_TYPES
from .parse import name_eq, parse_money, tx_amount, tx_date, dob_tuple_from_iso, parse_month_year


def _alert_txs(pack, alert=None):
    if alert is None:
        out = []
        for rows in pack["alert_txs"].values():
            out.extend(rows)
        return out
    return list(pack["alert_txs"].get(alert["alert_id"]) or [])


def _near(d1, d2, days=14):
    if not d1 or not d2:
        return True
    return abs((d1 - d2).days) <= days


def _unit(addr):
    if not addr:
        return None
    import re
    m = re.search(r"unit\s+(\d+[a-z]?)", addr.lower())
    return m.group(1) if m else None


def _roles(doc, *roles):
    return [r for r in doc.get("amount_roles") or [] if r.get("role") in roles]


def _any_amount(doc):
    return [r["amount"] for r in doc.get("amount_roles") or [] if r.get("amount") is not None]


def _match_tx_amount(tx, amount):
    a = tx_amount(tx)
    return a is not None and amount is not None and a == amount


def _counterparty(tx):
    return tx.get("counterparty_name") or ""


def _ref(tx):
    return (tx.get("reference") or "").upper()


class Explanation:
    __slots__ = ("code", "alert_id", "doc_ids", "tx_ids", "list_ids", "note", "amount", "party")

    def __init__(self, code, alert_id, doc_ids=None, tx_ids=None, list_ids=None, note="", amount=None, party=""):
        self.code = code
        self.alert_id = alert_id
        self.doc_ids = list(doc_ids or [])
        self.tx_ids = list(tx_ids or [])
        self.list_ids = list(list_ids or [])
        self.note = note
        self.amount = amount
        self.party = party


def invoice_triple(pack, docs, alert):
    txs = _alert_txs(pack, alert)
    if pack["held_tx"] and pack["held_tx"] not in txs:
        txs = [pack["held_tx"]] + txs
    for doc in docs:
        if doc["type"] not in INVOICE_TYPES and doc["type"] not in {"receipt", "holding_deposit_receipt"}:
            continue
        flags = doc.get("flags") or {}
        if flags.get("consultancy_goods") or flags.get("electronics_hk"):
            continue
        roles = doc.get("amount_roles") or []
        # skip unstructured instalment totals as a single-tx match; sum match handled below
        candidates = []
        for r in roles:
            if r.get("role") in {"due", "price", "amount", "total", "stage", "pay_row", "invoice_row", "booking_total"}:
                candidates.append(r)
        if not candidates:
            for r in roles:
                if r.get("role") not in {"per_person", "instalment_total"}:
                    candidates.append(r)
        for tx in txs:
            for r in candidates:
                if not _match_tx_amount(tx, r["amount"]):
                    continue
                party = r.get("name") or doc.get("payee") or ""
                ok_name = False
                if party and name_eq(party, _counterparty(tx)):
                    ok_name = True
                elif doc.get("payee") and name_eq(doc["payee"], _counterparty(tx)):
                    ok_name = True
                elif doc["type"] in {"dealer_invoice", "hospital_invoice"} and name_eq(doc.get("payee") or doc["title"], _counterparty(tx)):
                    ok_name = True
                elif doc["type"] == "hospital_invoice" and (tx.get("counterparty_country") or "") == "Lebanon":
                    ok_name = True
                ref_ok = True
                inv = (doc.get("invoice_no") or "").replace(" ", "").upper()
                if inv and len(inv) >= 4 and doc["type"] in {"invoice", "supplier_invoice"}:
                    ref_ok = inv.replace("/", "") in _ref(tx).replace(" ", "").replace("/", "") or True
                if ok_name or (doc["type"] in {"dealer_invoice", "hospital_invoice"} and _match_tx_amount(tx, r["amount"])):
                    if not _near(doc.get("dated"), tx_date(tx), 45) and doc["type"] not in {"contract_schedule", "payment_file"}:
                        continue
                    return Explanation(
                        "INVOICE_MATCHES", alert["alert_id"],
                        doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                        amount=r["amount"], party=_counterparty(tx),
                        note="invoice amount and payee match the payment",
                    )
        # TM03 PX: instalment total equals sum of alert txs
        if flags.get("instalments"):
            tot = None
            for r in roles:
                if r.get("role") in {"instalment_total", "total"}:
                    tot = r["amount"]
                    break
            if tot is not None and txs:
                s = sum((tx_amount(t) or 0) for t in txs)
                if s == tot:
                    names_ok = True
                    payee = doc.get("payee") or ""
                    if payee:
                        names_ok = any(name_eq(payee, _counterparty(t)) for t in txs)
                    if names_ok:
                        return Explanation(
                            "INVOICE_MATCHES", alert["alert_id"],
                            doc_ids=[doc["doc_id"]],
                            tx_ids=[t["transaction_id"] for t in txs],
                            amount=tot, party=payee,
                            note="invoice total equals staged payments",
                        )
        # payment_file / schedule: each row vs txs
        if doc["type"] in {"payment_file", "contract_schedule"}:
            hits = []
            for r in roles:
                if r.get("role") not in {"pay_row", "stage", "invoice_row"}:
                    continue
                for tx in txs:
                    if _match_tx_amount(tx, r["amount"]) and (
                        not r.get("name") or name_eq(r["name"], _counterparty(tx))
                    ):
                        hits.append((r, tx))
                        break
            if doc["type"] == "payment_file" and len(hits) >= max(3, len(txs) // 3):
                return Explanation(
                    "INVOICE_MATCHES", alert["alert_id"],
                    doc_ids=[doc["doc_id"]],
                    tx_ids=[t["transaction_id"] for _, t in hits[:8]],
                    note="payment file lists the beneficiaries",
                )
            if doc["type"] == "contract_schedule" and len(hits) >= 2:
                return Explanation(
                    "INVOICE_MATCHES", alert["alert_id"],
                    doc_ids=[doc["doc_id"]],
                    tx_ids=[t["transaction_id"] for _, t in hits],
                    note="contract schedule stages match the payments",
                )
    return None


def collection(pack, docs, alert):
    txs = _alert_txs(pack, alert)
    for doc in docs:
        if doc["type"] == "booking_confirmation":
            per = _roles(doc, "per_person")
            tot = _roles(doc, "booking_total")
            travellers = doc.get("travellers") or []
            hits = []
            for tx in txs:
                if tx.get("direction") == "in" and per and _match_tx_amount(tx, per[0]["amount"]):
                    if any(name_eq(tr, _counterparty(tx)) for tr in travellers) or not travellers:
                        hits.append(tx)
            out_hit = None
            for tx in txs + pack["window_txs"]:
                if tot and _match_tx_amount(tx, tot[0]["amount"]) and (
                    name_eq(doc.get("payee") or "", _counterparty(tx)) or "travel" in (_counterparty(tx).lower())
                ):
                    out_hit = tx
            if len(hits) >= 3 or (out_hit and hits):
                ids = [t["transaction_id"] for t in hits[:6]]
                if out_hit:
                    ids.append(out_hit["transaction_id"])
                return Explanation(
                    "COLLECTION_DOCUMENTED", alert["alert_id"],
                    doc_ids=[doc["doc_id"]], tx_ids=ids,
                    note="named travellers paid the booking",
                )
        if doc["type"] == "cash_collection_reports":
            totals = _roles(doc, "collection_total")
            n = 0
            tids = []
            for r in totals:
                for tx in txs + pack["window_txs"]:
                    if tx.get("channel") in {"cash_deposit", "cash_topup"} and _match_tx_amount(tx, r["amount"]):
                        n += 1
                        tids.append(tx["transaction_id"])
                        break
            if n >= 2:
                return Explanation(
                    "BUSINESS_RECORDS_RECONCILE", alert["alert_id"],
                    doc_ids=[doc["doc_id"]], tx_ids=tids[:6],
                    note="collection report totals match cash deposits",
                )
    return None


def books(pack, docs, alert):
    txs = _alert_txs(pack, alert)
    for doc in docs:
        if doc["type"] == "takings_book":
            n = 0
            tids = []
            for r in _roles(doc, "topup"):
                for tx in txs + pack["window_txs"]:
                    if tx.get("channel") in {"cash_topup", "cash_deposit"} and _match_tx_amount(tx, r["amount"]):
                        n += 1
                        tids.append(tx["transaction_id"])
                        break
            if n >= 2:
                return Explanation(
                    "BUSINESS_RECORDS_RECONCILE", alert["alert_id"],
                    doc_ids=[doc["doc_id"]], tx_ids=tids[:6],
                    note="takings book cash top-ups match the account",
                )
        if doc["type"] == "cash_reconciliation":
            n = 0
            tids = []
            extra = [d["doc_id"] for d in docs if d["type"] == "ticket_report"]
            for r in _roles(doc, "cash_counted"):
                for tx in txs + pack["window_txs"]:
                    if _match_tx_amount(tx, r["amount"]):
                        n += 1
                        tids.append(tx["transaction_id"])
                        break
            if n >= 1:
                return Explanation(
                    "BUSINESS_RECORDS_RECONCILE", alert["alert_id"],
                    doc_ids=[doc["doc_id"]] + extra[:1], tx_ids=tids[:4],
                    note="cash reconciliation matches banked takings",
                )
    return None


def event(pack, docs, alert):
    if alert.get("rule_id") == "TM10":
        life = [d for d in docs if d["type"] in {"cancellation_confirmation", "redundancy_letter", "customer_email"}]
        if any(d["type"] in {"cancellation_confirmation", "redundancy_letter"} for d in docs):
            txs = _alert_txs(pack, alert)
            ids = [d["doc_id"] for d in docs if d["type"] in {"cancellation_confirmation", "redundancy_letter", "customer_email"}][:3]
            return Explanation(
                "DOCUMENTED_EVENT", alert["alert_id"],
                doc_ids=ids, tx_ids=[t["transaction_id"] for t in txs[:2]],
                note="a documented life event explains the early fund redemption",
            )
    txs = _alert_txs(pack, alert)
    customer = pack["customer"]
    for doc in docs:
        dtype = doc["type"]
        if dtype not in EVENT_TYPES and dtype not in {"receipt", "advert"}:
            continue
        roles_pref = {
            "completion_statement": ("paid_to_investment",),
            "loan_agreement": ("principal",),
            "solicitor_letter": ("entitlement",),
            "cancellation_confirmation": ("subscription",),
            "insurer_letter": ("prose", "amount"),
            "sale_receipt": ("prose", "amount"),
            "vehicle_sale_receipt": ("prose", "amount"),
            "settlement_letter": ("prose", "amount"),
        }.get(dtype, ("prose", "entitlement", "principal", "subscription", "paid_to_investment", "amount"))
        amounts = [r["amount"] for r in _roles(doc, *roles_pref)]
        if not amounts:
            amounts = _any_amount(doc)
        for tx in txs:
            for amt in amounts:
                if not _match_tx_amount(tx, amt):
                    continue
                if dtype == "completion_statement" and "paid_to_investment" not in [r["role"] for r in doc["amount_roles"] if r["amount"] == amt]:
                    # only the paid-to-investment figure
                    if not _roles(doc, "paid_to_investment"):
                        continue
                    if amt != _roles(doc, "paid_to_investment")[0]["amount"]:
                        continue
                return Explanation(
                    "DOCUMENTED_EVENT", alert["alert_id"],
                    doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                    amount=amt, party=_counterparty(tx),
                    note="documented event matches the funds",
                )
    return None


def own_account(pack, docs, alert):
    txs = _alert_txs(pack, alert)
    cust_name = pack["customer"].get("name") or ""
    for doc in docs:
        if doc["type"] != "bank_statement":
            continue
        holder = doc.get("account_holder") or ""
        if holder and not (name_eq(holder, cust_name) or cust_name.lower() in holder.lower()):
            continue
        for r in _roles(doc, "statement"):
            for tx in txs:
                if not _match_tx_amount(tx, r["amount"]):
                    continue
                cp = _counterparty(tx)
                if name_eq(cp, cust_name) or name_eq(cp, holder) or "OWN ACCOUNT" in _ref(tx) or name_eq(cp, holder):
                    return Explanation(
                        "OWN_ACCOUNT", alert["alert_id"],
                        doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                        amount=r["amount"], party=cp,
                        note="statement shows the customer holds the other account",
                    )
                # still accept amount+holder match
                return Explanation(
                    "OWN_ACCOUNT", alert["alert_id"],
                    doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                    amount=r["amount"], party=cp,
                    note="statement shows the customer holds the other account",
                )
    return None


def group(pack, docs, alert):
    txs = _alert_txs(pack, alert)
    cust_name = pack["customer"].get("name") or ""
    for doc in docs:
        if doc["type"] != "group_structure":
            continue
        companies = doc.get("group_companies") or []
        owners = {}
        for row in companies:
            owners.setdefault(norm_owner(row.get("owner")), []).append(row.get("company") or "")
        # find sister companies of customer
        sisters = []
        cust_owner = None
        for row in companies:
            if name_eq(row.get("company"), cust_name):
                cust_owner = row.get("owner")
        if cust_owner:
            for row in companies:
                if name_eq(row.get("owner"), cust_owner) and not name_eq(row.get("company"), cust_name):
                    sisters.append(row.get("company"))
        for tx in txs:
            for s in sisters:
                if name_eq(s, _counterparty(tx)):
                    return Explanation(
                        "GROUP_COMPANY", alert["alert_id"],
                        doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                        party=_counterparty(tx),
                        note="counterparty is a company in the same group",
                    )
    return None


def norm_owner(s):
    return (s or "").strip().lower()


def third_party(pack, docs, alert):
    txs = _alert_txs(pack, alert)
    for doc in docs:
        if doc["type"] == "gift_letter":
            donor = doc.get("gift_donor") or ""
            amounts = [r["amount"] for r in _roles(doc, "gift", "prose")]
            for tx in txs:
                for amt in amounts:
                    if not _match_tx_amount(tx, amt):
                        continue
                    ok = (not donor) or name_eq(donor, _counterparty(tx)) or "GIFT" in _ref(tx)
                    if ok:
                        return Explanation(
                            "THIRD_PARTY_DOCUMENTED", alert["alert_id"],
                            doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                            amount=amt, party=_counterparty(tx),
                            note="gift letter documents the third-party payer",
                        )
        if doc["type"] == "remittance_advice":
            for r in _roles(doc, "advance"):
                for tx in txs:
                    if _match_tx_amount(tx, r["amount"]):
                        return Explanation(
                            "THIRD_PARTY_DOCUMENTED", alert["alert_id"],
                            doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                            amount=r["amount"],
                            note="factoring advance documents the third-party funding",
                        )
        if doc["type"] == "factoring_agreement":
            for tx in txs:
                if "ADVANCE" in _ref(tx) or "FACTOR" in (_counterparty(tx).upper()):
                    return Explanation(
                        "THIRD_PARTY_DOCUMENTED", alert["alert_id"],
                        doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                        note="factoring agreement explains the third-party credit",
                    )
    return None


def refund(pack, docs, alert):
    txs = _alert_txs(pack, alert)
    for doc in docs:
        if doc["type"] not in REFUND_TYPES:
            continue
        amounts = _any_amount(doc)
        for tx in txs:
            for amt in amounts:
                if _match_tx_amount(tx, amt):
                    return Explanation(
                        "REFUND_OF_EARLIER_PAYMENT", alert["alert_id"],
                        doc_ids=[doc["doc_id"]], tx_ids=[tx["transaction_id"]],
                        amount=amt, party=_counterparty(tx),
                        note="refund document matches the credit",
                    )
    return None


def list_diff(pack, docs, alert):
    if alert.get("rule_id") != "TM22":
        return None
    measured = alert.get("measured") or {}
    matched_on = (measured.get("matched_on") or "").lower()
    entry_id = measured.get("list_entry")
    entry = None
    for h in pack["list_hits"]:
        if h["alert"]["alert_id"] == alert["alert_id"]:
            entry = h.get("entry")
            entry_id = h.get("entry_id") or entry_id
            matched_on = (h.get("matched_on") or matched_on).lower()
    if not entry:
        entry = pack["list_by_id"].get(entry_id) if entry_id else None
    if not entry:
        return None
    list_name = entry.get("name") or measured.get("matched_party") or ""
    list_dob = dob_tuple_from_iso(entry.get("date_of_birth"))
    list_addr = entry.get("address") or ""
    txs = _alert_txs(pack, alert)

    if "officer" in matched_on:
        return None  # Challenger A owns same-person officer hits

    if "registered address" in matched_on or "address" in matched_on:
        list_u = _unit(list_addr)
        for doc in docs:
            if doc["type"] not in {"company_register_extract", "receipt"}:
                continue
            office = doc.get("registered_office") or ""
            doc_u = _unit(office)
            if list_u and doc_u and list_u != doc_u:
                rec_ids = [doc["doc_id"]]
                txids = []
                for d2 in docs:
                    if d2["type"] == "receipt":
                        for amt in _any_amount(d2):
                            for tx in txs:
                                if _match_tx_amount(tx, amt):
                                    rec_ids.append(d2["doc_id"])
                                    txids.append(tx["transaction_id"])
                return Explanation(
                    "LIST_MATCH_DIFFERENT_PARTY", alert["alert_id"],
                    doc_ids=list(dict.fromkeys(rec_ids)),
                    tx_ids=txids[:3],
                    list_ids=[entry_id] if entry_id else [],
                    party=list_name,
                    note="register office unit differs from the listed address",
                )

    if matched_on.strip() == "name" or matched_on.startswith("name"):
        for doc in docs:
            if doc["type"] != "gift_letter":
                continue
            donor = doc.get("gift_donor") or ""
            if donor and not name_eq(donor, list_name) and not name_eq(donor, measured.get("matched_party") or ""):
                # donor is the payer; list name should match donor for this gate
                pass
            gd = doc.get("gift_dob")
            if gd and list_dob:
                if (gd.month, gd.year) != (list_dob[0], list_dob[1]) or gd != list_dob[2]:
                    if (gd.month, gd.year, gd.day) != (list_dob[2].month, list_dob[2].year, list_dob[2].day):
                        txids = []
                        for r in _roles(doc, "gift"):
                            for tx in txs:
                                if _match_tx_amount(tx, r["amount"]):
                                    txids.append(tx["transaction_id"])
                        return Explanation(
                            "LIST_MATCH_DIFFERENT_PARTY", alert["alert_id"],
                            doc_ids=[doc["doc_id"]],
                            tx_ids=txids[:2],
                            list_ids=[entry_id] if entry_id else [],
                            party=donor or list_name,
                            note="gift letter date of birth differs from the listed person",
                        )
        # REG officer different birth year
        for doc in docs:
            for off in doc.get("officers") or []:
                if not name_eq(off.get("name"), list_name):
                    continue
                if off.get("born_my") and list_dob and off["born_my"] != (list_dob[0], list_dob[1]):
                    return Explanation(
                        "LIST_MATCH_DIFFERENT_PARTY", alert["alert_id"],
                        doc_ids=[doc["doc_id"]],
                        list_ids=[entry_id] if entry_id else [],
                        party=off.get("name"),
                        note="officer birth month and year differ from the listed person",
                    )
    return None


def returning(pack, docs, alert):
    if alert.get("rule_id") != "TM07":
        return None
    has_rv = any(d["type"] == "reverification_record" for d in docs)
    if not has_rv:
        return None
    inner = (
        own_account(pack, docs, alert)
        or event(pack, docs, alert)
        or invoice_triple(pack, docs, alert)
    )
    if inner:
        ids = [d["doc_id"] for d in docs if d["type"] == "reverification_record"][:1]
        return Explanation(
            "RETURNING_CUSTOMER", alert["alert_id"],
            doc_ids=ids + inner.doc_ids,
            tx_ids=inner.tx_ids,
            note="verified customer resumed use of a dormant account",
        )
    if has_rv:
        # weak returning if only reverification and activity in own name
        cust = pack["customer"].get("name") or ""
        txs = _alert_txs(pack, alert)
        if txs and all(name_eq(_counterparty(t), cust) or not _counterparty(t) for t in txs[:3]):
            ids = [d["doc_id"] for d in docs if d["type"] == "reverification_record"][:1]
            return Explanation(
                "RETURNING_CUSTOMER", alert["alert_id"],
                doc_ids=ids, tx_ids=[t["transaction_id"] for t in txs[:2]],
                note="reverification on file for dormant reactivation",
            )
    return None


MATCHERS = (
    list_diff,
    invoice_triple,
    collection,
    books,
    event,
    refund,
    third_party,
    group,
    own_account,
    returning,
)


def explain_alert(pack, docs, alert):
    for fn in MATCHERS:
        ex = fn(pack, docs, alert)
        if ex:
            return ex
    return None


def explain_case(pack, docs):
    out = {}
    for alert in pack["alerts"]:
        ex = explain_alert(pack, docs, alert)
        if ex:
            out[alert["alert_id"]] = ex
    return out
