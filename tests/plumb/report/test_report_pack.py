"""P4.1/P4.2 -- the close pack. Generated end to end by execute_run;
these check the arithmetic and the no-truncation rule, not the exact
typography.
"""

from datetime import date
from pathlib import Path

import pytest

from plumb.pipeline import execute_run
from plumb.report.reader import load_run_pack

from plumb_gen.config_loader import load_generator_config
from plumb_gen.io import write_sources
from plumb_gen.world import build_world


@pytest.fixture
def run_dir(tmp_path) -> Path:
    config = load_generator_config(
        Path("configs/config_a.yaml"), seed=7, batch_id="pack_test", batch_as_of=date(2026, 8, 20), tier="T2"
    )
    world = build_world(config)
    data_dir = tmp_path / "pack_test"
    write_sources(world, data_dir / "dataset")
    outcome = execute_run(
        data_dir=data_dir, out_dir=tmp_path / "reports", ablation="rules_only", sample_label="IN_SAMPLE",
        generator_seed=7, generator_config=Path("configs/config_a.yaml"), as_of=date(2026, 8, 26),
    )
    return outcome.run_dir


def test_all_five_pack_files_exist(run_dir):
    for name in ("close.md", "exceptions.md", "findings.jsonl", "resolutions.jsonl", "agent_calls.jsonl"):
        assert (run_dir / name).exists(), name


def test_close_waterfall_reconciles(run_dir):
    pack = load_run_pack(run_dir)
    gross = sum(o["gross_paise"] for o in pack.orders)
    deductions = (
        sum(p["fee_paise"] for p in pack.payments)
        + sum(p["tax_paise"] for p in pack.payments)
        + sum(i["expected_commission_paise"] for i in pack.intents)
        + sum(i["expected_tcs_paise"] for i in pack.intents)
        + sum(i["expected_tds_paise"] for i in pack.intents)
        + sum(r["amount_paise"] for r in pack.refunds)
        + sum(r["amount_paise"] for r in pack.reversals)
        + sum(d["deducted_amount_paise"] for d in pack.disputes)
    )
    expected_settleable = gross - deductions

    close = (run_dir / "close.md").read_text()
    assert "cash position" in close.lower()
    assert "forecast" not in close.lower().replace("not a forecast", "")  # never *labelled* a forecast
    # the reconciled figure appears verbatim
    from plumb.domain.money import format_inr

    assert format_inr(gross) in close
    assert format_inr(expected_settleable) in close
    # settled + in-flight + held partition every transfer's amount
    total_transfer = sum(t["amount_paise"] for t in pack.transfers)
    settled = sum(t["amount_paise"] for t in pack.transfers if t["settled_at_utc"] is not None
                  and not (t["on_hold"] == 1 and t["on_hold_until_utc"] is None))
    held = sum(t["amount_paise"] for t in pack.transfers if t["on_hold"] == 1 and t["on_hold_until_utc"] is None)
    in_flight = total_transfer - settled - held
    assert settled >= 0 and held >= 0 and in_flight >= 0
    assert settled + held + in_flight == total_transfer


def test_exceptions_header_states_the_percentage_and_nothing_is_truncated(run_dir):
    pack = load_run_pack(run_dir)
    text = (run_dir / "exceptions.md").read_text()
    from plumb.domain.money import format_inr

    processed = sum(o["gross_paise"] for o in pack.orders)
    assert f"of {format_inr(processed)} processed" in text  # denominator never buried (APP_FLOW §5.4)
    assert "escalated" in text
    # every exception id is present -- no truncation (UIUX §4.3 / APP_FLOW §5.4)
    for e in pack.exceptions:
        assert e["exception_id"] in text
