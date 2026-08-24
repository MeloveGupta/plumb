"""BACKEND_SCHEMA.md §5 — eval.sqlite. Same schema-test standard as
run.sql/truth.sql, scoped to what this schema actually contains.
"""

import sqlite3

import pytest

from _eval_db import open_eval_db
from test_money_law import _real_columns

EXEMPT = {("metric", "value_num")}  # BACKEND_SCHEMA §5's own generic value column


@pytest.fixture
def eval_db():
    conn = open_eval_db(":memory:")
    yield conn
    conn.close()


def test_ddl_applies_clean(eval_db):
    tables = eval_db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert {r[0] for r in tables} == {
        "metric", "scored_match", "scored_defect", "scored_abstention", "determinism_observation",
    }


def test_no_real_columns_outside_metric_value_num(eval_db):
    assert set(_real_columns(eval_db)) == EXEMPT


def test_metric_sample_label_rejects_an_illegal_value(eval_db):
    with pytest.raises(sqlite3.IntegrityError):
        eval_db.execute(
            "INSERT INTO metric (name, value_num, value_text, unit, sample_label) "
            "VALUES ('x', 1.0, NULL, 'ratio', 'MOSTLY_HELD_OUT')"
        )


def test_scored_match_verdict_rejects_an_illegal_value(eval_db):
    with pytest.raises(sqlite3.IntegrityError):
        eval_db.execute(
            "INSERT INTO scored_match (match_id, verdict, silent) VALUES ('m1', 'MAYBE_POSITIVE', 0)"
        )


def test_determinism_observation_same_run_same_record_key_collides(eval_db):
    eval_db.execute(
        "INSERT INTO determinism_observation (run_index, record_key, resolution_hash) VALUES (1, 'ord_00001', 'abc')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        eval_db.execute(
            "INSERT INTO determinism_observation (run_index, record_key, resolution_hash) VALUES (1, 'ord_00001', 'def')"
        )
