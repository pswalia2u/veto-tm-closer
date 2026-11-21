"""Optional xAI pass for residual RFI cases only.

Hard vetoes and SOP closes never reach this module. If XAI_API_KEY is
unset, or the model cites an ID that is not in the case, the caller
keeps the deterministic decision. Replies are cached so five judging
runs return the same verdict, reason code, reason, and evidence.
"""
import fcntl
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from . import CODE_VERDICT, CLOSE_CODES, RFI_CODES, ESC_CODES

DEFAULT_BASE = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4.7"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".llm_cache"

SYSTEM = """You close UK transaction-monitoring alerts. One verdict for the whole case.
CLOSE only if the documents explain every alert. If you are unsure, RFI, do not CLOSE.
If there is suspicion (fraud report, mule, structuring, listed person still in control, unexplained higher-risk country, early redemption with no life event), ESCALATE. Never RFI once there is suspicion.
reason_code must belong to the verdict. reason is 2-4 sentences naming this case's people, amounts, and document IDs. evidence is a list of IDs copied exactly from the case. Never invent an ID.
Return only JSON: {"verdict":"CLOSE|RFI|ESCALATE","reason_code":"...","reason":"...","evidence":["..."]}"""


def _enabled():
    return bool(os.environ.get("XAI_API_KEY"))


def warn_if_disabled():
    """Print once per run. Silent when Grok will actually be called."""
    import sys
    if os.environ.get("VETO_LLM") == "0":
        sys.stderr.write("VETO_LLM=0; leftovers will not use Grok.\n")
        return
    if not _enabled():
        sys.stderr.write("XAI_API_KEY not set; leftovers will not use Grok.\n")


def _model():
    return os.environ.get("XAI_MODEL") or DEFAULT_MODEL


def _base():
    return (os.environ.get("XAI_BASE_URL") or DEFAULT_BASE).rstrip("/")


def _endpoint():
    return _base() + "/chat/completions"


def _clip(text, n):
    text = text or ""
    if len(text) <= n:
        return text
    return text[:n] + "…"


def build_prompt(pack, docs, allow):
    cust = pack["customer"]
    declared = cust.get("declared") or {}
    lines = [
        f"Institution: {pack.get('institution')}",
        f"Customer: {cust.get('name')} ({cust.get('kind')})",
        f"Activity: {cust.get('business_activity') or cust.get('occupation') or ''}",
        f"Declared income/month: {declared.get('monthly_income_gbp')} turnover/year: {declared.get('annual_turnover_gbp')}",
        f"Expected countries: {', '.join(declared.get('expected_countries') or [])}",
        f"Allowed IDs include the ones below. Do not cite any other ID.",
        "",
        "Alerts:",
    ]
    for a in pack["alerts"]:
        lines.append(f"- {a.get('alert_id')} {a.get('rule_id')} {a.get('message')}")
        for t in pack["alert_txs"].get(a["alert_id"]) or []:
            lines.append(
                f"  tx {t.get('transaction_id')} {t.get('direction')} {t.get('channel')} "
                f"£{t.get('amount_gbp')} {t.get('counterparty_name')} {t.get('counterparty_country')} "
                f"ref={t.get('reference')}"
            )
    if pack.get("held_tx"):
        t = pack["held_tx"]
        lines.append(
            f"Held payment {t.get('transaction_id')} £{t.get('amount_gbp')} to {t.get('counterparty_name')}"
        )
    lines.append("")
    lines.append("Documents:")
    # Stable order: type, doc_id
    ordered = sorted(docs, key=lambda d: (d.get("type") or "", d.get("doc_id") or ""))
    for d in ordered[:14]:
        if d.get("type") in {"proof_of_address"}:
            continue
        lines.append(f"--- {d.get('doc_id')} type={d.get('type')} title={d.get('title')} dated={d.get('dated')}")
        lines.append(_clip(d.get("text") or "", 900))
    if pack.get("list_hits"):
        lines.append("")
        lines.append("Internal list hits:")
        for h in pack["list_hits"]:
            entry = h.get("entry") or {}
            lines.append(
                f"- {h.get('entry_id')} {entry.get('name')} dob={entry.get('date_of_birth')} "
                f"matched_on={h.get('matched_on')} party={h.get('matched_party')}"
            )
    lines.append("")
    lines.append("CLOSE codes: " + ", ".join(CLOSE_CODES))
    lines.append("RFI codes: " + ", ".join(RFI_CODES))
    lines.append("ESCALATE codes: " + ", ".join(ESC_CODES))
    return "\n".join(lines)


def _cache_path(body):
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return CACHE_DIR / (digest + ".json")


def _post(body):
    key = os.environ["XAI_API_KEY"]
    req = urllib.request.Request(
        _endpoint(),
        data=body.encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8")


def _parse_content(raw):
    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        return None
    return json.loads(content[start : end + 1])


def _accept(obj, allow):
    if not isinstance(obj, dict):
        return None
    verdict = obj.get("verdict")
    code = obj.get("reason_code")
    if verdict not in {"CLOSE", "RFI", "ESCALATE"}:
        return None
    if CODE_VERDICT.get(code) != verdict:
        return None
    evid = obj.get("evidence") or []
    if not isinstance(evid, list):
        return None
    kept = []
    for i in evid:
        if isinstance(i, str) and i in allow and i not in kept:
            kept.append(i)
    if verdict == "CLOSE":
        # A close must cite a real document or list entry, not only a transaction.
        if not any("-T" not in i for i in kept):
            return None
    reason = obj.get("reason") or ""
    if not isinstance(reason, str) or len(reason.split()) < 12:
        return None
    return {
        "verdict": verdict,
        "reason_code": code,
        "reason": reason.strip(),
        "evidence": kept[:12],
    }


def refine_ambiguous(pack, docs, allow):
    """Return a validated model decision, or None to keep the rule verdict."""
    if not _enabled():
        return None
    if os.environ.get("VETO_LLM") == "0":
        return None
    prompt = build_prompt(pack, docs, allow)
    payload = {
        "model": _model(),
        "temperature": 0,
        "seed": 1,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    }
    body = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    path = _cache_path(_endpoint() + "\n" + body)
    raw = None
    use_cache = os.environ.get("VETO_LLM_NOCACHE") != "1"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if use_cache and path.exists():
                raw = path.read_text(encoding="utf-8")
            else:
                try:
                    raw = _post(body)
                except (urllib.error.URLError, TimeoutError, OSError, KeyError):
                    return None
                try:
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(raw, encoding="utf-8")
                    tmp.replace(path)
                except OSError:
                    pass
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    try:
        obj = _parse_content(raw)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    return _accept(obj, allow)
