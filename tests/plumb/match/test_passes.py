"""LLD §4.1/§4.2, TRD §5.2 -- one hand-built fixture per pass, values
worked out on paper before being asserted (CLAUDE.md's testing rule).
"""

from plumb.domain.tolerance import ToleranceProfile
from plumb.match.engine import MatchConfig
from plumb.match.passes import PassP0, PassP1, PassP2, PassP3

from _match_fixtures import _bank_credit, _intent, _order, _payment, _record_set, _recon, _transfer

TOLERANCE = ToleranceProfile(name="test", amount_abs_paise=100, amount_rel_bps=10, date_window_days=2)


# ---------------------------------------------------------------- P0


def test_p0_joins_the_full_chain_when_utr_resolves():
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111"),
        _bank_credit(1, 98_000, utr="UTR111111111111"),
    )
    groups, remaining, pending = PassP0().run(records, records.all_keys())

    assert remaining == []
    assert pending == []
    assert len(groups) == 1
    group = groups[0]
    assert group.pass_ == "P0" and group.rule_id == "ID_CHAIN" and group.confidence_bps == 10_000
    assert {k for k, _ in group.members} == {
        "ord_00001", "int_00001", "pay_00001", "txfr_00001", "setl_00001", "bank_00001",
    }


def test_p0_leaves_an_intent_only_order_unclaimed():
    # No payment at all -- never got paid. A single side (intent), so P0
    # must not manufacture a match for it.
    records = _record_set(_order(1), _intent(1, 1))
    groups, remaining, pending = PassP0().run(records, records.all_keys())

    assert groups == []
    assert pending == []
    assert sorted(remaining) == ["int_00001", "ord_00001"]


def test_p0_holds_a_missing_bank_leg_open_as_pending_rather_than_claiming_it():
    # utr fails to parse on the bank side -- the chain up to the
    # settlement_recon is still fully linked via order/payment/transfer
    # ids, but the bank credit itself has nothing to join on (no utr).
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=98_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 98_000, utr=None),
    )
    groups, remaining, pending = PassP0().run(records, records.all_keys())

    assert groups == []  # not claimed yet -- the bank leg might still attach
    assert sorted(remaining) == ["bank_00001"]  # the orphan, on its own
    assert len(pending) == 1
    pg = pending[0]
    assert set(pg.members) == {"ord_00001", "int_00001", "pay_00001", "txfr_00001", "setl_00001"}
    assert pg.target_paise == 98_000
    assert pg.settlement_id == "stlbatch_1"


def test_p0_pending_target_nets_out_debit_paise():
    # A dispute or refund netted against the settlement means the bank
    # only ever receives credit_paise - debit_paise (plumb_gen/world.py's
    # own net_paise computation) -- target_paise must match that, not
    # the gross credit_paise, or an unparseable-UTR bank credit for a
    # settlement with any netting can never be found again.
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=279_198, debit_paise=167_683),
        _bank_credit(1, 111_515, utr=None),
    )
    _, _, pending = PassP0().run(records, records.all_keys())

    assert len(pending) == 1
    assert pending[0].target_paise == 111_515  # 279_198 - 167_683, hand-computed


# ---------------------------------------------------------------- P1


def test_p1_attaches_an_orphaned_bank_credit_by_exact_amount_and_date():
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=98_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 98_000, credited_on="2026-07-05", utr=None),
    )
    _, remaining, pending = PassP0().run(records, records.all_keys())
    orphan_bank = [k for k in remaining if k == "bank_00001"]

    groups, still_pending, still_orphan, ambiguous, contested = PassP1().run(records, pending, orphan_bank)

    assert still_pending == []
    assert still_orphan == []
    assert ambiguous == []
    assert contested == set()
    assert len(groups) == 1
    group = groups[0]
    assert group.pass_ == "P1" and group.rule_id == "EXACT_COMPOSITE" and group.confidence_bps == 9_500
    assert "bank_00001" in {k for k, _ in group.members}


def test_p1_attaches_when_the_bank_credit_is_net_of_a_dispute_deduction():
    # Same shape as test_p0_pending_target_nets_out_debit_paise, carried
    # through to an actual P1 attachment: the bank credit's real-world
    # amount is net of debit_paise, and P1 must compare against that net
    # figure to find it, not the recon's gross credit_paise.
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=279_198, debit_paise=167_683,
               settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 111_515, credited_on="2026-07-05", utr=None),
    )
    _, remaining, pending = PassP0().run(records, records.all_keys())
    orphan_bank = [k for k in remaining if k == "bank_00001"]

    groups, still_pending, still_orphan, ambiguous, contested = PassP1().run(records, pending, orphan_bank)

    assert still_pending == []
    assert still_orphan == []
    assert ambiguous == []
    assert len(groups) == 1
    assert "bank_00001" in {k for k, _ in groups[0].members}


def test_p1_does_not_attach_when_amount_matches_but_date_does_not():
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=98_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 98_000, credited_on="2026-07-09", utr=None),  # 4 days later, outside exact match
    )
    _, remaining, pending = PassP0().run(records, records.all_keys())
    orphan_bank = [k for k in remaining if k == "bank_00001"]

    groups, still_pending, still_orphan, ambiguous, contested = PassP1().run(records, pending, orphan_bank)

    assert groups == []
    assert len(still_pending) == 1
    assert still_orphan == ["bank_00001"]
    assert ambiguous == []


def test_p1_is_ambiguous_when_two_settlements_of_identical_value_tie_for_one_bank_credit():
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=50_000, settled_at="2026-07-05T00:00:00Z"),
        _order(2), _intent(2, 2), _payment(2, 2), _transfer(2, 2),
        _recon(2, 2, "stlbatch_2", "UTR222222222222", credit_paise=50_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 50_000, credited_on="2026-07-05", utr=None),
    )
    _, remaining, pending = PassP0().run(records, records.all_keys())
    orphan_bank = [k for k in remaining if k == "bank_00001"]
    assert len(pending) == 2

    groups, still_pending, still_orphan, ambiguous, contested = PassP1().run(records, pending, orphan_bank)

    # both settlements' own identity chains are still certain and must
    # finalise as P0 groups despite the contested bank leg
    assert still_pending == []
    p0_groups = [g for g in groups if g.pass_ == "P0"]
    assert len(p0_groups) == 2
    assert len(ambiguous) == 2
    assert contested == {"bank_00001"}
    assert still_orphan == []  # removed from the pool, but...
    # ...it must still surface as unmatched at the engine level, not vanish -- see test_engine.py


# ---------------------------------------------------------------- P2


def test_p2_matches_two_settlements_summing_to_one_bank_credit():
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_shared", "UTR111111111111", credit_paise=30_000, settled_at="2026-07-05T00:00:00Z"),
        _order(2), _intent(2, 2), _payment(2, 2), _transfer(2, 2),
        _recon(2, 2, "stlbatch_shared", "UTR222222222222", credit_paise=70_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 100_000, credited_on="2026-07-05", utr=None),
    )
    _, remaining, pending = PassP0().run(records, records.all_keys())
    orphan_bank = [k for k in remaining if k == "bank_00001"]
    assert len(pending) == 2  # same settlement_id, so P2 -- not P1 -- must find this

    groups, still_pending, still_orphan, ambiguous, contested = PassP2(MatchConfig()).run(
        records, pending, orphan_bank
    )

    assert still_pending == []
    assert still_orphan == []
    assert ambiguous == []
    assert len(groups) == 1
    group = groups[0]
    assert group.pass_ == "P2" and group.rule_id == "GROUP_SUBSET_SUM" and group.confidence_bps == 9_000
    member_keys = {k for k, _ in group.members}
    assert member_keys == {
        "ord_00001", "int_00001", "pay_00001", "txfr_00001", "setl_00001",
        "ord_00002", "int_00002", "pay_00002", "txfr_00002", "setl_00002",
        "bank_00001",
    }


def test_p2_is_ambiguous_when_two_bank_credit_subsets_both_sum_to_the_target():
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=100_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 40_000, credited_on="2026-07-05", utr=None),
        _bank_credit(2, 60_000, credited_on="2026-07-05", utr=None),
        _bank_credit(3, 25_000, credited_on="2026-07-05", utr=None),
        _bank_credit(4, 75_000, credited_on="2026-07-05", utr=None),
    )
    _, remaining, pending = PassP0().run(records, records.all_keys())
    orphan_bank = sorted(k for k in remaining if k.startswith("bank_"))

    groups, still_pending, still_orphan, ambiguous, contested = PassP2(MatchConfig()).run(
        records, pending, orphan_bank
    )

    assert still_pending == []
    assert len(ambiguous) == 1
    p0_groups = [g for g in groups if g.pass_ == "P0"]
    assert len(p0_groups) == 1  # the settlement's own chain still finalises
    assert contested == {"bank_00001", "bank_00002", "bank_00003", "bank_00004"}


# ---------------------------------------------------------------- P3


def test_p3_attaches_within_the_tolerance_band_and_date_window():
    # band = max(100, 10bps of 98_000=98) = 100 paise; a 90-paise
    # shortfall is inside the band. 1 day inside a 2-day window.
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=98_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 97_910, credited_on="2026-07-06", utr=None),
    )
    _, remaining, pending = PassP0().run(records, records.all_keys())
    orphan_bank = [k for k in remaining if k == "bank_00001"]

    groups, still_pending, still_orphan, ambiguous, contested = PassP3(TOLERANCE).run(
        records, pending, orphan_bank
    )

    assert still_pending == []
    assert len(groups) == 1
    group = groups[0]
    assert group.pass_ == "P3" and group.rule_id == "TOL_BAND" and group.confidence_bps == 7_000


def test_p3_leaves_it_unmatched_when_outside_the_band():
    # shortfall of 500 paise is outside the 100-paise band.
    records = _record_set(
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_1", "UTR111111111111", credit_paise=98_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(1, 97_500, credited_on="2026-07-05", utr=None),
    )
    _, remaining, pending = PassP0().run(records, records.all_keys())
    orphan_bank = [k for k in remaining if k == "bank_00001"]

    groups, still_pending, still_orphan, ambiguous, contested = PassP3(TOLERANCE).run(
        records, pending, orphan_bank
    )

    assert groups == []
    assert len(still_pending) == 1
    assert still_orphan == ["bank_00001"]
