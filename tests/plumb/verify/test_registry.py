"""LLD §5.2 -- the Check registry. Uses hand-built fake checks, not
D01/D02, so registry behaviour (requires-gating, applies_to-gating,
skip tallying, findings_by_unit shape) is tested independent of any
real check's own logic.
"""

from dataclasses import dataclass
from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import default_ratebook
from plumb.verify.registry import CheckContext, SkipSummary, run_checks
from plumb.verify.trace import Finding, RecomputeTrace, Severity, VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import intent, order


def _ctx():
    return CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())


def _unit(unit_id, completeness):
    o, i = order(1), intent(1, 1)
    return SettlementUnit(
        unit_id=unit_id, completeness=completeness, order=o, lines=[], intent=i, payments=[], refunds=[],
        transfers=[], reversals=[], disputes=[], recon_rows=[], bank_credit=None, rate_card=None, match_id=None,
    )


def _finding(unit_id):
    return Finding(
        defect_id="D99", unit_id=unit_id, severity=Severity.LOW, amount_at_risk_paise=1, on_matched_record=False,
        conclusion="test", trace=RecomputeTrace(steps=(), conclusion="test"), evidence=(),
    )


@dataclass(frozen=True)
class _AlwaysFires:
    defect_id: str = "D99"
    requires: frozenset = frozenset({Completeness.FULL})

    def applies_to(self, unit):
        return True

    def run(self, unit, ctx):
        return _finding(unit.unit_id)


@dataclass(frozen=True)
class _NeverApplies:
    defect_id: str = "D98"
    requires: frozenset = frozenset({Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT, Completeness.INTENT_ONLY})

    def applies_to(self, unit):
        return False

    def run(self, unit, ctx):
        raise AssertionError("run() must never be called when applies_to() is False")


def test_a_check_fires_on_a_unit_whose_completeness_is_in_requires():
    unit = _unit("unit_00001", Completeness.FULL)
    result = run_checks([unit], [_AlwaysFires()], _ctx())

    assert result.findings_by_unit == {"unit_00001": [_finding("unit_00001")]}
    assert result.skipped == []


def test_a_check_is_skipped_and_tallied_when_completeness_is_not_in_requires():
    unit = _unit("unit_00001", Completeness.INTENT_ONLY)
    result = run_checks([unit], [_AlwaysFires()], _ctx())

    assert result.findings_by_unit == {"unit_00001": []}
    assert result.skipped == [
        SkipSummary(defect_id="D99", reason="completeness=intent_only not in requires", unit_count=1)
    ]


def test_a_check_is_skipped_and_tallied_when_applies_to_declines():
    unit = _unit("unit_00001", Completeness.FULL)
    result = run_checks([unit], [_NeverApplies()], _ctx())

    assert result.findings_by_unit == {"unit_00001": []}
    assert result.skipped == [SkipSummary(defect_id="D98", reason="applies_to() declined", unit_count=1)]


def test_skip_counts_aggregate_across_units_sharing_the_same_reason():
    units = [_unit("unit_00001", Completeness.INTENT_ONLY), _unit("unit_00002", Completeness.MISSING_SETTLEMENT)]
    result = run_checks(units, [_AlwaysFires()], _ctx())

    assert len(result.skipped) == 2
    assert {s.unit_count for s in result.skipped} == {1}


def test_every_unit_appears_in_findings_by_unit_even_with_no_findings():
    unit = _unit("unit_00001", Completeness.INTENT_ONLY)
    result = run_checks([unit], [], _ctx())

    assert result.findings_by_unit == {"unit_00001": []}
