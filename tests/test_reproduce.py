"""P4.7 -- the CI-visible proxy for `make reproduce` on a fresh
container. Generates the held-out batch from the committed seed/config,
runs the rules_only arm, scores it, and asserts the full headline
metric set is produced -- with no API key.

The real fresh-container test is a manual pre-submit step (README);
this catches a broken `make reproduce` in CI.
"""

from datetime import date
from pathlib import Path

from plumb.pipeline import execute_run

from plumb_gen.config_loader import load_generator_config
from plumb_gen.io import write_sources
from plumb_gen.truth_db import write_truth
from plumb_gen.world import build_world

from plumb_eval.scorer import score_run

_HEADLINE_METRICS = {
    "auto_match_rate", "match_precision", "match_recall", "silent_error_rate",
    "defect_recall", "defect_precision", "root_cause_accuracy",
    "leakage_caught_inr", "leakage_missed_inr", "false_alarm_inr",
    "correct_abstention_rate", "over_abstention_rate", "determinism_score",
    "residual_resolution_rate", "escalated_unresolved_rate", "exceptions_total",
}


def test_make_reproduce_rules_only_leg(tmp_path):
    config = load_generator_config(
        Path("configs/config_b.yaml"), seed=42, batch_id="batch_main_200",
        batch_as_of=date(2026, 8, 20), tier="T2",
    )
    world = build_world(config)
    data_dir = tmp_path / "batch_main_200"
    write_sources(world, data_dir / "dataset")
    (data_dir / "truth").mkdir(parents=True)
    write_truth(world, data_dir / "truth" / "truth.sqlite")

    outcome = execute_run(
        data_dir=data_dir, out_dir=tmp_path / "reports", ablation="rules_only",
        sample_label="HELD_OUT", generator_seed=42,
        generator_config=Path("configs/config_b.yaml"), as_of=date(2026, 8, 26),
    )
    payload = score_run(outcome.run_dir, data_dir / "truth", allow_provisional=True)

    assert payload["sample_label"] == "HELD_OUT"
    assert _HEADLINE_METRICS <= set(payload["metrics"])
    # rules_only shape: escalates everything, resolves nothing
    assert payload["metrics"]["residual_resolution_rate"] == 0.0
    assert payload["metrics"]["escalated_unresolved_rate"] == 1.0
    assert payload["metrics"]["correct_abstention_rate"] == 1.0
    for name in ("close.md", "exceptions.md", "findings.jsonl", "metrics.md"):
        assert (outcome.run_dir / name).exists(), name
