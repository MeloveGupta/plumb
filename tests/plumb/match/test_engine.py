"""LLD §4.1 -- MatchEngine.run() end to end: every match carries a full
evidence chain, no record is ever claimed twice, and the result is
reproducible. The last two tests run against real plumb_gen output
(same method HANDOFF.md's own working notes recommend: run it and check,
don't just read the code) rather than another hand-built fixture.
"""

from plumb.domain.keys import IdSequence
from plumb.domain.tolerance import DEFAULT_V1
from plumb.ingest.pipeline import run_ingest
from plumb.match.engine import MatchConfig, MatchEngine, RecordSet
from plumb.store.ddl import open_run_db
from plumb_gen.config import GeneratorConfig
from plumb_gen.io import write_sources
from plumb_gen.world import build_world

from _match_fixtures import _bank_credit, _intent, _order, _payment, _record_set, _recon, _transfer


def _real_record_set(tmp_path, batch_size=200, seed=42):
    world = build_world(GeneratorConfig(seed=seed, batch_id="batch_test", batch_size=batch_size))
    out_dir = tmp_path / "dataset"
    write_sources(world, out_dir)
    conn = open_run_db(":memory:")
    ids = IdSequence()
    result = run_ingest(
        out_dir / "sellers.csv", out_dir / "intent.csv", out_dir / "razorpay.json", out_dir / "bank.csv", conn, ids
    )
    conn.close()
    return RecordSet.from_ingest(result)


def _small_mixed_record_set():
    """One clean full match, one composite-resolved match, one ambiguous
    tie, one intent-only order -- exercises every branch in one call."""
    return _record_set(
        # clean, resolves entirely at P0
        _order(1), _intent(1, 1), _payment(1, 1), _transfer(1, 1),
        _recon(1, 1, "stlbatch_clean", "UTR000000000001", credit_paise=98_000),
        _bank_credit(1, 98_000, credited_on="2026-07-05", utr="UTR000000000001"),
        # utr fails to parse; resolved by P1's exact composite
        _order(2), _intent(2, 2), _payment(2, 2), _transfer(2, 2),
        _recon(2, 2, "stlbatch_p1", "UTR000000000002", credit_paise=50_000, settled_at="2026-07-05T00:00:00Z"),
        _bank_credit(2, 50_000, credited_on="2026-07-05", utr=None),
        # two settlements tie for one bank credit -- ambiguous
        _order(3), _intent(3, 3), _payment(3, 3), _transfer(3, 3),
        _recon(3, 3, "stlbatch_amb_a", "UTR000000000003", credit_paise=70_000, settled_at="2026-07-06T00:00:00Z"),
        _order(4), _intent(4, 4), _payment(4, 4), _transfer(4, 4),
        _recon(4, 4, "stlbatch_amb_b", "UTR000000000004", credit_paise=70_000, settled_at="2026-07-06T00:00:00Z"),
        _bank_credit(3, 70_000, credited_on="2026-07-06", utr=None),
        # never got paid at all
        _order(5), _intent(5, 5),
    )


def test_every_group_carries_a_full_evidence_chain():
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    result = engine.run(_small_mixed_record_set())

    for group in result.groups:
        assert group.rule_id
        assert group.pass_ in {"P0", "P1", "P2", "P3"}
        assert 0 < group.confidence_bps <= 10_000
        assert len(group.members) >= 1
        for record_key, side in group.members:
            assert side in {"intent", "razorpay", "bank"}


def test_no_record_is_claimed_by_more_than_one_group_or_double_counted():
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    records = _small_mixed_record_set()
    result = engine.run(records)

    claimed = [key for group in result.groups for key, _ in group.members]
    assert len(claimed) == len(set(claimed))
    assert set(claimed).isdisjoint(result.unmatched)

    # every input key is accounted for exactly once: claimed, or unmatched
    accounted = set(claimed) | set(result.unmatched)
    assert accounted == set(records.all_keys())


def test_the_mixed_fixture_resolves_as_hand_expected():
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    result = engine.run(_small_mixed_record_set())

    by_pass = {}
    for g in result.groups:
        by_pass.setdefault(g.pass_, 0)
        by_pass[g.pass_] += 1

    # clean chain (P0) + ambiguous settlement A's chain (P0) + ambiguous
    # settlement B's chain (P0) = 3 P0 groups; the P1-composite chain = 1.
    assert by_pass.get("P0") == 3
    assert by_pass.get("P1") == 1
    # each contending settlement gets its own AmbiguousMatch -- both name
    # bank_00003, so L3 sees that the two chains are contesting one coin,
    # not a single merged report that would obscure which chains tied.
    assert len(result.ambiguous) == 2
    assert {a.pass_ for a in result.ambiguous} == {"P1"}
    assert all("bank_00003" in cand for a in result.ambiguous for cand in a.candidates)
    # order 5 (intent+intent record, never paid) plus the contested bank credit
    assert set(result.unmatched) == {"ord_00005", "int_00005", "bank_00003"}


def test_engine_run_is_deterministic_across_repeated_calls():
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    records = _small_mixed_record_set()

    first = engine.run(records)
    second = engine.run(records)

    assert first == second


def test_real_generated_batch_claims_every_record_exactly_once_or_leaves_it_unmatched(tmp_path):
    records = _real_record_set(tmp_path, batch_size=200)
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    result = engine.run(records)

    claimed = [key for group in result.groups for key, _ in group.members]
    assert len(claimed) == len(set(claimed))
    assert set(claimed).isdisjoint(result.unmatched)
    assert set(claimed) | set(result.unmatched) == set(records.all_keys())


def test_real_generated_batch_is_deterministic_across_repeated_runs(tmp_path):
    records = _real_record_set(tmp_path, batch_size=200)
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())

    first = engine.run(records)
    second = engine.run(records)

    assert first == second
