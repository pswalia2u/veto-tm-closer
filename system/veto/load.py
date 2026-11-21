import json
import re
from pathlib import Path

from . import HR_FALLBACK


def read_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _countries_from_policy(text):
    m = re.search(
        r"Higher-risk countries[^\n]*:\s*(.+?)(?:\n-|\n\n)",
        text,
        re.I | re.S,
    )
    if not m:
        return list(HR_FALLBACK)
    blob = m.group(1)
    blob = re.sub(r"\s+", " ", blob).strip().rstrip(".")
    parts = [p.strip() for p in blob.split(",") if p.strip()]
    return parts or list(HR_FALLBACK)


def parse_policy(text, inst_name):
    countries = _countries_from_policy(text)
    return {
        "institution": inst_name,
        "hr_countries": {c.lower() for c in countries},
        "own_account_rfi_multiple": 5.0,
        "px_invoice_gbp": 10000.0,
        "raw": text,
    }


def load_institution(folder):
    folder = Path(folder).resolve()
    name = folder.name
    policy_path = folder / "POLICY.md"
    policy_text = policy_path.read_text(encoding="utf-8") if policy_path.exists() else ""
    evidence_meta = read_jsonl(folder / "evidence.jsonl")
    docs_by_customer = {}
    for ev in evidence_meta:
        fpath = folder / ev["file"]
        try:
            text = fpath.read_text(encoding="utf-8")
        except OSError:
            text = ""
        rec = dict(ev)
        rec["text"] = text
        docs_by_customer.setdefault(ev["customer_id"], []).append(rec)

    alerts = read_jsonl(folder / "alerts.jsonl")
    alerts_by_id = {a["alert_id"]: a for a in alerts}
    alerts_by_customer = {}
    for a in alerts:
        alerts_by_customer.setdefault(a["customer_id"], []).append(a)

    customers = {c["customer_id"]: c for c in read_jsonl(folder / "customers.jsonl")}
    txs = read_jsonl(folder / "transactions.jsonl")
    txs_by_id = {t["transaction_id"]: t for t in txs}
    txs_by_customer = {}
    for t in txs:
        txs_by_customer.setdefault(t["customer_id"], []).append(t)

    reviews_by_customer = {}
    rev_path = folder / "previous_reviews.jsonl"
    if rev_path.exists():
        for r in read_jsonl(rev_path):
            reviews_by_customer.setdefault(r["customer_id"], []).append(r)

    list_by_id = {}
    list_path = folder / "internal_list.jsonl"
    if list_path.exists():
        for e in read_jsonl(list_path):
            list_by_id[e["entry_id"]] = e

    return {
        "folder": folder,
        "name": name,
        "policy": parse_policy(policy_text, name),
        "cases": read_jsonl(folder / "cases.jsonl"),
        "alerts_by_id": alerts_by_id,
        "alerts_by_customer": alerts_by_customer,
        "customers": customers,
        "txs_by_id": txs_by_id,
        "txs_by_customer": txs_by_customer,
        "docs_by_customer": docs_by_customer,
        "reviews_by_customer": reviews_by_customer,
        "list_by_id": list_by_id,
    }
