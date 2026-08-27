"""LLD §5.1/PRD §6 -- D03 refund netting error. Hand-computed: every
expected paise figure is worked on paper first.

Base numbers throughout: gross=200,000; commission 1500bps ->
apply_bps(200_000,1500) = 30,000; mdr=0 -> pre_debit_transfer =
200,000 - 30,000 - 0 = 170,000.
"""

from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import default_ratebook
from plumb.verify.checks.d02 import D02ShortSettlementInTolerance
from plumb.verify.checks.d03 import D03RefundNettingError
from plumb.verify.registry import CheckContext
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import assert_trace_reevaluates, intent, order, payment, rate_card, recon, refund

_D03 = D03RefundNettingError()
_D02 = D02ShortSettlementInTolerance()
_CTX = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())

_GROSS = 200_000
_COMMISSION_BPS = 1500
_PRE_DEBIT_TRANSFER = 170_000  # 200,000 - 30,000 - 0


def _unit(credit_paise, debit_paise, refunds=(), match_id="mtch_00001"):
    o = order(1, amount=_GROSS)
    i = intent(1, 1, commission_bps=_COMMISSION_BPS)
    rc = rate_card(1, commission_bps=_COMMISSION_BPS)
    p = payment(1, 1, amount=_GROSS, fee_paise=0)
    r = recon(1, 1, credit_paise=credit_paise, debit_paise=debit_paise)
    return SettlementUnit(
        unit_id="unit_00001", completeness=Completeness.FULL, order=o, lines=[], intent=i, payments=[p],
        refunds=list(refunds), transfers=[], reversals=[], disputes=[], recon_rows=[r], bank_credit=None,
        rate_card=rc, match_id=match_id,
    )


def test_under_netted_refund_fires_with_the_full_missing_amount():
    unit = _unit(credit_paise=_PRE_DEBIT_TRANSFER, debit_paise=0, refunds=[refund(1, 1, 50_000)])
    finding = _D03.run(unit, _CTX)

    assert finding is not None
    assert finding.defect_id == "D03"
    assert finding.amount_at_risk_paise == 50_000
    assert finding.on_matched_record is True
    assert_trace_reevaluates(finding)


def test_correctly_netted_refund_does_not_fire():
    unit = _unit(credit_paise=_PRE_DEBIT_TRANSFER - 50_000, debit_paise=50_000, refunds=[refund(1, 1, 50_000)])
    assert _D03.run(unit, _CTX) is None


def test_applies_to_declines_with_no_refund():
    # A D02-shaped unit (in-band shortfall, no refund at all) never
    # reaches run() -- structurally excluded, not a numeric coincidence.
    unit = _unit(credit_paise=_PRE_DEBIT_TRANSFER - 500, debit_paise=0, refunds=[])
    assert _D03.applies_to(unit) is False


def test_requires_full_and_missing_bank_only():
    assert _D03.requires == frozenset({Completeness.FULL, Completeness.MISSING_BANK})


def test_d02_does_not_cross_fire_on_a_d03_shaped_unit():
    """The user's explicit question: on a D03 order, D02's independently
    re-derived `expected` (120,000, netted from unit.refunds) is already
    correct while `actual` (170,000, built from the observed, wrongly
    un-netted debit_paise) looks like an overpayment -- delta=-50,000,
    D02's own guard discards it."""
    unit = _unit(credit_paise=_PRE_DEBIT_TRANSFER, debit_paise=0, refunds=[refund(1, 1, 50_000)])
    assert _D02.run(unit, _CTX) is None
    assert _D03.run(unit, _CTX) is not None  # D03 is the one that fires on this order
