"""BACKEND_SCHEMA.md §3 — the only sanctioned way to open a run.sqlite connection.

PRAGMA foreign_keys is per-connection and is not persisted in the database
file. Setting it once at creation time does nothing for the next connection
that reopens the same file. Nothing under src/plumb should call
sqlite3.connect() directly on a run.sqlite path — always go through
open_run_db (fresh) or open_existing_run_db (reopen) so the pragma can't be
forgotten on some later connection.
"""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schema" / "run.sql"
SCHEMA_SQL = SCHEMA_PATH.read_text()


def open_run_db(path: str | Path) -> sqlite3.Connection:
    """Create a fresh run.sqlite: apply the DDL, foreign keys on."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def open_existing_run_db(path: str | Path) -> sqlite3.Connection:
    """Reopen an already-built run.sqlite — report layer, tests, inspection."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
