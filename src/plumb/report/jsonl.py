"""findings.jsonl / resolutions.jsonl / agent_calls.jsonl -- projections
of run.sqlite (BACKEND_SCHEMA §6). Every field traces to a column; a
round-trip test re-reads them against the DB. Money stays *_paise int
here -- rupee formatting is markdown-only.
"""

import json

from plumb.report.reader import RunPack


def findings_jsonl(pack: RunPack) -> list[str]:
    lines = []
    for f in pack.findings:
        fid = f["finding_id"]
        lines.append(json.dumps({
            "finding_id": fid,
            "unit_id": f["unit_id"],
            "defect_id": f["defect_id"],
            "severity": f["severity"],
            "amount_at_risk_paise": f["amount_at_risk_paise"],
            "on_matched_record": bool(f["on_matched_record"]),
            "conclusion": f["conclusion"],
            "recompute_steps": [
                {"step_no": s["step_no"], "label": s["label"], "formula": s["formula"],
                 "inputs": s["inputs"], "output_paise": s["output_paise"]}
                for s in pack.recompute_steps.get(fid, [])
            ],
            "evidence": pack.finding_evidence.get(fid, []),
        }, sort_keys=True))
    return lines


def resolutions_jsonl(pack: RunPack) -> list[str]:
    lines = []
    for e in pack.exceptions:
        exc_id = e["exception_id"]
        r = pack.resolutions.get(exc_id)
        if r is None:
            continue
        lines.append(json.dumps({
            "exception_id": exc_id,
            "origin": e["origin"],
            "amount_at_risk_paise": e["amount_at_risk_paise"],
            "queue_rank": e["queue_rank"],
            "outcome": r["outcome"],
            "model_claimed_outcome": r["model_claimed_outcome"],
            "was_downgraded": bool(r["was_downgraded"]),
            "downgrade_reason": r["downgrade_reason"],
            "confidence": r["confidence"],
            "chosen_hypothesis_id": r["chosen_hypothesis_id"],
            "iterations_used": r["iterations_used"],
            "stop_reason": r["stop_reason"],
            "what_was_tried": r["what_was_tried"],
            "what_would_resolve_it": r["what_would_resolve_it"],
            "hypotheses": pack.hypotheses.get(exc_id, []),
            "evidence_chain": pack.resolution_evidence.get(exc_id, []),
        }, sort_keys=True))
    return lines


def agent_calls_jsonl(pack: RunPack) -> list[str]:
    lines = []
    for c in pack.agent_calls:
        lines.append(json.dumps({
            "call_id": c["call_id"],
            "exception_id": c["exception_id"],
            "iteration": c["iteration"],
            "tool": c["tool"],
            "args": json.loads(c["args_json"]),
            "result_sha256": c["result_sha256"],
            "result_row_count": c["result_row_count"],
            "latency_ms": c["latency_ms"],
            "tokens_in": c["tokens_in"],
            "tokens_out": c["tokens_out"],
            "called_at_utc": c["called_at_utc"],
        }, sort_keys=True))
    return lines
