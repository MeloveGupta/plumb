"""Test-only DDL application for eval.sqlite.

Deliberately not under src/plumb/ or src/plumb_eval/ -- mirrors
tests/schema/_truth_db.py's own reasoning: schema-level tests apply
schema/eval.sql directly, without depending on plumb_eval's writer.
"""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "eval.sql"
SCHEMA_SQL = SCHEMA_PATH.read_text()


def open_eval_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn
