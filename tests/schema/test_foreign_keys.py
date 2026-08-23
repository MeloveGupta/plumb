"""BACKEND_SCHEMA.md §8, item 7, plus question 1's "actually on, not assumed" check."""

import os
import sqlite3
import tempfile

from _seed import seed_exception
import pytest

from plumb.store.ddl import open_existing_run_db, open_run_db


def test_foreign_keys_pragma_reads_back_on(db):
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_foreign_keys_still_enforced_on_a_reopened_connection():
    # The scenario question 1 is actually about: schema/run.sql's own
    # PRAGMA line only runs once, when open_run_db executes the DDL script.
    # A later connection that just reopens the file — report layer, a
    # test, a panelist — never re-runs that script, so this only proves
    # anything if open_existing_run_db sets the pragma itself.
    path = tempfile.mktemp(suffix=".sqlite")
    try:
        conn = open_run_db(path)
        seed_exception(conn, "exc_00001", "ord_00001")
        conn.commit()
        conn.close()

        reopened = open_existing_run_db(path)
        assert reopened.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            reopened.execute(
                "INSERT INTO resolution_evidence (exception_id, record_key, role) "
                "VALUES ('exc_00001', 'ord_99999', 'primary')"
            )
        reopened.close()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_resolution_evidence_with_unknown_record_key_raises(db):
    seed_exception(db, "exc_00001", "ord_00001")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO resolution_evidence (exception_id, record_key, role) VALUES (?, 'ord_99999', 'primary')",
            ("exc_00001",),
        )


def test_resolution_evidence_with_known_record_key_succeeds(db):
    seed_exception(db, "exc_00001", "ord_00001")
    db.execute(
        "INSERT INTO resolution_evidence (exception_id, record_key, role) VALUES (?, 'ord_00001', 'primary')",
        ("exc_00001",),
    )
