"""BACKEND_SCHEMA.md §3.2 -- provenance chain writers, hand-checked
against a real run.sqlite (via plumb.store.ddl.open_run_db), not a
schema-less mock connection.
"""

import json

import pytest

from plumb.domain.keys import IdSequence
from plumb.store.ddl import open_run_db
from plumb.store.writer import write_quarantine, write_raw_record, write_source_file, write_transform_log


@pytest.fixture
def conn():
    c = open_run_db(":memory:")
    yield c
    c.close()


def test_write_source_file_returns_a_deterministic_id_and_persists(conn):
    ids = IdSequence()
    source_file_id = write_source_file(
        conn, ids, source_id="bank", path="dataset/bank.csv", sha256="abc123",
        byte_size=1000, row_count=42, file_format="csv",
    )
    assert source_file_id == "srcf_00001"
    row = conn.execute("SELECT source_id, path, row_count FROM source_file WHERE source_file_id = ?", (source_file_id,)).fetchone()
    assert row == ("bank", "dataset/bank.csv", 42)


def test_write_source_file_ids_increment_across_calls(conn):
    ids = IdSequence()
    first = write_source_file(conn, ids, source_id="intent", path="a", sha256="x", byte_size=1, row_count=1, file_format="csv")
    second = write_source_file(conn, ids, source_id="bank", path="b", sha256="y", byte_size=1, row_count=1, file_format="csv")
    assert first == "srcf_00001"
    assert second == "srcf_00002"


def test_write_raw_record_preserves_the_payload_verbatim(conn):
    ids = IdSequence()
    source_file_id = write_source_file(conn, ids, source_id="bank", path="p", sha256="x", byte_size=1, row_count=1, file_format="csv")
    payload = {"bank_ref": "RB1", "credit": "100.00", "narration": "UTR:ABC123456789012 SETTLEMENT"}
    write_raw_record(conn, "raw_bank_00001", source_file_id, 1, payload)

    row = conn.execute(
        "SELECT source_file_id, line_no, raw_payload_json FROM raw_record WHERE raw_id = ?", ("raw_bank_00001",)
    ).fetchone()
    assert row[0] == source_file_id
    assert row[1] == 1
    assert json.loads(row[2]) == payload


def test_write_raw_record_with_unknown_source_file_id_raises(conn):
    with pytest.raises(Exception):  # sqlite3.IntegrityError -- FK violation
        write_raw_record(conn, "raw_bank_00001", "srcf_99999", 1, {})


def test_write_transform_log_records_field_before_after_rule_id(conn):
    ids = IdSequence()
    source_file_id = write_source_file(conn, ids, source_id="bank", path="p", sha256="x", byte_size=1, row_count=1, file_format="csv")
    write_raw_record(conn, "raw_bank_00001", source_file_id, 1, {})

    write_transform_log(
        conn, ids, "raw_bank_00001",
        [("credit", "100.00", "10000", "rupee_to_paise"), ("value_date", "2026-08-20", "2026-08-19T18:30:00Z", "date_only_ist_midnight")],
    )
    rows = conn.execute(
        "SELECT field, before_text, after_text, rule_id FROM transform_log WHERE raw_id = ? ORDER BY transform_id",
        ("raw_bank_00001",),
    ).fetchall()
    assert rows == [
        ("credit", "100.00", "10000", "rupee_to_paise"),
        ("value_date", "2026-08-20", "2026-08-19T18:30:00Z", "date_only_ist_midnight"),
    ]


def test_write_transform_log_ids_continue_across_raw_records(conn):
    ids = IdSequence()
    source_file_id = write_source_file(conn, ids, source_id="bank", path="p", sha256="x", byte_size=1, row_count=2, file_format="csv")
    write_raw_record(conn, "raw_bank_00001", source_file_id, 1, {})
    write_raw_record(conn, "raw_bank_00002", source_file_id, 2, {})

    write_transform_log(conn, ids, "raw_bank_00001", [("f1", "a", "b", "rule")])
    write_transform_log(conn, ids, "raw_bank_00002", [("f2", "c", "d", "rule")])

    ids_seen = [r[0] for r in conn.execute("SELECT transform_id FROM transform_log ORDER BY transform_id").fetchall()]
    assert ids_seen == ["xfm_00001", "xfm_00002"]


def test_write_quarantine_counts_a_bad_row_without_dropping_it(conn):
    ids = IdSequence()
    source_file_id = write_source_file(conn, ids, source_id="bank", path="p", sha256="x", byte_size=1, row_count=1, file_format="csv")
    write_raw_record(conn, "raw_bank_00001", source_file_id, 1, {"credit": "not-a-number"})

    write_quarantine(conn, "raw_bank_00001", "unparseable_amount", "credit was 'not-a-number'")

    row = conn.execute("SELECT reason_code, detail FROM quarantine WHERE raw_id = ?", ("raw_bank_00001",)).fetchone()
    assert row == ("unparseable_amount", "credit was 'not-a-number'")
    # the raw row itself is still there -- quarantine never deletes it
    assert conn.execute("SELECT COUNT(*) FROM raw_record WHERE raw_id = ?", ("raw_bank_00001",)).fetchone()[0] == 1
