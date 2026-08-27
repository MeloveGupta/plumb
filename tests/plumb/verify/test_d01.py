"""LLD §5.1/PRD §6 -- D01 commission rate drift. Hand-computed: every
expected paise figure below is worked on paper first (apply_bps with
ROUND_HALF_UP, ties round up), never derived by calling apply_bps and
trusting its output.
"""

from dataclasses import replace
from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import default_ratebook
from plumb.verify.checks.d01 import D01CommissionRateDrift
from plumb.verify.registry import CheckContext
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import assert_trace_reevaluates, intent, order, rate_card

_CHECK = D01CommissionRateDrift()
_CTX = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())


def _unit(gross, contracted_bps, applied_bps, completeness=Completeness.FULL, payments=None, transfers=None, match_id="mtch_00001"):
    o = order(1, amount=gross)
    i = intent(1, 1, commission_bps=applied_bps)
    rc = rate_card(1, commission_bps=contracted_bps)
    return SettlementUnit(
        unit_id="unit_00001", completeness=completeness, order=o, lines=[], intent=i,
        payments=payments if payments is not None else [], refunds=[],
        transfers=transfers if transfers is not None else [], reversals=[], disputes=[], recon_rows=[],
        bank_credit=None, rate_card=rc, match_id=match_id,
    )


def test_no_finding_when_applied_matches_contracted():
    unit = _unit(gross=200_000, contracted_bps=1500, applied_bps=1500)
    assert _CHECK.run(unit, _CTX) is None


def test_drift_caught_with_the_exact_delta():
    # gross=200,000; contracted 1500bps -> 200,000*1500/10000 = 30,000
    # applied 1600bps -> 200,000*1600/10000 = 32,000; delta = 2,000
    unit = _unit(gross=200_000, contracted_bps=1500, applied_bps=1600)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.defect_id == "D01"
    assert finding.amount_at_risk_paise == 2_000
    assert finding.on_matched_record is True
    assert_trace_reevaluates(finding)


def test_intent_only_unit_still_supports_d01():
    """LLD §5.1: 'a unit at INTENT_ONLY still supports D01' -- same
    drift as the previous test, but on a unit with no payment/transfer
    at all and no match_id, proving D01 needs neither."""
    unit = _unit(gross=200_000, contracted_bps=1500, applied_bps=1600, completeness=Completeness.INTENT_ONLY, match_id=None)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.amount_at_risk_paise == 2_000
    assert finding.on_matched_record is False
    assert_trace_reevaluates(finding)


def test_bps_mismatch_that_rounds_to_the_same_paise_figure_does_not_fire():
    # gross=100; contracted 1500bps -> (100*1500+5000)//10000 = 15
    # applied 1501bps -> (100*1501+5000)//10000 = 15 -- same paise figure
    unit = _unit(gross=100, contracted_bps=1500, applied_bps=1501)
    assert _CHECK.run(unit, _CTX) is None


def test_applies_to_declines_when_no_rate_card_resolved():
    unit = _unit(gross=200_000, contracted_bps=1500, applied_bps=1600)
    unit = replace(unit, rate_card=None)
    assert _CHECK.applies_to(unit) is False


def test_requires_every_completeness_value():
    assert _CHECK.requires == frozenset(
        {Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT, Completeness.INTENT_ONLY}
    )
