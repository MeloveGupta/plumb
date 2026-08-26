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
    bank_by_id = {bc.bank_credit_id: bc for bc in world.bank_credits}
    # both settlement_recon_ids and bank_credit_ids share the same
    # numeric suffix by construction (setl_00005 <-> bank_00005)
    for rid in paired_recon_ids:
        suffix = rid.split("_")[1]
        bc = bank_by_id[f"bank_{suffix}"]
        assert bc.utr is None
        assert _extracts_no_utr_pattern(bc.narration)
        assert bc.amount_paise == by_recon[rid].credit_paise - by_recon[rid].debit_paise


def test_adversarial_pair_count_too_large_for_the_batch_raises():
    with pytest.raises(ValueError, match="adversarial_pair_count"):
        _world(seed=42, batch_size=5, adversarial_pair_count=10)


@pytest.mark.parametrize("seed", SEEDS)
def test_tier_messiness_is_deterministic_for_a_given_seed(seed):
    a = _world(seed=seed, unparseable_narration_rate_bps=2000, settlement_batch_rate_bps=3000,
               settlement_split_rate_bps=2000, adversarial_pair_count=2)
    b = _world(seed=seed, unparseable_narration_rate_bps=2000, settlement_batch_rate_bps=3000,
               settlement_split_rate_bps=2000, adversarial_pair_count=2)
    assert [bc.bank_credit_id for bc in a.bank_credits] == [bc.bank_credit_id for bc in b.bank_credits]
    assert [bc.amount_paise for bc in a.bank_credits] == [bc.amount_paise for bc in b.bank_credits]
    assert [r.credit_paise for r in a.settlement_recons] == [r.credit_paise for r in b.settlement_recons]


def test_zero_rate_fields_leave_bank_credits_one_to_one_with_settlements():
    # Default config (all new fields at 0) must produce the same 1:1
    # shape build_world always has -- confirmed by the pass count, not
    # by re-deriving values already covered by test_world.py.
    world = _world(seed=42)
    assert len(world.bank_credits) == len(world.settlement_recons)
