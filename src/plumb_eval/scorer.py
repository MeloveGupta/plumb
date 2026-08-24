"""TRD §8.3: plumb-eval --run reports/{run_id} --truth data/{batch_id}/truth.
Joins on record_key, computes every PRD §7 metric, emits eval.sqlite,
metrics.json, and a Markdown table.
"""

import json
from pathlib import Path

from plumb_eval.eval_db import write_eval_result
from plumb_eval.manifest import gate
from plumb_eval.metrics import NOT_MEASURED, compute_metrics
from plumb_eval.run_reader import RunData, open_run_db_readonly
from plumb_eval.scoring import score_abstentions, score_all_matches, score_defects, validate_no_fabrication
from plumb_eval.truth_store import TruthStore
from plumb_gen.truth_db import open_existing_truth_db


def score_run(run_dir: Path, truth_dir: Path, *, allow_provisional: bool = False) -> dict:
    manifest, is_provisional = gate(run_dir, allow_provisional=allow_provisional)
    sample_label = manifest["sample_label"]

    run_conn = open_run_db_readonly(str(run_dir / "run.sqlite"))
    truth_conn = open_existing_truth_db(truth_dir / "truth.sqlite")
    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()

    validate_no_fabrication(run, truth)  # TRD §8.3 -- fabrication fails the run, not a metric

    scored_matches = score_all_matches(run, truth)
    scored_defects, true_positive_finding_ids = score_defects(run, truth)
    scored_abstentions = score_abstentions(run, truth)
    metrics = compute_metrics(
        run, truth, scored_matches, scored_defects, true_positive_finding_ids, scored_abstentions
    )

    write_eval_result(
        run_dir / "eval.sqlite", metrics, scored_matches, scored_defects, scored_abstentions, sample_label
    )

    payload = {
        "provisional": is_provisional,
        "sample_label": sample_label,
        "metrics": {m.name: (m.value if m.value is not None else NOT_MEASURED) for m in metrics},
    }
    (run_dir / "metrics.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (run_dir / "metrics.md").write_text(_render_markdown(metrics, sample_label, is_provisional))

    return payload


def _render_markdown(metrics, sample_label: str, is_provisional: bool) -> str:
    lines: list[str] = []
    if is_provisional:
        lines.append("**PROVISIONAL** (dirty working tree)")
        lines.append("")
    lines.append(f"Sample: `{sample_label}`")
    lines.append("")
    lines.append("| metric | value | unit |")
    lines.append("|---|---|---|")
    for m in metrics:
        value = NOT_MEASURED if m.value is None else m.value
        lines.append(f"| {m.name} | {value} | {m.unit} |")
    return "\n".join(lines) + "\n"
