"""LLD §5.1/PRD §6 -- D05 TDS rate/basis error. Hand-computed: every
expected paise figure is worked on paper first. TDS_BPS=10
(default_ratebook()). gross=200,000; commission 1500bps=30,000; mdr=0
-> transfer_amount_paise_true = 170,000 (the wrong basis D05 injects).
"""

from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import default_ratebook
from plumb.verify.checks.d05 import D05TdsRateOrBasisError
from plumb.verify.registry import CheckContext
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import assert_trace_reevaluates, intent, order

_CHECK = D05TdsRateOrBasisError()
_CTX = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())

_GROSS = 200_000


def _unit(applied_tds, match_id="mtch_00001"):
    o = order(1, amount=_GROSS)
    i = intent(1, 1, tds_paise=applied_tds)
    return SettlementUnit(
        unit_id="unit_00001", completeness=Completeness.INTENT_ONLY, order=o, lines=[], intent=i, payments=[],
        refunds=[], transfers=[], reversals=[], disputes=[], recon_rows=[], bank_credit=None, rate_card=None,
        match_id=match_id,
    )


def test_net_basis_defect_fires_with_the_exact_delta():
    # world's wrong value: apply_bps(170_000, 10) = 170 (net/transfer basis)
    # correct: apply_bps(200_000, 10) = 200 (gross basis)
    unit = _unit(applied_tds=170)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.defect_id == "D05"
    assert finding.amount_at_risk_paise == 30
    assert_trace_reevaluates(finding)


def test_clean_gross_basis_does_not_fire():
    unit = _unit(applied_tds=200)  # apply_bps(200_000, 10) = 200
    assert _CHECK.run(unit, _CTX) is None


def test_missing_tds_line_fires_hand_fixture_only():
    """No generator support for this PRD submode -- hand-built fixture
    only, not verifiable against a real batch."""
    unit = _unit(applied_tds=0)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.amount_at_risk_paise == 200


def test_stale_legacy_rate_fires_hand_fixture_only():
    """No generator support for this PRD submode -- hand-built fixture
    only, not verifiable against a real batch. applied_tds computed as
    if at the legacy 100bps (1%) rate: apply_bps(200_000, 100) = 2,000."""
    unit = _unit(applied_tds=2_000)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.amount_at_risk_paise == 1_800


def test_requires_every_completeness_value():
    assert _CHECK.requires == frozenset(
        {Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT, Completeness.INTENT_ONLY}
    )
