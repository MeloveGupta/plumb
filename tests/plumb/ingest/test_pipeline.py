"""End to end: run_adapter against real plumb-gen output -> source_file/
raw_record/transform_log/quarantine rows land in run.sqlite correctly.
"""

from plumb.domain.keys import IdSequence
from plumb.ingest.adapters.bank import BankAdapter
from plumb.ingest.adapters.intent import IntentAdapter
from plumb.ingest.adapters.razorpay import RazorpayAdapter
from plumb.ingest.pipeline import run_adapter
from plumb.store.ddl import open_run_db
from plumb_gen.config import GeneratorConfig
from plumb_gen.io import write_sources
from plumb_gen.world import build_world


def _real_dataset(tmp_path, batch_size=50):
    world = build_world(GeneratorConfig(seed=42, batch_id="batch_test", batch_size=batch_size))
    out_dir = tmp_path / "dataset"
    write_sources(world, out_dir)
    return out_dir


def test_run_adapter_writes_the_full_provenance_chain_for_bank(tmp_path):
    dataset_dir = _real_dataset(tmp_path)
    conn = open_run_db(":memory:")
    ids = IdSequence()

    summary = run_adapter(BankAdapter(), dataset_dir / "bank.csv", conn, ids)

    assert summary["total"] > 0
    assert summary["normalised"] + summary["quarantined"] == summary["total"]
    assert summary["quarantined"] == 0  # real generator output is always well-formed

    source_file_count = conn.execute("SELECT COUNT(*) FROM source_file").fetchone()[0]
    assert source_file_count == 1
    raw_record_count = conn.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0]
    assert raw_record_count == summary["total"]
    # every bank row gets 3 transforms (credit, value_date, narration)
    transform_count = conn.execute("SELECT COUNT(*) FROM transform_log").fetchone()[0]
    assert transform_count == summary["total"] * 3
    quarantine_count = conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]
    assert quarantine_count == 0
    conn.close()


def test_run_adapter_all_three_sources_populate_the_chain(tmp_path):
    dataset_dir = _real_dataset(tmp_path)
    conn = open_run_db(":memory:")
    ids = IdSequence()

    intent_summary = run_adapter(IntentAdapter(), dataset_dir / "intent.csv", conn, ids)
    razorpay_summary = run_adapter(RazorpayAdapter(), dataset_dir / "razorpay.json", conn, ids)
    bank_summary = run_adapter(BankAdapter(), dataset_dir / "bank.csv", conn, ids)

    assert conn.execute("SELECT COUNT(*) FROM source_file").fetchone()[0] == 3
    total_raw = intent_summary["total"] + razorpay_summary["total"] + bank_summary["total"]
    assert conn.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0] == total_raw

    # source_file_ids and raw_ids are unique across all three sources --
    # one shared IdSequence, no cross-source collisions.
    source_file_ids = [r[0] for r in conn.execute("SELECT source_file_id FROM source_file").fetchall()]
    assert len(source_file_ids) == len(set(source_file_ids))
    raw_ids = [r[0] for r in conn.execute("SELECT raw_id FROM raw_record").fetchall()]
    assert len(raw_ids) == len(set(raw_ids))
    conn.close()


def test_run_adapter_quarantine_evidence_is_inspectable(tmp_path):
    dataset_dir = _real_dataset(tmp_path)
    conn = open_run_db(":memory:")
    ids = IdSequence()
    run_adapter(BankAdapter(), dataset_dir / "bank.csv", conn, ids)

    # A bare_token or ambiguous_narration UTR extraction shows up as
    # inspectable transform_log evidence, not silently absorbed.
    row = conn.execute(
        "SELECT before_text, after_text, rule_id FROM transform_log WHERE field = 'narration' LIMIT 1"
    ).fetchone()
    assert row is not None
    before_text, after_text, rule_id = row
    assert rule_id in {"utr_labelled", "neft_ref", "rtgs_ref", "imps_ref", "bare_token", "no_match"}
    conn.close()
