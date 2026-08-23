"""BACKEND_SCHEMA.md §8, item 1.

Hardcoded exemption set, not pattern-matched, so a new REAL column can't
quietly join it — the table/column list itself comes from the live schema
(PRAGMA table_info), only the three exemptions are hand-typed.
"""

EXEMPT = {
    ("run", "llm_temperature"),
    ("match_group", "confidence"),
    ("resolution", "confidence"),
}


def _real_columns(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    found = []
    for table in tables:
        for row in db.execute(f'PRAGMA table_info("{table}")').fetchall():
            column, col_type = row[1], row[2]
            if col_type.upper() == "REAL":
                found.append((table, column))
    return found


def test_no_real_columns_outside_the_hardcoded_exemption_set(db):
    violations = [f"{t}.{c}" for t, c in _real_columns(db) if (t, c) not in EXEMPT]
    assert not violations, violations


def test_exemption_set_is_exactly_the_three_real_columns_that_exist(db):
    # Guards the other direction too: if a REAL column gets removed, the
    # exemption set should shrink with it, not sit there covering nothing.
    assert set(_real_columns(db)) == EXEMPT
