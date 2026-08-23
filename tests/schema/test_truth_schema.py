"""BACKEND_SCHEMA.md §4 — truth.sqlite. Same schema-test standard as run.sql,
scoped to what this schema actually contains.
"""

import sqlite3

import pytest

from _truth_db import open_truth_db
from test_json_columns import find_json_columns_missing_check
from test_money_law import _real_columns


@pytest.fixture
def truth_db():
    conn = open_truth_db(":memory:")
    yield conn
    conn.close()


def test_ddl_applies_clean(truth_db):
    tables = truth_db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert {r[0] for r in tables} == {"truth_record", "injected_defect"}


def test_no_real_columns_at_all(truth_db):
    assert _real_columns(truth_db) == []


def test_every_json_column_has_a_json_valid_check():
    from _truth_db import SCHEMA_SQL

    assert find_json_columns_missing_check(SCHEMA_SQL) == []


def test_injected_defect_with_unknown_record_key_raises(truth_db):
    with pytest.raises(sqlite3.IntegrityError):
        truth_db.execute(
            """INSERT INTO injected_defect
               (instance_id, record_key, defect_class, amount_at_risk_paise, within_tolerance, params_json)
               VALUES ('inst_00001', 'ord_99999', 'D02', 3000, 1, '{}')"""
        )


def test_injected_defect_with_known_record_key_succeeds(truth_db):
    truth_db.execute(
        """INSERT INTO truth_record
           (record_key, true_counterparts_json, true_obligation_json, resolvable_from_available_data)
           VALUES ('ord_00001', '[]', '{}', 1)"""
    )
    truth_db.execute(
        """INSERT INTO injected_defect
           (instance_id, record_key, defect_class, amount_at_risk_paise, within_tolerance, params_json)
           VALUES ('inst_00001', 'ord_00001', 'D02', 3000, 1, '{}')"""
    )
