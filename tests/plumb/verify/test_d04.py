"""LLD §5.1/PRD §6 -- D04 TCS basis error. Hand-computed: every expected
paise figure is worked on paper first. TCS_BPS=50 (default_ratebook()).
"""

from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import RateBook, default_ratebook
from plumb.verify.checks.d04 import D04TcsBasisError
from plumb.verify.registry import CheckContext
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import intent, order, rate_card, refund

_CHECK = D04TcsBasisError()
_CTX = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())

_GROSS = 200_000


def _unit(applied_tcs, refunds=(), match_id="mtch_00001"):
    o = order(1, amount=_GROSS)
    i = intent(1, 1, tcs_paise=applied_tcs)
    rc = rate_card(1)
    return SettlementUnit(
        unit_id="unit_00001", completeness=Completeness.INTENT_ONLY, order=o, lines=[], intent=i, payments=[],
        refunds=list(refunds), transfers=[], reversals=[], disputes=[], recon_rows=[], bank_credit=None,
        rate_card=rc, match_id=match_id,
    )


def test_gross_basis_defect_fires_with_the_exact_delta():
    # world's wrong value: apply_bps(200_000, 50) = 1,000 (gross basis)
    # correct: apply_bps(150_000, 50) = 750 (net of the 50,000 refund)
    unit = _unit(applied_tcs=1_000, refunds=[refund(1, 1, 50_000)])
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.defect_id == "D04"
    assert finding.amount_at_risk_paise == 250


def test_clean_no_refund_does_not_fire():
    unit = _unit(applied_tcs=1_000, refunds=[])  # apply_bps(200_000, 50) = 1,000
    assert _CHECK.run(unit, _CTX) is None


def test_clean_order_with_an_organic_refund_does_not_fire():
    """Regression guard: world.py originally computed intent.
    expected_tcs_paise on GROSS for every non-D04 order, even one with an
    organic (non-forced) refund, since TCS was computed before the
    organic-refund branch ran -- an 11-false-positive generator bug this
    check's tax-law-correct recompute exposed (root-caused and fixed in
    world.py's _correct_tcs_for_organic_refunds; see
    tests/plumb_gen/test_world.py's regression test for the generator
    side). Post-fix, a clean order's applied TCS is already net of its
    own organic refund, so this must NOT fire."""
    unit = _unit(applied_tcs=800, refunds=[refund(1, 1, 40_000)])  # apply_bps(160_000, 50) = 800, now correct
    assert _CHECK.run(unit, _CTX) is None


def test_no_applicable_rate_declines_rather_than_raising():
    ctx = CheckContext(ratebook=RateBook({}), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())
    unit = _unit(applied_tcs=1_000)
    assert _CHECK.run(unit, ctx) is None


def test_requires_every_completeness_value():
    assert _CHECK.requires == frozenset(
        {Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT, Completeness.INTENT_ONLY}
    )
