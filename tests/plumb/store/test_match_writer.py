"""BACKEND_SCHEMA.md §3.4 -- match_group/match_member writers, hand-checked
against a real run.sqlite. The claim-once guard here is demonstrated the
same way tests/schema/test_match_member_unique.py already demonstrates
it at the raw-SQL level (CLAUDE.md's standing rule: a guard isn't done
until shown failing on a real violation) -- exercised here from the
matcher's own persist() path instead.
"""

import sqlite3

import pytest

from plumb.domain.keys import IdSequence
from plumb.match.engine import AmbiguousMatch, MatchGroup, MatchResult, persist
from plumb.store.ddl import open_run_db
from plumb.store.writer import write_match_group, write_match_member

_SEED_SQL = """
INSERT INTO record_index (record_key, entity_type, source_id) VALUES
    ('ord_00001', 'order', 'intent'),
    ('pay_00001', 'payment', 'razorpay'),
    ('bank_00001', 'bank_credit', 'bank');
"""


@pytest.fixture
def conn():
    c = open_run_db(":memory:")
    c.executescript(_SEED_SQL)
    yield c
    c.close()


def test_write_match_group_returns_a_deterministic_id_and_persists(conn):
    ids = IdSequence()
    match_id = write_match_group(conn, ids, rule_id="ID_CHAIN", pass_="P0", confidence_bps=10_000)
    assert match_id == "mtch_00001"
    row = conn.execute(
        "SELECT rule_id, pass, confidence FROM match_group WHERE match_id = ?", (match_id,)
    ).fetchone()
    assert row == ("ID_CHAIN", "P0", 1.0)


def test_write_match_member_persists_side(conn):
    ids = IdSequence()
    match_id = write_match_group(conn, ids, rule_id="ID_CHAIN", pass_="P0", confidence_bps=10_000)
    write_match_member(conn, match_id, "ord_00001", "intent")
    row = conn.execute(
        "SELECT match_id, side FROM match_member WHERE record_key = ?", ("ord_00001",)
    ).fetchone()
    assert row == (match_id, "intent")


def test_write_match_member_rejects_a_record_claimed_by_a_second_match_id(conn):
    """Demonstrated, not asserted: this is the same violation
    tests/schema/test_match_member_unique.py shows against raw SQL,
    reproduced here against the matcher's own write path so a bug in
    persist() (double-claiming a record_key) would fail loudly rather
    than silently double-counting a match rate.
    """
    ids = IdSequence()
    first_match = write_match_group(conn, ids, rule_id="ID_CHAIN", pass_="P0", confidence_bps=10_000)
    second_match = write_match_group(conn, ids, rule_id="EXACT_COMPOSITE", pass_="P1", confidence_bps=9_500)
    write_match_member(conn, first_match, "ord_00001", "intent")

    with pytest.raises(sqlite3.IntegrityError):
        write_match_member(conn, second_match, "ord_00001", "bank")


def test_persist_round_trips_a_match_result(conn):
    result = MatchResult(
        groups=(
            MatchGroup(
                rule_id="ID_CHAIN", pass_="P0", confidence_bps=10_000,
                members=(("ord_00001", "intent"), ("pay_00001", "razorpay")),
            ),
        ),
        unmatched=("bank_00001",),
        ambiguous=(),
    )
    ids = IdSequence()

    match_ids = persist(conn, ids, result)

    assert match_ids == {0: "mtch_00001"}
    members = conn.execute(
        "SELECT record_key, side FROM match_member WHERE match_id = ? ORDER BY record_key", ("mtch_00001",)
    ).fetchall()
    assert members == [("ord_00001", "intent"), ("pay_00001", "razorpay")]
    # unmatched/ambiguous never get a DB row -- persist() only writes what was actually claimed
    assert conn.execute("SELECT COUNT(*) FROM match_group").fetchone()[0] == 1


def test_persist_would_surface_a_double_claim_as_an_integrity_error(conn):
    """If MatchEngine ever produced two groups both claiming the same
    record_key (the exact bug ix_member_claimed_once exists to catch),
    persist() must not swallow it -- the second write fails loudly.
    """
    result = MatchResult(
        groups=(
            MatchGroup(rule_id="ID_CHAIN", pass_="P0", confidence_bps=10_000, members=(("ord_00001", "intent"),)),
            MatchGroup(rule_id="EXACT_COMPOSITE", pass_="P1", confidence_bps=9_500, members=(("ord_00001", "intent"),)),
        ),
        unmatched=(),
        ambiguous=(AmbiguousMatch(pass_="P1", reason="unused here", candidates=()),),
    )
    ids = IdSequence()

    with pytest.raises(sqlite3.IntegrityError):
        persist(conn, ids, result)
