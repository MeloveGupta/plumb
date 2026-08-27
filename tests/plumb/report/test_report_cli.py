"""UIUX_BRIEF.md §3.1 -- CLI run output v1 (L0/L1), plus L2's summary +
on_matched_record sub-line (P2.12)."""

import pytest

from plumb.match.engine import MatchGroup, MatchResult
from plumb.report.cli import render_run_summary
from plumb.verify.trace import EvidenceRef, Finding, RecomputeTrace, Severity

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


def _finding(defect_id, amount_at_risk_paise, on_matched_record):
    return Finding(
        defect_id=defect_id, unit_id="unit_00001", severity=Severity.LOW,
        amount_at_risk_paise=amount_at_risk_paise, on_matched_record=on_matched_record,
        conclusion="test", trace=RecomputeTrace(steps=(), conclusion="test"), evidence=(EvidenceRef("ord_00001", "order"),),
    )


def test_l2_line_omitted_when_no_l2_data_given():
    result = MatchResult(groups=(_group(3),), unmatched=("bank_00001",), ambiguous=())
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="IN_SAMPLE", tolerance_profile_name="default_v1",
        total_records=4, source_count=4, quarantined=0, result=result, reports_dir="reports/r1", color=False,
    )
    assert "L2" not in output


def test_l2_line_and_matched_sub_line_render_with_real_figures():
    # 24 findings at 100,000 paise (matched) + 7 at 10,000 paise (unmatched):
    # 24*100,000 + 7*10,000 = 2,400,000 + 70,000 = 2,470,000 paise = Rs 24,700.00
    result = MatchResult(groups=(_group(3),), unmatched=("bank_00001",), ambiguous=())
    findings = [_finding("D01", 100_000, True) for _ in range(24)] + [_finding("D02", 10_000, False) for _ in range(7)]
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="HELD_OUT", tolerance_profile_name="default_v1",
        total_records=812, source_count=4, quarantined=4, result=result, reports_dir="reports/r1",
        l2_unit_count=812, l2_findings=findings, color=False,
    )

    assert "L2  verify         812 verified" in output
    assert "31 findings" in output
    assert "₹24,700.00 at risk" in output
    assert "└─ 24 findings on MATCHED records" in output


def test_l2_line_is_ledger_green_when_zero_at_risk():
    result = MatchResult(groups=(), unmatched=(), ambiguous=())
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="IN_SAMPLE", tolerance_profile_name="default_v1",
        total_records=0, source_count=4, quarantined=0, result=result, reports_dir="reports/r1",
        l2_unit_count=0, l2_findings=[], color=True,
    )
    assert _GREEN in output


def test_l2_line_is_oxide_red_when_money_is_at_risk():
    result = MatchResult(groups=(), unmatched=(), ambiguous=())
    output = render_run_summary(
        run_id="r1", batch_id="b1", sample_label="IN_SAMPLE", tolerance_profile_name="default_v1",
        total_records=0, source_count=4, quarantined=0, result=result, reports_dir="reports/r1",
        l2_unit_count=1, l2_findings=[_finding("D01", 500, False)], color=True,
    )
    assert _RED in output


def test_rejects_a_sample_label_that_is_not_held_out_or_in_sample():
    result = MatchResult(groups=(), unmatched=(), ambiguous=())
    with pytest.raises(ValueError, match="HELD_OUT.*IN_SAMPLE"):
        render_run_summary(
            run_id="r1", batch_id="b1", sample_label="MAYBE", tolerance_profile_name="default_v1",
            total_records=0, source_count=4, quarantined=0, result=result, reports_dir="reports/r1", color=False,
        )
