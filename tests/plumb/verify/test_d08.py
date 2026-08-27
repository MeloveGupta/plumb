"""LLD §5.1/PRD §6 -- D08 GST-on-fee rate error (per-unit, PRD-DEVIATION
-- see d08.py's module docstring). Hand-computed: GST_ON_FEES_STANDARD
is 1800bps (default_ratebook()).
"""

from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import RateBook, default_ratebook
from plumb.verify.checks.d08 import D08GstOnFeeRateError
from plumb.verify.registry import CheckContext
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import assert_trace_reevaluates, intent, order, payment

_CHECK = D08GstOnFeeRateError()
_CTX = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())


def _unit(fee_paise, applied_tax, match_id="mtch_00001"):
    o = order(1)
    i = intent(1, 1)
    p = payment(1, 1, fee_paise=fee_paise, tax_paise=applied_tax)
    return SettlementUnit(
        unit_id="unit_00001", completeness=Completeness.FULL, order=o, lines=[], intent=i, payments=[p],
        refunds=[], transfers=[], reversals=[], disputes=[], recon_rows=[], bank_credit=None, rate_card=None,
        match_id=match_id,
    )


def test_wrong_gst_slab_fires_with_the_exact_delta():
    # fee=10,000 (Rs 100.00 MDR); correct 1800bps -> apply_bps(10_000,1800)
    # = (10_000*1800+5000)//10000 = (18_000_000+5000)//10000 = 1_800
    # wrong slab used (1200bps): apply_bps(10_000,1200) = (12_000_000+5000)//10000 = 1_200
    unit = _unit(fee_paise=10_000, applied_tax=1_200)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.defect_id == "D08"
    assert finding.amount_at_risk_paise == 600
    assert_trace_reevaluates(finding)


def test_correct_gst_does_not_fire():
    unit = _unit(fee_paise=10_000, applied_tax=1_800)
    assert _CHECK.run(unit, _CTX) is None


def test_zero_mdr_produces_zero_gst_and_does_not_fire():
    # UPI has zero MDR -- a wrong rate applied to zero is still zero
    unit = _unit(fee_paise=0, applied_tax=0)
    assert _CHECK.run(unit, _CTX) is None


def test_no_applicable_rate_declines_rather_than_raising():
    ctx = CheckContext(ratebook=RateBook({}), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())
    unit = _unit(fee_paise=10_000, applied_tax=1_200)
    assert _CHECK.run(unit, ctx) is None


def test_applies_to_declines_with_no_payments():
    o = order(1)
    i = intent(1, 1)
    unit = SettlementUnit(
        unit_id="unit_00001", completeness=Completeness.INTENT_ONLY, order=o, lines=[], intent=i, payments=[],
        refunds=[], transfers=[], reversals=[], disputes=[], recon_rows=[], bank_credit=None, rate_card=None,
        match_id=None,
    )
    assert _CHECK.applies_to(unit) is False


def test_requires_full_missing_bank_missing_settlement():
    assert _CHECK.requires == frozenset(
        {Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT}
    )
