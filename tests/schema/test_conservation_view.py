"""BACKEND_SCHEMA.md §8, item 8 — v_conservation returns equal counts after a successful run."""

from _seed import seed_record_index


def test_conservation_matches_when_every_record_has_a_terminal_state(db):
    seed_record_index(db, "ord_00001")
    seed_record_index(db, "ord_00002")
    db.execute("INSERT INTO record_terminal_state (record_key, terminal_state) VALUES ('ord_00001', 'VERIFIED_CLEAN')")
    db.execute("INSERT INTO record_terminal_state (record_key, terminal_state) VALUES ('ord_00002', 'QUARANTINED')")
    records_in, accounted_for = db.execute("SELECT records_in, accounted_for FROM v_conservation").fetchone()
    assert records_in == accounted_for == 2


def test_conservation_diverges_when_a_record_has_no_terminal_state(db):
    seed_record_index(db, "ord_00001")
    seed_record_index(db, "ord_00002")
    db.execute("INSERT INTO record_terminal_state (record_key, terminal_state) VALUES ('ord_00001', 'VERIFIED_CLEAN')")
    records_in, accounted_for = db.execute("SELECT records_in, accounted_for FROM v_conservation").fetchone()
    assert records_in == 2
    assert accounted_for == 1
