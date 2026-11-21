from .parse import name_eq, tx_amount


def _tm01_multiple(pack):
    m = None
    for a in pack["alerts"]:
        if a.get("rule_id") == "TM01":
            try:
                val = float((a.get("measured") or {}).get("multiple") or 0)
            except (TypeError, ValueError):
                val = 0
            m = val if m is None else max(m, val)
    return m


def apply_sop(pack, explanations, policy):
    """Downgrade CLOSE -> RFI only. explanations: dict."""
    if not explanations:
        return None
    if len(explanations) < len(pack["alerts"]):
        return None  # not a full CLOSE yet

    codes = {ex.code for ex in explanations.values()}
    multiple = _tm01_multiple(pack) or 0.0
    rfi_at = float(policy.get("own_account_rfi_multiple") or 5)

    # 5x own-account (not documented events)
    only_own = codes <= {"OWN_ACCOUNT", "RETURNING_CUSTOMER"}
    if only_own and multiple >= rfi_at:
        return {
            "verdict": "RFI",
            "code": "RFI_UPDATED_PROFILE",
            "evidence": _ids(explanations),
            "note": "own-account transfers take activity to five times the declared profile",
        }

    # PX £10k invoice gate
    if pack.get("institution") == "payments_fx":
        threshold = float(policy.get("px_invoice_gbp") or 10000)
        held = pack.get("held_tx")
        client = pack["customer"].get("name") or ""
        targets = []
        if held:
            targets.append(held)
        else:
            for rows in pack["alert_txs"].values():
                for t in rows:
                    if t.get("direction") == "out":
                        targets.append(t)
        needs = []
        for t in targets:
            amt = tx_amount(t)
            if amt is None:
                continue
            if float(amt) >= threshold and not name_eq(_counterparty_name(t), client):
                needs.append(t)
        if needs:
            has_inv = any(ex.code in {"INVOICE_MATCHES", "GROUP_COMPANY", "OWN_ACCOUNT"} for ex in explanations.values())
            if not has_inv:
                ev = [t["transaction_id"] for t in needs[:3]]
                return {
                    "verdict": "RFI",
                    "code": "RFI_PURPOSE_DOCUMENTS",
                    "evidence": ev,
                    "note": "a payment of £10,000 or more to someone other than the client needs an invoice or contract on file",
                }
    return None


def _counterparty_name(t):
    return t.get("counterparty_name") or ""


def _ids(explanations):
    out = []
    for ex in explanations.values():
        out.extend(ex.doc_ids)
        out.extend(ex.tx_ids)
        out.extend(ex.list_ids)
    # unique preserve
    seen = set()
    keep = []
    for i in out:
        if i and i not in seen:
            seen.add(i)
            keep.append(i)
    return keep
