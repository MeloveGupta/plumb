"""P1.10, GATE P1 -- L1 determinism_score = 1.000 across 5 independent
runs, tested the hard way (tests/plumb_gen/test_determinism.py's own
style): five full independent pipeline runs, hashed and compared -- not
two in-memory MatchResult objects compared with == in the same process
(that's already covered, cheaply, by test_engine.py; this is the formal
harness GATE P1 actually asks for).

Each of the 5 runs regenerates the dataset from scratch (same seed),
re-ingests, and re-matches with its own fresh IdSequence, hashing the
resulting MatchResult's own content (rule_id/pass/confidence/members
per group, plus unmatched and ambiguous) rather than persisted DB rows:
persist() requires record_index to already be populated, and nothing in
src/plumb/ writes record_index yet -- only the provenance chain
(source_file/raw_record/transform_log/quarantine) is wired up so far
(tests/schema/_seed.py hand-seeds record_index for exactly this reason,
and test_match_writer.py does the same). That gap belongs to whichever
task actually writes the canonical entity tables (verify's
SettlementUnit builder, P2.1, is the first thing that will need real
rows there) -- not to the matcher's own determinism harness, so this
test hashes the matcher's output directly instead of routing through
persistence it doesn't otherwise need.
"""

import hashlib
import tempfile
from pathlib import Path

from plumb.domain.keys import IdSequence
from plumb.domain.tolerance import DEFAULT_V1
from plumb.ingest.pipeline import run_ingest
from plumb.match.engine import MatchConfig, MatchEngine, RecordSet
from plumb.store.ddl import open_run_db
from plumb_gen.config import GeneratorConfig
from plumb_gen.io import write_sources
from plumb_gen.world import build_world

_BATCH_SIZE = 200


def _run_pipeline_and_hash(seed: int) -> str:
    with tempfile.TemporaryDirectory() as td:
        world = build_world(GeneratorConfig(seed=seed, batch_id="batch_determinism", batch_size=_BATCH_SIZE))
        out_dir = Path(td) / "dataset"
        write_sources(world, out_dir)

        conn = open_run_db(":memory:")
        ids = IdSequence()
        ingest_result = run_ingest(
            out_dir / "sellers.csv", out_dir / "intent.csv", out_dir / "razorpay.json", out_dir / "bank.csv",
            conn, ids,
        )
        conn.close()
        records = RecordSet.from_ingest(ingest_result)
        engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
        result = engine.run(records)

        canonical = repr(
            (
                tuple((g.rule_id, g.pass_, g.confidence_bps, g.members) for g in result.groups),
                result.unmatched,
                tuple((a.pass_, a.reason, a.candidates) for a in result.ambiguous),
            )
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def test_l1_determinism_score_is_1_000_across_five_runs():
    hashes = [_run_pipeline_and_hash(seed=42) for _ in range(5)]
    determinism_score = sum(1 for h in hashes if h == hashes[0]) / len(hashes)

    assert determinism_score == 1.000
    assert len(set(hashes)) == 1


def test_a_different_seed_produces_different_output():
    # Proves the test above isn't vacuously passing because the hash
    # ignores the actual match content.
    hash_a = _run_pipeline_and_hash(seed=42)
    hash_b = _run_pipeline_and_hash(seed=43)
    assert hash_a != hash_b
