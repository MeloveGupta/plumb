"""PRD §8.2 T2/T3 -- world.py's post-loop messiness passes: many:1
batching, 1:many splitting, and the adversarial-pair ambiguity trap.
"""

import re

import pytest

from plumb_gen.config import GeneratorConfig
from plumb_gen.world import build_world

SEEDS = [1, 2, 3, 7, 42]


def _world(seed=42, **overrides):
    config = GeneratorConfig(seed=seed, batch_id="batch_test", **overrides)
    return build_world(config)


def _extracts_no_utr_pattern(text: str) -> bool:
    # Mirrors the shape of LLD §3.2's five extraction patterns closely
    # enough for a test guard: no run of 12+ contiguous alnum chars,
    # which is what narration.py's own _unparseable() guarantees.
    return re.search(r"[A-Z0-9]{12,}", text) is None


@pytest.mark.parametrize("seed", SEEDS)
def test_settlement_batching_reduces_bank_credit_count_and_conserves_money(seed):
    world = _world(seed=seed, unparseable_narration_rate_bps=2000, settlement_batch_rate_bps=5000)
    assert len(world.bank_credits) < len(world.settlement_recons)
    assert sum(bc.amount_paise for bc in world.bank_credits) == sum(
        r.credit_paise - r.debit_paise for r in world.settlement_recons
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_settlement_splitting_increases_bank_credit_count_and_conserves_money(seed):
    world = _world(seed=seed, unparseable_narration_rate_bps=2000, settlement_split_rate_bps=5000)
    assert len(world.bank_credits) > len(world.settlement_recons)
    assert sum(bc.amount_paise for bc in world.bank_credits) == sum(
        r.credit_paise - r.debit_paise for r in world.settlement_recons
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_batched_and_split_bank_credits_are_unparseable(seed):
    # Every manufactured bank credit must genuinely fail narration
    # extraction, not just carry utr=None -- ingest re-derives utr from
    # the narration text independently, so the text has to actually be
    # unparseable or the override is silently discarded at ingest time.
    world = _world(seed=seed, unparseable_narration_rate_bps=0, settlement_batch_rate_bps=5000,
                   settlement_split_rate_bps=5000)
    manufactured = [bc for bc in world.bank_credits if bc.utr is None]
    assert manufactured  # the test would be vacuous if nothing was manufactured
    for bc in manufactured:
        assert bc.utr is None
        assert _extracts_no_utr_pattern(bc.narration)


@pytest.mark.parametrize("seed", SEEDS)
def test_adversarial_pairs_share_exact_amount_and_date(seed):
    world = _world(seed=seed, adversarial_pair_count=3)
    from collections import defaultdict

    # Grouped by *net* target (credit_paise - debit_paise), not the raw
    # tuple: the leader keeps its own original debit_paise (possibly
    # nonzero), only the follower is forced to 0 -- their net targets
    # match exactly, which is what the matcher actually compares, even
    # though the raw (credit_paise, debit_paise) pairs can legitimately
    # differ.
    groups = defaultdict(list)
    for r in world.settlement_recons:
        groups[(r.credit_paise - r.debit_paise, r.settled_at_utc)].append(r.settlement_recon_id)
    paired = [ids for ids in groups.values() if len(ids) >= 2]
    assert len(paired) == 3  # exactly the requested count, hand-verified against the config

    paired_recon_ids = {rid for group in paired for rid in group}
    by_recon = {r.settlement_recon_id: r for r in world.settlement_recons}
    # Correlated via truth's true_counterparts, not an assumed shared
    # numeric suffix -- bank_credit_id is ingest-derived from CSV row
    # position, not a value carried in the row, so nothing guarantees
    # it lines up with settlement_recon_id's own suffix once anything
    # reorders world.bank_credits (batch_rate_bps/split_rate_bps do; a
    # future combination with adversarial_pair_count would otherwise
    # silently break this test the same way it broke the real
    # re-measurement before that bug was found and fixed).
    bank_id_by_recon_id = {}
    for record in world.truth_records:
        recon_id = next((c for c in record.true_counterparts if c.startswith("setl_")), None)
        bank_id = next((c for c in record.true_counterparts if c.startswith("bank_")), None)
        if recon_id and bank_id:
            bank_id_by_recon_id[recon_id] = bank_id
    bank_by_id = {bc.bank_credit_id: bc for bc in world.bank_credits}
    for rid in paired_recon_ids:
        bc = bank_by_id[bank_id_by_recon_id[rid]]
        assert bc.utr is None
        assert _extracts_no_utr_pattern(bc.narration)
        assert bc.amount_paise == by_recon[rid].credit_paise - by_recon[rid].debit_paise


def test_adversarial_pair_count_too_large_for_the_batch_raises():
    with pytest.raises(ValueError, match="adversarial_pair_count"):
        _world(seed=42, batch_size=5, adversarial_pair_count=10)


def _recon_and_bank_for(world, record):
    # Correlated via truth's own true_counterparts, never by assumed id
    # suffix: bank_credit_id is ingest-derived from CSV row position
    # (plumb/ingest/adapters/bank.py), not from any value carried in
    # the row, so it is *not* guaranteed to share a numeric suffix with
    # its settlement_recon_id once anything has reordered
    # world.bank_credits (batching/splitting/in-flight all do). This
    # bit the re-measurement script for real before it was fixed here.
    recon_id = next(c for c in record.true_counterparts if c.startswith("setl_"))
    bank_id = next(c for c in record.true_counterparts if c.startswith("bank_"))
    recon = next(r for r in world.settlement_recons if r.settlement_recon_id == recon_id)
    bank_credit = next(bc for bc in world.bank_credits if bc.bank_credit_id == bank_id)
    return recon, bank_credit


@pytest.mark.parametrize("seed", SEEDS)
def test_in_flight_settlements_are_genuinely_partial_and_unparseable(seed):
    world = _world(seed=seed, unparseable_narration_rate_bps=0, settlement_in_flight_rate_bps=5000)
    settled_records = [r for r in world.truth_records if any(c.startswith("bank_") for c in r.true_counterparts)]
    in_flight_records = []
    for record in settled_records:
        recon, bank_credit = _recon_and_bank_for(world, record)
        if bank_credit.utr is None:
            in_flight_records.append((recon, bank_credit))
    assert in_flight_records  # vacuous otherwise

    for recon, bank_credit in in_flight_records:
        net_target = recon.credit_paise - recon.debit_paise
        assert _extracts_no_utr_pattern(bank_credit.narration)
        # genuinely partial -- 30-70% of the true net target, never the
        # full amount (that would just be an ordinary unparseable-
        # narration case, not this feature)
        assert 0 < bank_credit.amount_paise < net_target


@pytest.mark.parametrize("seed", SEEDS)
def test_in_flight_settlements_are_marked_unresolvable_in_truth(seed):
    world = _world(seed=seed, unparseable_narration_rate_bps=0, settlement_in_flight_rate_bps=5000)
    settled_records = [r for r in world.truth_records if any(c.startswith("bank_") for c in r.true_counterparts)]

    expected_unresolvable_keys = set()
    for record in settled_records:
        recon, bank_credit = _recon_and_bank_for(world, record)
        if bank_credit.utr is None and bank_credit.amount_paise < recon.credit_paise - recon.debit_paise:
            expected_unresolvable_keys.add(record.record_key)
    assert expected_unresolvable_keys  # vacuous otherwise

    actual_unresolvable_keys = {r.record_key for r in world.truth_records if not r.resolvable_from_available_data}
    assert actual_unresolvable_keys == expected_unresolvable_keys


def test_in_flight_settlement_money_is_not_conserved_by_design():
    # Unlike batching/splitting, in-flight settlements deliberately break
    # record-for-record conservation -- part of the true net target is
    # genuinely absent from this batch, not just present under a
    # different bank_credit_id.
    world = _world(seed=42, unparseable_narration_rate_bps=0, settlement_in_flight_rate_bps=5000)
    total_net_target = sum(r.credit_paise - r.debit_paise for r in world.settlement_recons)
    total_bank = sum(bc.amount_paise for bc in world.bank_credits)
    assert total_bank < total_net_target


@pytest.mark.parametrize("seed", SEEDS)
def test_tier_messiness_is_deterministic_for_a_given_seed(seed):
    a = _world(seed=seed, unparseable_narration_rate_bps=2000, settlement_batch_rate_bps=3000,
               settlement_split_rate_bps=2000, settlement_in_flight_rate_bps=1500, adversarial_pair_count=2)
    b = _world(seed=seed, unparseable_narration_rate_bps=2000, settlement_batch_rate_bps=3000,
               settlement_split_rate_bps=2000, settlement_in_flight_rate_bps=1500, adversarial_pair_count=2)
    assert [bc.bank_credit_id for bc in a.bank_credits] == [bc.bank_credit_id for bc in b.bank_credits]
    assert [bc.amount_paise for bc in a.bank_credits] == [bc.amount_paise for bc in b.bank_credits]
    assert [r.credit_paise for r in a.settlement_recons] == [r.credit_paise for r in b.settlement_recons]


def test_zero_rate_fields_leave_bank_credits_one_to_one_with_settlements():
    # Default config (all new fields at 0) must produce the same 1:1
    # shape build_world always has -- confirmed by the pass count, not
    # by re-deriving values already covered by test_world.py.
    world = _world(seed=42)
    assert len(world.bank_credits) == len(world.settlement_recons)
