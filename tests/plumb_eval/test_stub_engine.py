"""GATE P0's own criterion: "scorer produces a full metrics table
against a stub engine returning zero matches." End-to-end: a real
generator-produced truth.sqlite, a real write_stub_run-produced
run.sqlite + manifest.json, scored through the real plumb-eval CLI path
(scorer.score_run) -- no crash, no division-by-zero, no missing rows.
"""

import sqlite3

from plumb.stub_engine import write_stub_run
from plumb_eval.scorer import score_run
from plumb_gen.config import GeneratorConfig
from plumb_gen.injection_config import DefectSpec, InjectionConfig
from plumb_gen.truth_db import write_truth
from plumb_gen.world import build_world

EXPECTED_METRIC_NAMES = {
    "auto_match_rate", "match_precision", "match_recall", "silent_error_rate",
    "defect_recall", "defect_precision", "root_cause_accuracy",
    "leakage_caught_inr", "leakage_missed_inr", "false_alarm_inr",
    "correct_abstention_rate", "over_abstention_rate",
    "records_per_second", "wall_clock_seconds_total",
    "llm_tokens_per_1000_records", "inr_cost_per_1000_records",
    "determinism_score",
    "residual_resolution_rate", "escalated_unresolved_rate", "exceptions_total",
    "auto_resolved_count", "proposed_count", "escalated_unresolved_count",
}


def test_scorer_produces_a_complete_metrics_table_against_the_stub_engine(tmp_path):
    config = GeneratorConfig(
        seed=42,
        batch_id="batch_test",
        batch_size=50,
        defects=InjectionConfig(defects={"D01": DefectSpec(count=3), "D02": DefectSpec(count=4)}),
    )
    world = build_world(config)

    truth_dir = tmp_path / "truth"
    truth_dir.mkdir()
    write_truth(world, truth_dir / "truth.sqlite")

    run_dir = tmp_path / "run"
    write_stub_run(
        run_dir,
        run_id="run_test",
        batch_id="batch_test",
        generator_seed=42,
        generator_config_sha256="deadbeef",
        sample_label="HELD_OUT",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:05Z",
    )

    result = score_run(run_dir, truth_dir)  # must not raise

    assert result["provisional"] is False
    assert result["sample_label"] == "HELD_OUT"
    assert set(result["metrics"]) == EXPECTED_METRIC_NAMES

    # Zero matches -> the match-family ratios are 0/0, printed NOT_MEASURED.
    assert result["metrics"]["match_precision"] == "NOT_MEASURED"
    assert result["metrics"]["silent_error_rate"] == "NOT_MEASURED"
    # 50 orders, 0 auto-matched, nonzero denominator -> a real 0.0.
    assert result["metrics"]["auto_match_rate"] == 0.0
    assert result["metrics"]["match_recall"] == 0.0

    # Zero findings -> defect precision/root-cause are 0/0, but recall's
    # denominator (7 injected defects) is nonzero -> a real 0.0.
    assert result["metrics"]["defect_precision"] == "NOT_MEASURED"
    assert result["metrics"]["root_cause_accuracy"] == "NOT_MEASURED"
    assert result["metrics"]["defect_recall"] == 0.0
    assert result["metrics"]["leakage_missed_inr"] == sum(d.amount_at_risk_paise for d in world.injected_defects)

    assert (run_dir / "eval.sqlite").exists()
    conn = sqlite3.connect(run_dir / "eval.sqlite")
    row_count = conn.execute("SELECT COUNT(*) FROM metric").fetchone()[0]
    conn.close()
    assert row_count == len(EXPECTED_METRIC_NAMES)

    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "metrics.md").exists()
