"""LLD §5.3/PRD §6 -- D02 short settlement in tolerance. THE FLAGSHIP.

Every expected figure is hand-computed on paper first:
tolerance = DEFAULT_V1 (amount_abs_paise=100, amount_rel_bps=10).
gross=1,000,000; commission 1500bps -> apply_bps(1_000_000,1500)
  = (1_000_000*1500+5000)//10000 = (1_500_000_000+5000)//10000 = 150_000
mdr fee_paise=20_000 (observed, trusted) -> expected_transfer = 1_000_000
  - 150_000 - 20_000 = 830_000
band_paise(830_000) = max(100, apply_bps(830_000,10))
  = max(100, (8_300_000+5000)//10000) = max(100, 830) = 830
"""

from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import default_ratebook
from plumb.verify.checks.d02 import D02ShortSettlementInTolerance, compute_expected_net
from plumb.verify.registry import CheckContext
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import assert_trace_reevaluates, dispute, intent, order, payment, rate_card, recon, refund

_CHECK = D02ShortSettlementInTolerance()
_CTX = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())

_GROSS = 1_000_000
_COMMISSION_BPS = 1500
_MDR_FEE = 20_000
_EXPECTED = 830_000  # gross - commission(150,000) - mdr(20,000)
_BAND = 830


def _unit(credit_paise, debit_paise=0, completeness=Completeness.FULL, bank_credit=None, refunds=(), disputes=(), match_id="mtch_00001"):
    o = order(1, amount=_GROSS)
    i = intent(1, 1, commission_bps=_COMMISSION_BPS)
    rc = rate_card(1, commission_bps=_COMMISSION_BPS)
    p = payment(1, 1, amount=_GROSS, fee_paise=_MDR_FEE)
    r = recon(1, 1, credit_paise=credit_paise, debit_paise=debit_paise)
    return SettlementUnit(
        unit_id="unit_00001", completeness=completeness, order=o, lines=[], intent=i, payments=[p],
        refunds=list(refunds), transfers=[], reversals=[], disputes=list(disputes), recon_rows=[r],
        bank_credit=bank_credit, rate_card=rc, match_id=match_id,
    )


def test_compute_expected_net_matches_the_hand_computed_figure():
    unit = _unit(credit_paise=_EXPECTED)
    assert compute_expected_net(unit, _CTX) == _EXPECTED


def test_in_band_shortfall_fires():
    # short by exactly 500 paise, inside the 830-paise band
    unit = _unit(credit_paise=_EXPECTED - 500)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.defect_id == "D02"
    assert finding.amount_at_risk_paise == 500
    assert finding.on_matched_record is True
    assert_trace_reevaluates(finding)


def test_out_of_band_shortfall_does_not_fire():
    # short by 2,000 paise -- past the 830-paise band; the matcher's own
    # P3 already would have failed to attach this, so it is an ordinary
    # break, not a silent one
    unit = _unit(credit_paise=_EXPECTED - 2_000)
    assert _CHECK.run(unit, _CTX) is None


def test_overpaid_or_exact_settlement_does_not_fire():
    unit = _unit(credit_paise=_EXPECTED)
    assert _CHECK.run(unit, _CTX) is None


def test_missing_bank_in_flight_trap_does_not_fire():
    """The T2 in-flight case: settlement_recon.credit_paise is never
    reduced when the bank leg is genuinely partial/unattached -- it still
    reflects the full target, so expected == actual and this must not
    fire even though bank_credit is None."""
    unit = _unit(credit_paise=_EXPECTED, completeness=Completeness.MISSING_BANK, bank_credit=None, match_id="mtch_00001")
    assert _CHECK.run(unit, _CTX) is None


def test_missing_bank_with_a_genuine_shortfall_still_fires():
    """Proves requires={FULL, MISSING_BANK} is doing real work, not just
    tolerating the in-flight null case: a real in-band shortfall on a
    MISSING_BANK unit (bank leg just hasn't arrived for unrelated
    reasons) must still be caught."""
    unit = _unit(credit_paise=_EXPECTED - 500, completeness=Completeness.MISSING_BANK, bank_credit=None)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.amount_at_risk_paise == 500
    assert_trace_reevaluates(finding)


def test_refund_and_dispute_are_netted_before_comparison():
    # refund 40,000 + dispute deduction 10,000 = 50,000 debit, both well
    # under expected_transfer (830,000) so no clamping triggers ->
    # expected_net = 830,000 - 50,000 = 780,000
    unit = _unit(credit_paise=780_000, refunds=[refund(1, 1, 40_000)], disputes=[dispute(1, 1, 10_000)])
    assert compute_expected_net(unit, _CTX) == 780_000
    assert _CHECK.run(unit, _CTX) is None  # settles exactly, not short


def test_refund_plus_dispute_exceeding_expected_transfer_is_clamped_to_zero():
    # refund 900,000 alone already exceeds expected_transfer (830,000) ->
    # debit clamps to 830,000 -> expected_net = 0
    unit = _unit(credit_paise=0, refunds=[refund(1, 1, 900_000)])
    assert compute_expected_net(unit, _CTX) == 0


def test_applies_to_declines_with_no_recon_rows():
    unit = _unit(credit_paise=_EXPECTED)
    unit_no_recon = SettlementUnit(
        unit_id=unit.unit_id, completeness=unit.completeness, order=unit.order, lines=[], intent=unit.intent,
        payments=unit.payments, refunds=[], transfers=[], reversals=[], disputes=[], recon_rows=[],
        bank_credit=None, rate_card=unit.rate_card, match_id=unit.match_id,
    )
    assert _CHECK.applies_to(unit_no_recon) is False


def test_requires_full_and_missing_bank_only():
    assert _CHECK.requires == frozenset({Completeness.FULL, Completeness.MISSING_BANK})
