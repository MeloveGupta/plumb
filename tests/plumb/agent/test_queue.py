"""P3 step 9 -- the exception queue: one entry per residual / ambiguous
set / finding, ranked by rupees descending (APP_FLOW §2).

Amounts are chosen in the fixture; the expected ordering is worked out
by hand in the test, not read from build_exception_queue's output.
"""

from _agent_fixtures import bank_credit, ingest_result, payment

from plumb.agent.queue import Exception_, _contested_key, build_exception_queue
from plumb.domain.keys import IdSequence
from plumb.match.engine import AmbiguousMatch, MatchResult, RecordSet
from plumb.verify.trace import Finding, RecomputeTrace, Severity


def _finding(defect_id, amount, on_matched=True):
    return Finding(
        defect_id=defect_id, unit_id="unit_00001", severity=Severity.HIGH,
        amount_at_risk_paise=amount, on_matched_record=on_matched, conclusion=f"{defect_id} fired",
        trace=RecomputeTrace(steps=(), conclusion="x"), evidence=(),
    )


def _records():
    batch = ingest_result(
        razorpay_records=[payment(2, 2, amount=100_000)],
        bank_records=[bank_credit(1, 500_000), bank_credit(3, 300_000)],
    )
    return RecordSet.from_ingest(batch)


def test_contested_key_is_the_one_the_candidates_disagree_about():
    match = AmbiguousMatch(
        pass_="P1",
        reason="settlement stlbatch_x: 2 bank credit candidates",
        candidates=(("int_00001", "pay_00001", "bank_00003"), ("int_00001", "pay_00001", "bank_00004")),
    )
    assert _contested_key(match) == "bank_00003"


def test_queue_is_ranked_by_rupees_descending():
    match_result = MatchResult(
        groups=(),
        unmatched=("bank_00001", "pay_00002"),
        ambiguous=(
            AmbiguousMatch(
                pass_="P1", reason="2 candidates",
                candidates=(("pay_00001", "bank_00003"), ("pay_00001", "bank_00009")),
            ),
        ),
    )
    findings = [("fnd_00001", _finding("D01", 250_000)), ("fnd_00002", _finding("D02", 700_000))]

    queue = build_exception_queue(match_result, _records(), findings, IdSequence())

    # hand-ranked: 700k fnd_00002, 500k bank_00001, 300k ambiguous(bank_00003),
    #              250k fnd_00001, 100k pay_00002
    assert [(e.queue_rank, e.exception_id, e.amount_at_risk_paise) for e in queue] == [
        (1, "exc_00001", 700_000),
        (2, "exc_00002", 500_000),
        (3, "exc_00003", 300_000),
        (4, "exc_00004", 250_000),
        (5, "exc_00005", 100_000),
    ]
    assert queue[0].origin == "FINDING" and queue[0].finding_id == "fnd_00002"
    assert queue[1].origin == "UNMATCHED" and queue[1].record_key == "bank_00001"
    assert queue[2].record_key == "bank_00003"


def test_ambiguous_entry_carries_its_candidates():
    match = AmbiguousMatch(
        pass_="P2", reason="subset ambiguity",
        candidates=(("pay_00001", "bank_00003"), ("pay_00001", "bank_00003", "bank_00009")),
    )
    queue = build_exception_queue(
        MatchResult(groups=(), unmatched=(), ambiguous=(match,)), _records(), [], IdSequence()
    )
    assert queue[0].candidates == (("pay_00001", "bank_00003"), ("pay_00001", "bank_00003", "bank_00009"))


def test_tie_break_is_stable_on_the_key_string():
    match_result = MatchResult(groups=(), unmatched=("bank_00003", "bank_00001"), ambiguous=())
    # bank_00001 and bank_00003 have amounts 500k and 300k -> not a tie; use findings for a real tie
    findings = [("fnd_00002", _finding("D02", 300_000)), ("fnd_00001", _finding("D01", 300_000))]
    queue = build_exception_queue(match_result, _records(), findings, IdSequence())
    ranks = [(e.queue_rank, e.record_key or e.finding_id, e.amount_at_risk_paise) for e in queue]
    # 500k bank_00001, then the two 300k findings tie -> fnd_00001 before fnd_00002, then 300k bank_00003
    assert ranks == [
        (1, "bank_00001", 500_000),
        (2, "bank_00003", 300_000),
        (3, "fnd_00001", 300_000),
        (4, "fnd_00002", 300_000),
    ]


def test_frozen_exception_dataclass():
    e = Exception_("exc_00001", "UNMATCHED", "bank_00001", None, 1, 1, "residual")
    try:
        e.queue_rank = 2
    except AttributeError:
        return
    raise AssertionError("Exception_ should be frozen")
