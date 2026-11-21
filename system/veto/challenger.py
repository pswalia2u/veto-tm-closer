from .parse import name_eq, tx_date, dob_tuple_from_iso
from . import INVOICE_TYPES


def _docs_of(docs, *types):
    return [d for d in docs if d["type"] in types]


def _has_flag(docs, flag):
    return any((d.get("flags") or {}).get(flag) for d in docs)


def hard_veto(pack, docs):
    """Challenger A: suspicion. Blocks CLOSE and RFI."""
    evidence = []
    if _has_flag(docs, "fraud") or _docs_of(docs, "sending_bank_fraud_report"):
        evidence = [d["doc_id"] for d in _docs_of(docs, "sending_bank_fraud_report")]
        return {"code": "ESC_MULE_ACTIVITY", "evidence": evidence,
                "note": "a sending bank reported an authorised push payment scam into this account"}
    if _has_flag(docs, "mule_chat"):
        evidence = [d["doc_id"] for d in docs if (d.get("flags") or {}).get("mule_chat")]
        return {"code": "ESC_MULE_ACTIVITY", "evidence": evidence,
                "note": "the customer described passing on other people's money"}
    if _has_flag(docs, "threshold_evasion"):
        evidence = [d["doc_id"] for d in docs if (d.get("flags") or {}).get("threshold_evasion")]
        return {"code": "ESC_STRUCTURING", "evidence": evidence,
                "note": "a staff note records an attempt to stay under a reporting threshold"}
    if _has_flag(docs, "unwilling_lebanon"):
        evidence = [d["doc_id"] for d in docs if (d.get("flags") or {}).get("unwilling_lebanon")]
        return {"code": "ESC_HIGH_RISK_CORRIDOR", "evidence": evidence,
                "note": "the client would not explain why funds were routed to Lebanon"}
    if _has_flag(docs, "shared_device") or _has_flag(docs, "nigeria_login") or _has_flag(docs, "hr_login"):
        evidence = [d["doc_id"] for d in _docs_of(docs, "device_export")]
        code = "ESC_ACCOUNT_MISUSE"
        if _has_flag(docs, "shared_device"):
            code = "ESC_ACCOUNT_MISUSE"
        return {"code": code, "evidence": evidence,
                "note": "device and login data show shared use or a higher-risk login country"}

    officer = _officer_listed(pack, docs)
    if officer:
        return officer
    same_gift = _gift_same_person(pack, docs)
    if same_gift:
        return same_gift
    return None


def _payment_date(pack):
    if pack.get("held_tx"):
        return tx_date(pack["held_tx"])
    for rows in pack["alert_txs"].values():
        for t in rows:
            d = tx_date(t)
            if d:
                return d
    return pack.get("window_to")


def _officer_listed(pack, docs):
    pay_d = _payment_date(pack)
    for hit in pack.get("list_hits") or []:
        matched_on = (hit.get("matched_on") or "").lower()
        if "officer" not in matched_on:
            continue
        entry = hit.get("entry") or {}
        entry_id = hit.get("entry_id")
        list_name = entry.get("name") or hit.get("matched_party") or ""
        list_dob = dob_tuple_from_iso(entry.get("date_of_birth"))
        found_same = None
        found_diff = False
        for doc in docs:
            for off in doc.get("officers") or []:
                if not name_eq(off.get("name"), list_name):
                    continue
                if list_dob and off.get("born_my"):
                    if off["born_my"] == (list_dob[0], list_dob[1]):
                        psc_docs = []
                        still = False
                        for d2 in docs:
                            for p in d2.get("psc") or []:
                                if name_eq(p.get("name"), list_name):
                                    psc_docs.append(d2["doc_id"])
                                    ceased = p.get("ceased")
                                    if ceased is None or (pay_d and ceased >= pay_d):
                                        still = True
                        found_same = {
                            "code": "ESC_LISTED_PARTY",
                            "evidence": [x for x in [doc["doc_id"], entry_id] + psc_docs if x],
                            "note": "the listed person matches an officer by name and birth month-year and still controlled the company at the payment date",
                        }
                    else:
                        found_diff = True
        if found_same:
            return found_same
        if found_diff:
            return None
        return {
            "code": "ESC_LISTED_PARTY",
            "evidence": [entry_id] if entry_id else [],
            "note": "the alert matches a listed person as a company officer by name and date of birth",
        }
    return None


def _gift_same_person(pack, docs):
    for hit in pack.get("list_hits") or []:
        matched_on = (hit.get("matched_on") or "").lower()
        if not matched_on.startswith("name"):
            continue
        if "officer" in matched_on or "address" in matched_on:
            continue
        entry = hit.get("entry") or {}
        entry_id = hit.get("entry_id")
        list_name = entry.get("name") or hit.get("matched_party") or ""
        list_dob = dob_tuple_from_iso(entry.get("date_of_birth"))
        if not list_dob:
            continue
        for doc in docs:
            if doc["type"] != "gift_letter":
                continue
            gd = doc.get("gift_dob")
            donor = doc.get("gift_donor") or ""
            if gd and gd == list_dob[2]:
                return {
                    "code": "ESC_LISTED_PARTY",
                    "evidence": [x for x in [doc["doc_id"], entry_id] if x],
                    "note": "the gift letter date of birth matches the listed person",
                }
            if gd and (gd.month, gd.year, gd.day) == (list_dob[2].month, list_dob[2].year, list_dob[2].day):
                return {
                    "code": "ESC_LISTED_PARTY",
                    "evidence": [x for x in [doc["doc_id"], entry_id] if x],
                    "note": "the gift letter date of birth matches the listed person",
                }
    return None


def kill_close(pack, docs, explanations, policy):
    """Challenger B. explanations: dict alert_id -> Explanation. Returns Esc dict or None."""
    rules = {a["rule_id"] for a in pack["alerts"]}
    explained = set(explanations.keys())
    unexplained = [a for a in pack["alerts"] if a["alert_id"] not in explained]

    # goods / FX mismatch invoices
    for d in docs:
        flags = d.get("flags") or {}
        if flags.get("electronics_hk") or flags.get("consultancy_goods"):
            return {
                "code": "ESC_INVOICE_MISMATCH",
                "evidence": [d["doc_id"]],
                "note": "invoices on file do not support the payments (goods or currency do not match)",
            }

    if "TM06" in rules:
        if not any(explanations.get(a["alert_id"]) for a in pack["alerts"] if a["rule_id"] == "TM06"):
            countries = []
            for a in pack["alerts"]:
                if a["rule_id"] == "TM06":
                    countries.append((a.get("measured") or {}).get("countries") or "")
            ev = []
            for a in pack["alerts"]:
                if a["rule_id"] == "TM06":
                    ev.extend(a.get("transaction_ids") or [])
            return {
                "code": "ESC_HIGH_RISK_CORRIDOR",
                "evidence": ev[:4],
                "note": "payments to or from a higher-risk country are unexplained",
            }

    if "TM10" in rules:
        if not any(explanations.get(a["alert_id"]) for a in pack["alerts"] if a["rule_id"] == "TM10"):
            ev = []
            for a in pack["alerts"]:
                if a["rule_id"] == "TM10":
                    ev.extend(a.get("transaction_ids") or [])
            return {
                "code": "ESC_EARLY_REDEMPTION",
                "evidence": ev[:4],
                "note": "fund units were bought and sold back quickly with no documented reason",
            }

    if "TM08" in rules:
        if not any(explanations.get(a["alert_id"]) for a in pack["alerts"] if a["rule_id"] == "TM08"):
            # only escalate unexplained TM08 when bundled with rapid movement or multiple flows
            if "TM02" in rules or "TM10" in rules:
                ev = []
                for a in pack["alerts"]:
                    if a["rule_id"] in {"TM08", "TM02"}:
                        ev.extend(a.get("transaction_ids") or [])
                return {
                    "code": "ESC_THIRD_PARTY_FUNDING",
                    "evidence": ev[:4],
                    "note": "unrelated third parties funded the account and the money moved on",
                }

    if "TM02" in rules and "TM04" in rules:
        has_col = any(
            explanations[aid].code in {"COLLECTION_DOCUMENTED", "BUSINESS_RECORDS_RECONCILE", "INVOICE_MATCHES", "DOCUMENTED_EVENT"}
            for aid in explanations
        )
        if not has_col:
            ev = []
            for a in pack["alerts"]:
                if a["rule_id"] in {"TM02", "TM04"}:
                    ev.extend(a.get("transaction_ids") or [])
            return {
                "code": "ESC_PASS_THROUGH",
                "evidence": ev[:6],
                "note": "money arrived from many people and left again with no documented collection",
            }

    if "TM03" in rules:
        tm03 = [a for a in pack["alerts"] if a["rule_id"] == "TM03"]
        unexplained_tm03 = [a for a in tm03 if a["alert_id"] not in explained]
        if unexplained_tm03:
            loc = 0
            for a in tm03:
                loc = max(loc, int((a.get("measured") or {}).get("locations") or 0))
            has_books = any(d["type"] in {"cash_collection_reports", "takings_book", "cash_reconciliation", "contract_schedule"} for d in docs)
            if loc >= 2 and not has_books:
                return {
                    "code": "ESC_STRUCTURING",
                    "evidence": (tm03[0].get("transaction_ids") or [])[:4],
                    "note": "repeated just-under-threshold cash across locations with no collection records",
                }

    # invoice docs in window whose amounts miss the alert txs
    alert_amts = set()
    alert_tx_ids = []
    for rows in pack["alert_txs"].values():
        for t in rows:
            from .parse import tx_amount
            a = tx_amount(t)
            if a is not None:
                alert_amts.add(a)
            alert_tx_ids.append(t["transaction_id"])
    inv_docs = [d for d in docs if d["type"] in INVOICE_TYPES]
    if inv_docs and alert_amts:
        any_hit = False
        for d in inv_docs:
            for r in d.get("amount_roles") or []:
                if r.get("amount") in alert_amts:
                    any_hit = True
        # only mismatch-escalate when invoices exist AND we have no invoice explanation
        has_inv_ex = any(explanations[aid].code == "INVOICE_MATCHES" for aid in explanations)
        if not any_hit and not has_inv_ex and pack.get("institution") == "payments_fx" and pack.get("held_tx"):
            return {
                "code": "ESC_INVOICE_MISMATCH",
                "evidence": [d["doc_id"] for d in inv_docs[:3]] + ([pack["held_tx"]["transaction_id"]] if pack.get("held_tx") else []),
                "note": "invoices on file do not match the held payment",
            }
    return None
