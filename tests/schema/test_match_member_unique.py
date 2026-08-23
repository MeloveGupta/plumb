"""BACKEND_SCHEMA.md §8, item 5 — ix_member_claimed_once exists and is UNIQUE."""

import sqlite3

import pytest

from _seed import seed_match_group, seed_record_index


def test_ix_member_claimed_once_rejects_double_claim(db):
    seed_match_group(db, "mtch_00001")
    seed_match_group(db, "mtch_00002")
    seed_record_index(db, "ord_00001")
    db.execute(
        "INSERT INTO match_member (match_id, record_key, side) VALUES ('mtch_00001', 'ord_00001', 'intent')"
    )
    # Different match_id, different side — only record_key repeats. The
    # index is on record_key alone, not (match_id, record_key), which the
    # table's own composite PRIMARY KEY already covers separately.
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO match_member (match_id, record_key, side) VALUES ('mtch_00002', 'ord_00001', 'bank')"
        )
