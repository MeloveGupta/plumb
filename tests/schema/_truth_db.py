"""Test-only DDL application for truth.sqlite.

Deliberately not under src/plumb/ — the engine never opens truth.sqlite
(TRD §3.1, the ground-truth AST test in tests/test_import_boundary.py).
Only plumb_gen writes it and plumb_eval reads it, and neither exists yet.
When they do, their own connection-opening code lives there, not here.
"""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "truth.sql"
SCHEMA_SQL = SCHEMA_PATH.read_text()


def open_truth_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn
