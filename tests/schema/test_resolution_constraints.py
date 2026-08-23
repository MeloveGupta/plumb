"""BACKEND_SCHEMA.md §8, item 6 — escalation without what_would_resolve_it raises."""

import sqlite3

import pytest

from _seed import seed_exception


def test_escalation_without_what_would_resolve_it_raises(db):
    seed_exception(db, "exc_00001", "ord_00001")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO resolution (exception_id, outcome, model_claimed_outcome, was_downgraded,
                                        confidence, iterations_used, stop_reason, what_was_tried,
                                        what_would_resolve_it)
               VALUES (?, 'ESCALATED_UNRESOLVED', 'ESCALATED_UNRESOLVED', 0, 0.4, 8,
                        'iteration_cap', 'checked ledger', NULL)""",
            ("exc_00001",),
        )


def test_escalation_with_what_would_resolve_it_succeeds(db):
    seed_exception(db, "exc_00001", "ord_00001")
    db.execute(
        """INSERT INTO resolution (exception_id, outcome, model_claimed_outcome, was_downgraded,
                                    confidence, iterations_used, stop_reason, what_was_tried,
                                    what_would_resolve_it)
           VALUES (?, 'ESCALATED_UNRESOLVED', 'ESCALATED_UNRESOLVED', 0, 0.4, 8,
                    'iteration_cap', 'checked ledger', 'a bank statement confirming the UTR')""",
        ("exc_00001",),
    )
