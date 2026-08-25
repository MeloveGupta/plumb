"""UIUX_BRIEF.md §3.1 -- CLI run output v1 (L0/L1 only)."""

import pytest

from plumb.match.engine import MatchGroup, MatchResult
from plumb.report.cli import render_run_summary

_GREEN = "\033[38;2;47;95;74m"
_RED = "\033[38;2;168;50;30m"


def _group(n_members: int) -> MatchGroup:
    return MatchGroup(
        rule_id="ID_CHAIN", pass_="P0", confidence_bps=10_000,
        members=tuple((f"ord_{i:05d}", "intent") for i in range(n_members)),
    )


def test_renders_the_header_and_l0_l1_lines():
    result = MatchResult(groups=(_group(3),), unmatched=("bank_00001",), ambiguous=())
    output = render_run_summary(
        run_id="2026-08-28T14:22:03Z-a3f9c1", batch_id="batch_main_200", sample_label="HELD_OUT",
        tolerance_profile_name="default_v1", total_records=4, source_count=4, quarantined=0,
        result=result, reports_dir="reports/2026-08-28T14:22:03Z-a3f9c1", color=False,
    )

    assert "plumb · settlement assurance" in output
    assert "run 2026-08-28T14:22:03Z-a3f9c1 · batch_main_200 · HELD_OUT · tolerance default_v1" in output
    assert "L0  ingest         4 records · 4 sources    0 quarantined" in output
    assert "L1  match          3 matched  75.0%    1 unmatched" in output
    assert "reports/2026-08-28T14:22:03Z-a3f9c1/" in output


def test_conservation_line_balances_when_claimed_plus_unmatched_equals_total():
    result = MatchResult(groups=(_group(3),), unmatched=("bank_00001",), ambiguous=())
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="IN_SAMPLE", tolerance_profile_name="default_v1",
        total_records=4, source_count=4, quarantined=0, result=result, reports_dir="reports/r1", color=False,
    )
    assert "4 in · 4 accounted for ✓" in output


def test_conservation_line_fails_visibly_when_a_record_is_unaccounted_for():
    # total_records=5 but only 4 show up claimed+unmatched -- one record
    # vanished somewhere upstream. This must never be silently correct.
    result = MatchResult(groups=(_group(3),), unmatched=("bank_00001",), ambiguous=())
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="IN_SAMPLE", tolerance_profile_name="default_v1",
        total_records=5, source_count=4, quarantined=0, result=result, reports_dir="reports/r1", color=False,
    )
    assert "5 in · 4 accounted for ✗" in output


def test_conservation_success_is_coloured_ledger_green_when_enabled():
    result = MatchResult(groups=(_group(3),), unmatched=("bank_00001",), ambiguous=())
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="IN_SAMPLE", tolerance_profile_name="default_v1",
        total_records=4, source_count=4, quarantined=0, result=result, reports_dir="reports/r1", color=True,
    )
    assert _GREEN in output


def test_conservation_failure_is_coloured_oxide_red_when_enabled():
    result = MatchResult(groups=(_group(3),), unmatched=("bank_00001",), ambiguous=())
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="IN_SAMPLE", tolerance_profile_name="default_v1",
        total_records=5, source_count=4, quarantined=0, result=result, reports_dir="reports/r1", color=True,
    )
    assert _RED in output


def test_color_disabled_produces_plain_text():
    result = MatchResult(groups=(_group(3),), unmatched=("bank_00001",), ambiguous=())
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="IN_SAMPLE", tolerance_profile_name="default_v1",
        total_records=4, source_count=4, quarantined=0, result=result, reports_dir="reports/r1", color=False,
    )
    assert "\033[" not in output


def test_rejects_a_sample_label_that_is_not_held_out_or_in_sample():
    result = MatchResult(groups=(), unmatched=(), ambiguous=())
    with pytest.raises(ValueError, match="HELD_OUT.*IN_SAMPLE"):
        render_run_summary(
            run_id="r1", batch_id="b1", sample_label="MAYBE", tolerance_profile_name="default_v1",
            total_records=0, source_count=4, quarantined=0, result=result, reports_dir="reports/r1", color=False,
        )
