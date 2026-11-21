import json
import re
from pathlib import Path

from . import CODE_VERDICT
from .load import load_institution
from .pack import pack_case, allow_ids_for
from .parse import parse_docs
from .match import explain_case
from .sop import apply_sop
from .challenger import hard_veto, kill_close
from .reason import render
from .llm import refine_ambiguous, warn_if_disabled


ESC_PRIORITY = (
    "ESC_LISTED_PARTY",
    "ESC_MULE_ACTIVITY",
    "ESC_STRUCTURING",
    "ESC_INVOICE_MISMATCH",
    "ESC_PASS_THROUGH",
    "ESC_HIGH_RISK_CORRIDOR",
    "ESC_THIRD_PARTY_FUNDING",
    "ESC_EARLY_REDEMPTION",
    "ESC_ACCOUNT_MISUSE",
    "ESC_UNEXPLAINED_FUNDS",
)

RFI_BY_RULE = {
    "TM01": None,  # kind-specific
    "TM02": "RFI_PURPOSE_DOCUMENTS",
    "TM03": "RFI_BUSINESS_RECORDS",
    "TM04": "RFI_COUNTERPARTY_DETAILS",
    "TM05": "RFI_SOURCE_OF_FUNDS",
    "TM07": "RFI_SOURCE_OF_FUNDS",
    "TM08": "RFI_COUNTERPARTY_DETAILS",
    "TM22": "RFI_COUNTERPARTY_DETAILS",
}


def _unique(ids):
    seen = set()
    out = []
    for i in ids:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out[:12]


def _residual_rfi(pack):
    kind = (pack["customer"].get("kind") or "individual").lower()
    rules = [a.get("rule_id") for a in pack["alerts"]]
    if "TM22" in rules:
        return "RFI_COUNTERPARTY_DETAILS"
    if "TM01" in rules:
        return "RFI_BUSINESS_RECORDS" if kind == "business" else "RFI_SOURCE_OF_FUNDS"
    if pack.get("institution") == "payments_fx" and pack.get("held_tx"):
        return "RFI_PURPOSE_DOCUMENTS"
    for r in ("TM08", "TM04", "TM02", "TM03", "TM05", "TM07"):
        if r in rules:
            code = RFI_BY_RULE[r]
            if r == "TM03" and kind != "business":
                return "RFI_SOURCE_OF_FUNDS"
            if r == "TM05" and kind == "business":
                return "RFI_BUSINESS_RECORDS"
            return code
    return "RFI_PURPOSE_DOCUMENTS"


def _close_code(pack, explanations):
    codes = [explanations[a["alert_id"]].code for a in pack["alerts"] if a["alert_id"] in explanations]
    if any(c == "LIST_MATCH_DIFFERENT_PARTY" for c in codes):
        return "LIST_MATCH_DIFFERENT_PARTY"
    order = [
        "INVOICE_MATCHES", "COLLECTION_DOCUMENTED", "BUSINESS_RECORDS_RECONCILE",
        "DOCUMENTED_EVENT", "OWN_ACCOUNT", "GROUP_COMPANY", "THIRD_PARTY_DOCUMENTED",
        "REFUND_OF_EARLIER_PAYMENT", "RETURNING_CUSTOMER",
    ]
    for c in order:
        if c in codes:
            return c
    return codes[0] if codes else "INVOICE_MATCHES"


def decide_case(pack, docs, policy, allow):
    extra = None
    veto = hard_veto(pack, docs)
    explanations = {}
    if veto:
        verdict, code = "ESCALATE", veto["code"]
        extra = veto
    else:
        explanations = explain_case(pack, docs)
        all_explained = len(explanations) == len(pack["alerts"]) and pack["alerts"]
        if all_explained:
            sop = apply_sop(pack, explanations, policy)
            if sop:
                verdict, code = sop["verdict"], sop["code"]
                extra = sop
            else:
                kill = kill_close(pack, docs, explanations, policy)
                if kill:
                    verdict, code = "ESCALATE", kill["code"]
                    extra = kill
                else:
                    verdict, code = "CLOSE", _close_code(pack, explanations)
        else:
            kill = kill_close(pack, docs, explanations, policy)
            if kill:
                verdict, code = "ESCALATE", kill["code"]
                extra = kill
            else:
                # unexplained TM06/TM10 already handled in kill_close; residual RFI
                verdict, code = "RFI", _residual_rfi(pack)
                # Ambiguous only: no suspicion veto, no SOP close. Model may CLOSE,
                # RFI, or ESCALATE. Invalid or invented IDs are discarded.
                refined = refine_ambiguous(pack, docs, allow)
                if refined:
                    verdict, code = refined["verdict"], refined["reason_code"]
                    extra = {
                        "note": refined["reason"],
                        "evidence": refined["evidence"],
                        "reason_override": refined["reason"],
                        "evidence_override": refined["evidence"],
                    }

    if CODE_VERDICT.get(code) != verdict:
        verdict = CODE_VERDICT.get(code, verdict)

    reason, evid = render(verdict, code, pack, extra, explanations)
    docs_first, txs = [], []
    for i in evid:
        if not i or i not in allow:
            continue
        # Document and list ids are not transaction ids (those contain -T).
        if "-T" in i:
            txs.append(i)
        else:
            docs_first.append(i)
    evid = docs_first + txs
    if not evid:
        # still cite something real
        for a in pack["alerts"]:
            for tid in a.get("transaction_ids") or []:
                if tid in allow:
                    evid.append(tid)
            if evid:
                break
        if pack.get("held_tx") and pack["held_tx"]["transaction_id"] in allow:
            evid.append(pack["held_tx"]["transaction_id"])
        evid = _unique(evid)

    if extra and extra.get("reason_override"):
        reason = extra["reason_override"]
        kept = [i for i in extra.get("evidence_override") or [] if i in allow]
        if kept:
            evid = kept
    reason = reason.replace("..", ".")
    parts = [p.strip() for p in re.split(r"(?<=[a-zA-Z0-9)])\.\s+(?=[A-Z])", reason) if p.strip()]
    if len(parts) < 2:
        parts.append("The decision follows the institution's transaction monitoring SOP")
    reason = ". ".join(parts[:4]).rstrip(".") + "."

    return {
        "case_id": pack["case"]["case_id"],
        "alert_ids": list(pack["case"].get("alert_ids") or []),
        "verdict": verdict,
        "reason_code": code,
        "reason": reason,
        "evidence": evid,
    }


def run_folder(inst_dir, out_path):
    warn_if_disabled()
    inst = load_institution(inst_dir)
    policy = inst["policy"]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for case in inst["cases"]:
            pack = pack_case(case, inst)
            allow = allow_ids_for(pack, inst)
            docs = parse_docs(pack["docs_raw"])
            rec = decide_case(pack, docs, policy, allow)
            fh.write(json.dumps(rec, ensure_ascii=True) + "\n")
