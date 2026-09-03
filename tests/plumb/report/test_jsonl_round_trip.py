"""BACKEND_SCHEMA §6 -- "every field in every JSONL line traces to a
column. A CI test round-trips a sample of lines back against the
database and fails on any divergence." This is that test.
"""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from plumb.pipeline import execute_run
from plumb.report.jsonl import agent_calls_jsonl, findings_jsonl, resolutions_jsonl
from plumb.report.reader import load_run_pack

from plumb_gen.config_loader import load_generator_config
from plumb_gen.io import write_sources
from plumb_gen.world import build_world


@pytest.fixture
def run_dir(tmp_path) -> Path:
    config = load_generator_config(
        Path("configs/config_a.yaml"), seed=11, batch_id="rt", batch_as_of=date(2026, 8, 20), tier="T2"
    )
    world = build_world(config)
    data_dir = tmp_path / "rt"
    write_sources(world, data_dir / "dataset")
    outcome = execute_run(
        data_dir=data_dir, out_dir=tmp_path / "reports", ablation="rules_only", sample_label="IN_SAMPLE",
        generator_seed=11, generator_config=Path("configs/config_a.yaml"), as_of=date(2026, 8, 26),
    )
    return outcome.run_dir


def test_findings_jsonl_round_trips_to_the_finding_table(run_dir):
    pack = load_run_pack(run_dir)
    conn = sqlite3.connect(run_dir / "run.sqlite")
    lines = [json.loads(x) for x in findings_jsonl(pack)]
    assert len(lines) == conn.execute("SELECT COUNT(*) FROM finding").fetchone()[0]

    for line in lines:
        row = conn.execute(
            "SELECT unit_id, defect_id, severity, amount_at_risk_paise, on_matched_record, conclusion "
            "FROM finding WHERE finding_id = ?", (line["finding_id"],)
        ).fetchone()
        assert row == (
            line["unit_id"], line["defect_id"], line["severity"], line["amount_at_risk_paise"],
            int(line["on_matched_record"]), line["conclusion"],
        )
        db_steps = conn.execute(
            "SELECT step_no, label, formula, output_paise FROM recompute_step WHERE finding_id = ? ORDER BY step_no",
            (line["finding_id"],)
        ).fetchall()
        assert [(s["step_no"], s["label"], s["formula"], s["output_paise"]) for s in line["recompute_steps"]] == db_steps
    conn.close()


def test_resolutions_jsonl_round_trips_to_the_resolution_table(run_dir):
    pack = load_run_pack(run_dir)
    conn = sqlite3.connect(run_dir / "run.sqlite")
    lines = [json.loads(x) for x in resolutions_jsonl(pack)]
    assert len(lines) == conn.execute("SELECT COUNT(*) FROM resolution").fetchone()[0]

    for line in lines:
        row = conn.execute(
            "SELECT outcome, model_claimed_outcome, was_downgraded, confidence, iterations_used, "
            "stop_reason, what_was_tried, what_would_resolve_it FROM resolution WHERE exception_id = ?",
            (line["exception_id"],)
        ).fetchone()
        assert row == (
            line["outcome"], line["model_claimed_outcome"], int(line["was_downgraded"]), line["confidence"],
            line["iterations_used"], line["stop_reason"], line["what_was_tried"], line["what_would_resolve_it"],
        )
    conn.close()


def test_agent_calls_jsonl_round_trips(run_dir):
    pack = load_run_pack(run_dir)
    conn = sqlite3.connect(run_dir / "run.sqlite")
    lines = [json.loads(x) for x in agent_calls_jsonl(pack)]
    assert len(lines) == conn.execute("SELECT COUNT(*) FROM agent_call").fetchone()[0]
    for line in lines:
        row = conn.execute(
            "SELECT iteration, tool, args_json, result_sha256, tokens_in, tokens_out, called_at_utc "
            "FROM agent_call WHERE call_id = ?", (line["call_id"],)
        ).fetchone()
        assert row == (
            line["iteration"], line["tool"], json.dumps(line["args"]), line["result_sha256"],
            line["tokens_in"], line["tokens_out"], line["called_at_utc"],
        )
    conn.close()
