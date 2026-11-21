from datetime import datetime, date


def _parse_iso_date(s):
    if not s:
        return None
    s = str(s)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def pack_case(case, inst):
    cid = case["customer_id"]
    customer = inst["customers"].get(cid) or {}
    alert_ids = list(case.get("alert_ids") or [])
    alerts = []
    for aid in alert_ids:
        a = inst["alerts_by_id"].get(aid)
        if a:
            alerts.append(a)
    txs_by_id = inst["txs_by_id"]
    alert_txs = {}
    for a in alerts:
        rows = []
        for tid in a.get("transaction_ids") or []:
            t = txs_by_id.get(tid)
            if t:
                rows.append(t)
        alert_txs[a["alert_id"]] = rows

    all_txs = list(inst["txs_by_customer"].get(cid) or [])
    rw = case.get("review_window") or {}
    wfrom = _parse_iso_date(rw.get("from"))
    wto = _parse_iso_date(rw.get("to"))

    def in_window(t, pad=2):
        d = _parse_iso_date((t.get("booked_at") or "")[:10])
        if not d or not wfrom or not wto:
            return True
        from datetime import timedelta
        return (wfrom - timedelta(days=pad)) <= d <= (wto + timedelta(days=pad))

    window_txs = [t for t in all_txs if in_window(t)]
    held_id = case.get("held_payment_id")
    held_tx = txs_by_id.get(held_id) if held_id else None

    list_hits = []
    for a in alerts:
        if a.get("rule_id") != "TM22":
            continue
        measured = a.get("measured") or {}
        entry_id = measured.get("list_entry")
        entry = inst["list_by_id"].get(entry_id) if entry_id else None
        list_hits.append({
            "alert": a,
            "entry_id": entry_id,
            "entry": entry,
            "matched_on": measured.get("matched_on") or "",
            "matched_party": measured.get("matched_party") or "",
        })

    return {
        "case": case,
        "customer": customer,
        "alerts": alerts,
        "alert_txs": alert_txs,
        "all_txs": all_txs,
        "window_txs": window_txs,
        "held_tx": held_tx,
        "docs_raw": list(inst["docs_by_customer"].get(cid) or []),
        "reviews": list(inst["reviews_by_customer"].get(cid) or []),
        "list_hits": list_hits,
        "window_from": wfrom,
        "window_to": wto,
        "institution": inst["name"],
        "policy": inst["policy"],
        "list_by_id": inst["list_by_id"],
        "allow_ids": None,  # filled after parse
    }


def allow_ids_for(pack, inst):
    ids = set()
    for t in pack["all_txs"]:
        ids.add(t["transaction_id"])
    for d in pack["docs_raw"]:
        ids.add(d["doc_id"])
    for e in inst["list_by_id"]:
        ids.add(e)
    if pack["held_tx"]:
        ids.add(pack["held_tx"]["transaction_id"])
    for a in pack["alerts"]:
        ids.add(a["alert_id"])
        for tid in a.get("transaction_ids") or []:
            ids.add(tid)
    return ids
