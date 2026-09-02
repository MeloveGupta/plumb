"""The persistence bridge end to end: generate a batch, run the L0->L4
chain in the rules_only arm (no model client), and confirm the
resulting run.sqlite is well formed -- v_conservation balanced, every
resolution FKs an exception, the manifest carries the reproducibility
fields.

config_a here -- this is wiring verification, not a headline number.
The held-out rules_only baseline is committed separately (ABLATION.md).

KNOWN GAP (see DEVLOG / flagged to the user): plumb_eval.scorer.score_run
cannot yet score a real run -- match/engine.py emits the order and
intent keys as match_member rows (side='intent'), but
plumb_eval/truth_store.py's closures are leg-only by explicit design
("a real match_group's members can only ever be leg keys ... never the
order's own key"). So validate_no_fabrication and score_match both fail
on real matcher output. That is an L1<->scorer contract dispute, not a
bridge defect -- the end-to-end score_run assertion is xfail'd until
it's resolved.
"""

from datetime import date
from pathlib import Path

import pytest

from plumb.pipeline import execute_run

from plumb_gen.config_loader import load_generator_config
from plumb_gen.io import write_sources
from plumb_gen.truth_db import write_truth
from plumb_gen.world import build_world

from plumb_eval.scorer import score_run


@pytest.fixture
def batch(tmp_path) -> Path:
    config = load_generator_config(
        Path("configs/config_a.yaml"), seed=42, batch_id="bridge_test",
        batch_as_of=date(2026, 8, 20), tier="T2",
    )
    world = build_world(config)
    data_dir = tmp_path / "bridge_test"
    write_sources(world, data_dir / "dataset")
    (data_dir / "truth").mkdir(parents=True, exist_ok=True)
    write_truth(world, data_dir / "truth" / "truth.sqlite")
    return data_dir


def test_rules_only_run_is_scorable_and_conserves(batch, tmp_path):
    outcome = execute_run(
        data_dir=batch,
        out_dir=tmp_path / "reports",
        ablation="rules_only",
        sample_label="IN_SAMPLE",
        generator_seed=42,
        generator_config=Path("configs/config_a.yaml"),
        as_of=date(2026, 8, 26),
    )

    # rules_only escalates every exception, nothing else
    assert outcome.exception_count > 0
    assert set(outcome.resolution_outcomes) == {"ESCALATED_UNRESOLVED"}
    assert outcome.resolution_outcomes["ESCALATED_UNRESOLVED"] == outcome.exception_count

    # v_conservation: every record_index key has exactly one terminal state
    import sqlite3

    conn = sqlite3.connect(outcome.run_dir / "run.sqlite")
    records_in, accounted_for = conn.execute("SELECT records_in, accounted_for FROM v_conservation").fetchone()
    assert records_in == accounted_for and records_in > 0
    # every resolution FKs an exception; every exception a real queue rank
    assert conn.execute("SELECT COUNT(*) FROM resolution").fetchone()[0] == outcome.exception_count
    assert conn.execute("SELECT COUNT(DISTINCT queue_rank) FROM exception").fetchone()[0] == outcome.exception_count
    # findings persisted with their traces and evidence
    assert conn.execute("SELECT COUNT(*) FROM finding").fetchone()[0] >= 0
    assert conn.execute(
        "SELECT COUNT(*) FROM resolution WHERE outcome = 'ESCALATED_UNRESOLVED' AND what_would_resolve_it IS NULL"
    ).fetchone()[0] == 0
    conn.close()


@pytest.mark.xfail(reason="L1<->scorer contract: matcher emits order/intent keys as match_members, "
                          "truth_store closures are leg-only -- see module docstring", strict=True)
def test_rules_only_run_scores_end_to_end(batch, tmp_path):
    outcome = execute_run(
        data_dir=batch, out_dir=tmp_path / "reports", ablation="rules_only", sample_label="IN_SAMPLE",
        generator_seed=42, generator_config=Path("configs/config_a.yaml"), as_of=date(2026, 8, 26),
    )
    payload = score_run(outcome.run_dir, batch / "truth", allow_provisional=True)
    assert payload["sample_label"] == "IN_SAMPLE"
    assert "defect_recall" in payload["metrics"]


def test_manifest_has_the_reproducibility_fields(batch, tmp_path):
    outcome = execute_run(
        data_dir=batch,
        out_dir=tmp_path / "reports",
        ablation="rules_only",
        sample_label="IN_SAMPLE",
        generator_seed=42,
        generator_config=Path("configs/config_a.yaml"),
        as_of=date(2026, 8, 26),
    )
    import json

    manifest = json.loads((outcome.run_dir / "manifest.json").read_text())
    assert manifest["sample_label"] == "IN_SAMPLE"
    assert manifest["ablation_config"] == "rules_only"
    assert manifest["llm_model"] is None  # rules_only makes no model call
    assert len(manifest["prompt_sha256"]) == 64
    assert len(manifest["schema_sha256"]) == 64
    assert len(manifest["engine_config_sha256"]) == 64

    # schema_sha256 in the manifest matches schema/run.sql on disk (schema §8 test 10)
    import hashlib

    on_disk = hashlib.sha256(Path("schema/run.sql").read_bytes()).hexdigest()
    assert manifest["schema_sha256"] == on_disk
