"""LLD §5.1/PRD §6 -- D06 orphaned hold. Hand-computed: age in days is
worked out on paper first. d06_hold_age_days=14 (VerifyConfig default).
"""

from datetime import date

from plumb.domain.tolerance import DEFAULT_V1
from plumb.rules.ratebook import default_ratebook
from plumb.verify.checks.d06 import D06OrphanedHold
from plumb.verify.registry import CheckContext
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit

from _verify_fixtures import intent, order, payment, transfer

_CHECK = D06OrphanedHold()
_CTX = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 7, 20), config=VerifyConfig())


def _unit(placed_at, on_hold=True, on_hold_until=None, amount=50_000, match_id="mtch_00001"):
    o = order(1, placed_at=placed_at)
    i = intent(1, 1)
    p = payment(1, 1)
    t = transfer(1, 1, amount=amount, on_hold=on_hold, on_hold_until=on_hold_until, settled_at=None)
    return SettlementUnit(
        unit_id="unit_00001", completeness=Completeness.MISSING_SETTLEMENT, order=o, lines=[], intent=i,
        payments=[p], refunds=[], transfers=[t], reversals=[], disputes=[], recon_rows=[], bank_credit=None,
        rate_card=None, match_id=match_id,
    )


def test_orphaned_hold_aged_beyond_threshold_fires():
    # placed 2026-07-01, as_of 2026-07-20 -> 19 days >= 14
    unit = _unit(placed_at="2026-07-01T00:00:00Z", amount=50_000)
    finding = _CHECK.run(unit, _CTX)

    assert finding is not None
    assert finding.defect_id == "D06"
    assert finding.amount_at_risk_paise == 50_000


def test_orphaned_hold_not_yet_aged_does_not_fire():
    # placed 2026-07-12, as_of 2026-07-20 -> 8 days < 14
    unit = _unit(placed_at="2026-07-12T00:00:00Z")
    assert _CHECK.applies_to(unit) is True
    assert _CHECK.run(unit, _CTX) is None


def test_legitimate_hold_with_a_release_date_does_not_apply():
    unit = _unit(placed_at="2026-07-01T00:00:00Z", on_hold_until="2026-07-25T00:00:00Z")
    assert _CHECK.applies_to(unit) is False


def test_requires_missing_settlement_only():
    assert _CHECK.requires == frozenset({Completeness.MISSING_SETTLEMENT})
