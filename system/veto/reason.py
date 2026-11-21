from .parse import tx_amount


def _gbp(v):
    if v is None:
        return ""
    try:
        return f"£{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _cust(pack):
    return pack["customer"].get("name") or "the customer"


def _first_tx(pack):
    for rows in pack["alert_txs"].values():
        if rows:
            return rows[0]
    if pack.get("held_tx"):
        return pack["held_tx"]
    return None


def _alert_summary(pack):
    bits = []
    for a in pack["alerts"]:
        bits.append(a.get("rule_id") or "")
    return ", ".join([b for b in bits if b])


def render(verdict, code, pack, extra, explanations=None):
    """Return (reason, evidence_ids). extra is challenger/sop dict or None."""
    name = _cust(pack)
    explanations = explanations or {}
    ids = []
    amount = None
    party = ""
    doc = ""
    for ex in explanations.values():
        ids.extend(ex.doc_ids)
        ids.extend(ex.tx_ids)
        ids.extend(ex.list_ids)
        amount = amount or ex.amount
        party = party or ex.party
        if ex.doc_ids and not doc:
            doc = ex.doc_ids[0]
    if extra:
        ids.extend(extra.get("evidence") or [])
    held = pack.get("held_tx")
    if held:
        ids.append(held["transaction_id"])
        if amount is None:
            amount = tx_amount(held)
        if not party:
            party = held.get("counterparty_name") or ""
    tx = _first_tx(pack)
    if amount is None:
        for a in pack["alerts"]:
            m = a.get("measured") or {}
            for k in ("received_gbp", "total_gbp", "amount_gbp", "moved_gbp", "paid_out_gbp"):
                if m.get(k) is not None:
                    amount = m[k]
                    break
            if amount is not None:
                break
    if tx and amount is None:
        amount = tx_amount(tx)
    if tx and not party:
        party = tx.get("counterparty_name") or ""

    amt_s = _gbp(amount)
    rules = _alert_summary(pack)

    note = (extra or {}).get("note") or ""
    for ex in explanations.values():
        if ex.note and not note:
            note = ex.note

    text = _template(verdict, code, name, amt_s, party, doc, rules, note, pack)
    return text, ids


def _template(verdict, code, name, amt, party, doc, rules, note, pack):
    ask_map = {
        "RFI_SOURCE_OF_FUNDS": (
            f"Ask {name} for proof of the source of the {amt or 'funds'} received in the review window"
            + (f", including who {party} is and why they paid" if party else "")
            + "."
        ),
        "RFI_UPDATED_PROFILE": (
            f"Ask {name} for an updated expected monthly income or payment volume. "
            f"Activity in the window is well above the amount declared at onboarding."
        ),
        "RFI_PURPOSE_DOCUMENTS": (
            f"Ask {name} for the invoice or contract for the "
            + (f"{amt} payment to {party}" if party else f"{amt} payment" if amt else "payment")
            + "."
        ),
        "RFI_BUSINESS_RECORDS": (
            f"Ask {name} for the business records (takings, collection reports or accounts) that reconcile the {amt or 'activity'} in the window."
        ),
        "RFI_COUNTERPARTY_DETAILS": (
            f"Ask {name} who {party or 'the counterparty'} is, their date of birth or company number, and what the payment was for, so the internal-list match can be settled."
        ),
    }
    if verdict == "RFI":
        core = ask_map.get(code, f"Ask {name} for documents that explain the {rules} alerts.")
        second = f" Nothing on file currently explains the {rules} activity" + (f" involving {party}" if party else "") + "."
        third = " There is no indication of crime on the face of the file, so an RFI is proportionate rather than an escalation."
        return core + second + third

    if verdict == "ESCALATE":
        lead = {
            "ESC_MULE_ACTIVITY": f"{name}'s account received other people's money and passed it on.",
            "ESC_STRUCTURING": f"{name}'s activity was split to stay under a reporting or invoice threshold.",
            "ESC_UNEXPLAINED_FUNDS": f"{amt or 'Funds'} moved through {name}'s account with no credible explanation.",
            "ESC_PASS_THROUGH": f"Money arrived from several people into {name}'s account and left again quickly.",
            "ESC_INVOICE_MISMATCH": f"Invoices on file for {name} do not support the payments" + (f" to {party}" if party else "") + ".",
            "ESC_HIGH_RISK_CORRIDOR": f"{name} sent or received {amt or 'funds'} involving a higher-risk country that was not declared.",
            "ESC_ACCOUNT_MISUSE": f"Someone other than {name} appears to control or share use of the account.",
            "ESC_THIRD_PARTY_FUNDING": f"Unrelated third parties funded {name}'s account" + (f", including {party}" if party else "") + ".",
            "ESC_EARLY_REDEMPTION": f"{name} bought fund units and sold them back quickly, which can be used to move money.",
            "ESC_LISTED_PARTY": f"The counterparty" + (f" {party}" if party else "") + f" is the listed party or is controlled by them.",
        }.get(code, f"The {rules} activity on {name}'s account is unexplained or shows signs of crime.")
        mid = (" " + note.capitalize() + ".") if note else ""
        if not mid.endswith("."):
            mid += "."
        tail = " Escalate to the MLRO rather than asking the customer, which would risk tipping off."
        if doc:
            tail += f" Relied on {doc}" + (f" and the {amt} payment" if amt else "") + "."
        elif amt:
            tail += f" The {amt} movement is in the alert file."
        return lead + mid + tail

    # CLOSE
    lead = {
        "INVOICE_MATCHES": f"The {amt or 'payment'}" + (f" to {party}" if party else "") + f" matches an invoice or payment file on {name}'s record" + (f" ({doc})" if doc else "") + ".",
        "DOCUMENTED_EVENT": f"A documented event on file explains the {amt or 'funds'} for {name}" + (f" from {party}" if party else "") + (f" ({doc})" if doc else "") + ".",
        "OWN_ACCOUNT": f"The {amt or 'transfer'} moved between accounts {name} is shown to hold" + (f" on {doc}" if doc else "") + ".",
        "COLLECTION_DOCUMENTED": f"A documented collection on behalf of named people explains the payments on {name}'s account" + (f" ({doc})" if doc else "") + ".",
        "BUSINESS_RECORDS_RECONCILE": f"Business records on file reconcile to the {amt or 'activity'} on {name}'s account" + (f" ({doc})" if doc else "") + ".",
        "GROUP_COMPANY": f"The counterparty" + (f" {party}" if party else "") + f" is a company in the same group as {name}.",
        "THIRD_PARTY_DOCUMENTED": f"A documented relationship explains the third-party payer" + (f" {party}" if party else "") + f" on {name}'s account" + (f" ({doc})" if doc else "") + ".",
        "REFUND_OF_EARLIER_PAYMENT": f"The {amt or 'credit'} is a refund of an earlier payment by {name}" + (f" ({doc})" if doc else "") + ".",
        "RETURNING_CUSTOMER": f"{name} is a verified customer resuming use of a dormant account.",
        "LIST_MATCH_DIFFERENT_PARTY": f"The evidence shows the counterparty is not the listed person" + (f" {party}" if party else "") + (f" ({doc})" if doc else "") + ".",
        "WITHIN_PROFILE": f"After documented items, remaining activity fits {name}'s declared profile.",
    }.get(code, f"The evidence explains the {rules} alerts on {name}'s account.")
    mid = (" " + note.capitalize() + ".") if note else ""
    tail = f" The {rules} alerts are therefore closed." if rules else " The alerts are therefore closed."
    return (lead + mid + tail).replace("..", ".")
