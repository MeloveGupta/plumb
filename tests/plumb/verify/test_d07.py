"""LLD §5.1/PRD §6 -- D07 reversal without refund. Hand-computed: every
expected paise figure is worked on paper first.
"""

from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import default_ratebook
from plumb.verify.checks.d07 import D07ReversalWithoutRefund
from plumb.verify.registry import CheckContext
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import intent, order, payment, refund, reversal, transfer

_CHECK = D07ReversalWithoutRefund()
_CTX = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 1), config=VerifyConfig())


def _unit(reversals=(), refunds=(), match_id="mtch_00001"):
    o = order(1)
    i = intent(1, 1)
    p = payment(1, 1)
    t = transfer(1, 1, amount=98_000)
    return SettlementUnit(
        unit_id="unit_00001", completeness=Completeness.FULL, order=o, lines=[], intent=i, payments=[p],
        refunds=list(refunds), transfers=[t], reversals=list(reversals), disputes=[], recon_rows=[],
        bank_credit=None, rate_card=None, match_id=match_id,
    )


def test_reversal_with_no_refund_fires():
    unit = _unit(reversals=[reversal(1, 1, 98_000)])
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.defect_id == "D07"
    assert finding.amount_at_risk_paise == 98_000


def test_reversal_with_a_covering_full_refund_does_not_fire():
    unit = _unit(reversals=[reversal(1, 1, 98_000)], refunds=[refund(1, 1, 98_000)])
    assert _CHECK.run(unit, _CTX) is None


def test_no_reversal_at_all_does_not_apply():
    unit = _unit()
    assert _CHECK.applies_to(unit) is False


def test_requires_full_and_missing_bank_only():
    assert _CHECK.requires == frozenset({Completeness.FULL, Completeness.MISSING_BANK})
