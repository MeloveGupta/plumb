"""BACKEND_SCHEMA.md §3.2 -- provenance chain writers: source_file,
raw_record, transform_log, quarantine. Persists what ingest/ computed
(RawRecord, Transform, NormalResult) -- ingest itself stays pure per
LLD §3.1's own framing ("keeps normalise a pure function"); writing is
this module's job, not normalise()'s.

Takes plain scalars/tuples rather than importing plumb.ingest.normalise's
dataclasses: `store <- all layers` means store must sit beneath every
layer, never depend on one -- importing ingest's types here would be a
real circular import (ingest imports store to write, store would import
ingest for types), not just an untidy one. Callers (ingest/pipeline.py)
unpack RawRecord/Transform into plain arguments at the call site.
"""

import json
import sqlite3

from plumb.domain.keys import IdSequence


def write_source_file(
    conn: sqlite3.Connection,
    ids: IdSequence,
    *,
    source_id: str,
    path: str,
    sha256: str,
    byte_size: int,
    row_count: int,
    file_format: str,
) -> str:
    source_file_id = ids.next("srcf")
    conn.execute(
        "INSERT INTO source_file (source_file_id, source_id, path, sha256, byte_size, row_count, format) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source_file_id, source_id, path, sha256, byte_size, row_count, file_format),
    )
    return source_file_id


def write_raw_record(
    conn: sqlite3.Connection, raw_id: str, source_file_id: str, line_no: int, raw_payload: dict
) -> None:
    conn.execute(
        "INSERT INTO raw_record (raw_id, source_file_id, line_no, raw_payload_json) VALUES (?, ?, ?, ?)",
        (raw_id, source_file_id, line_no, json.dumps(raw_payload)),
    )


def write_transform_log(
    conn: sqlite3.Connection,
    ids: IdSequence,
    raw_id: str,
    transforms: list[tuple[str, str | None, str | None, str]],
) -> None:
    """transforms: (field, before_text, after_text, rule_id) tuples, in order."""
    for field, before_text, after_text, rule_id in transforms:
        transform_id = ids.next("xfm")
        conn.execute(
            "INSERT INTO transform_log (transform_id, raw_id, field, before_text, after_text, rule_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (transform_id, raw_id, field, before_text, after_text, rule_id),
        )


def write_quarantine(conn: sqlite3.Connection, raw_id: str, reason_code: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO quarantine (raw_id, reason_code, detail) VALUES (?, ?, ?)",
        (raw_id, reason_code, detail),
    )


def write_match_group(conn: sqlite3.Connection, ids: IdSequence, *, rule_id: str, pass_: str, confidence_bps: int) -> str:
    """confidence_bps arrives as an int (TRD §2.5 -- no float anywhere in
    the engine's own path); match_group.confidence is REAL in the schema
    and CHECK(confidence > 0 AND confidence <= 1), so the /10000 division
    happens here, right at the DB boundary, as a bare expression rather
    than a named float value the rest of the engine could pick up.
    """
    match_id = ids.next("mtch")
    conn.execute(
        "INSERT INTO match_group (match_id, rule_id, pass, confidence) VALUES (?, ?, ?, ?)",
        (match_id, rule_id, pass_, confidence_bps / 10_000),
    )
    return match_id


def write_match_member(conn: sqlite3.Connection, match_id: str, record_key: str, side: str) -> None:
    """ix_member_claimed_once (BACKEND_SCHEMA.md §3.4) enforces "claimed
    exactly once" at the DB level: a record_key already written under a
    different match_id raises sqlite3.IntegrityError here rather than
    silently double-counting. Callers do not need to check this
    themselves -- the constraint is the check."""
    conn.execute(
        "INSERT INTO match_member (match_id, record_key, side) VALUES (?, ?, ?)",
        (match_id, record_key, side),
    )
