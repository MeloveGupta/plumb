"""BACKEND_SCHEMA.md §8, item 4 — all six append-only tables, not just finding.

Each case updates/deletes a column that itself has no CHECK constraint (or
updates to another valid enum value), so a raised IntegrityError can only be
the trigger firing, not an incidental separate constraint failure.
"""

import sqlite3

import pytest

from _seed import (
    seed_agent_call,
    seed_finding,
    seed_match_group,
    seed_match_member,
    seed_record_terminal_state,
    seed_resolution,
)

CASES = [
    ("finding", "conclusion", "updated conclusion", lambda c: seed_finding(c, "fnd_00001", "unit_00001", "ord_00001")),
    ("resolution", "what_was_tried", "re-checked ledger", lambda c: seed_resolution(c, "exc_00001", "ord_00001")),
    ("agent_call", "tool", "different_tool", lambda c: seed_agent_call(c, "call_00001", "exc_00001", "ord_00001")),
    ("match_group", "rule_id", "EXACT_COMPOSITE", lambda c: seed_match_group(c, "mtch_00001")),
    ("match_member", "side", "bank", lambda c: seed_match_member(c, "mtch_00001", "ord_00001")),
    ("record_terminal_state", "terminal_state", "QUARANTINED", lambda c: seed_record_terminal_state(c, "ord_00001")),
]
IDS = [c[0] for c in CASES]


@pytest.mark.parametrize("table, column, new_value, seed", CASES, ids=IDS)
def test_update_rejected(db, table, column, new_value, seed):
    seed(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f"UPDATE {table} SET {column} = ?", (new_value,))


@pytest.mark.parametrize("table, column, new_value, seed", CASES, ids=IDS)
def test_delete_rejected(db, table, column, new_value, seed):
    seed(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f"DELETE FROM {table}")
