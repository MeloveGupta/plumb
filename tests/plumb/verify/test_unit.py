"""LLD §5.1 -- SettlementUnit builder. One hand-built fixture per
Completeness value; each traces to a concrete generator/matcher
mechanism (see verify/unit.py's own docstrings), not a guess.
"""

from plumb.domain.keys import IdSequence
from plumb.verify.unit import Completeness, build_units

from _verify_fixtures import (
    bank_credit,
    ingest_result,
    intent,
    match_group,
    match_result,
    order,
    payment,
    rate_card,
    recon,
    transfer,
)


def test_full_chain_with_an_attached_bank_credit_is_full():
    o, i, p, t, r, b = order(1), intent(1, 1), payment(1, 1), transfer(1, 1), recon(1, 1), bank_credit(1, 98_000, utr="UTR000001")
    result = ingest_result(intent_records=[o, i], razorpay_records=[p, t, r], bank_records=[b])
    mr = match_result(
        groups=[
            match_group(
                "P0",
                [
                    ("ord_00001", "intent"), ("int_00001", "intent"), ("pay_00001", "razorpay"),
                    ("txfr_00001", "razorpay"), ("setl_00001", "razorpay"), ("bank_00001", "bank"),
                ],
            )
        ]
    )
    units = build_units(result, mr, {0: "mtch_00001"}, IdSequence())

    assert len(units) == 1
    unit = units[0]
    assert unit.unit_id == "unit_00001"
    assert unit.completeness == Completeness.FULL
    assert unit.bank_credit == b
    assert unit.recon_rows == [r]
    assert unit.match_id == "mtch_00001"


def test_pending_chain_with_an_unattached_bank_credit_is_missing_bank():
    """The T2 in-flight trap: a real bank_credit exists in bank.csv (never
    absent) but the matcher's own passes never attach it -- it surfaces
    in MatchResult.unmatched instead of the order's group. This is the
    scenario the acceptance criteria flagged explicitly."""
    o, i, p, t, r = order(1), intent(1, 1), payment(1, 1), transfer(1, 1), recon(1, 1)
    b = bank_credit(1, 41_500, utr=None, narration="unparseable narration")  # partial, in-flight, orphaned
    result = ingest_result(intent_records=[o, i], razorpay_records=[p, t, r], bank_records=[b])
    mr = match_result(
        groups=[
            match_group(
                "P0",
                [
                    ("ord_00001", "intent"), ("int_00001", "intent"), ("pay_00001", "razorpay"),
                    ("txfr_00001", "razorpay"), ("setl_00001", "razorpay"),
                ],
            )
        ],
        unmatched=["bank_00001"],
    )
    units = build_units(result, mr, {0: "mtch_00001"}, IdSequence())

    assert len(units) == 1
    unit = units[0]
    assert unit.completeness == Completeness.MISSING_BANK
    assert unit.bank_credit is None
    assert unit.recon_rows == [r]
    assert unit.match_id == "mtch_00001"


def test_settled_at_never_reached_with_no_recon_at_all_is_missing_settlement():
    """world.py creates settlement_recon and bank_credit together, gated
    on the same `settled_at is not None` condition -- an on-hold or
    still-in-window transfer has neither, not just a missing bank leg."""
    o, i, p, t = order(1), intent(1, 1), payment(1, 1), transfer(1, 1, on_hold=True, on_hold_until=None, settled_at=None)
    result = ingest_result(intent_records=[o, i], razorpay_records=[p, t])
    mr = match_result(
        groups=[
            match_group(
                "P0",
                [("ord_00001", "intent"), ("int_00001", "intent"), ("pay_00001", "razorpay"), ("txfr_00001", "razorpay")],
            )
        ]
    )
    units = build_units(result, mr, {0: "mtch_00001"}, IdSequence())

    assert len(units) == 1
    unit = units[0]
    assert unit.completeness == Completeness.MISSING_SETTLEMENT
    assert unit.bank_credit is None
    assert unit.recon_rows == []


def test_order_with_no_payment_at_all_is_intent_only():
    o, i = order(1), intent(1, 1)
    result = ingest_result(intent_records=[o, i])
    mr = match_result(unmatched=["ord_00001", "int_00001"])
    units = build_units(result, mr, {}, IdSequence())

    assert len(units) == 1
    unit = units[0]
    assert unit.completeness == Completeness.INTENT_ONLY
    assert unit.payments == []
    assert unit.match_id is None


def test_rate_card_as_of_lookup_picks_the_card_effective_on_the_order_date():
    o, i = order(1, placed_at="2026-07-15T00:00:00Z"), intent(1, 1)
    old_card = rate_card(1, effective_from="2024-01-01", effective_to="2026-06-30", commission_bps=1200)
    new_card = rate_card(2, effective_from="2026-07-01", effective_to=None, commission_bps=1500)
    result = ingest_result(intent_records=[o, i], sellers_records=[old_card, new_card])
    mr = match_result(unmatched=["ord_00001", "int_00001"])
    units = build_units(result, mr, {}, IdSequence())

    assert units[0].rate_card == new_card
