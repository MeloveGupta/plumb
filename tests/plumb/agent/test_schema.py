"""P3 step 2 -- the Resolution schema and its code-enforced invariants
(TRD §7.3). Every failure case is demonstrated by constructing a
genuinely invalid Resolution and catching the error, not by reading the
validator.
"""

import pytest
from pydantic import ValidationError

from plumb.agent.schema import EvidenceRef, Hypothesis, Resolution, StopReason


def _valid(**overrides) -> dict:
    """A minimal well-formed PROPOSED resolution; override one field per
    test to exercise one invariant."""
    base = dict(
        exception_id="exc_00001",
        outcome="PROPOSED",
        confidence_bps=8_000,
        hypotheses=[
            Hypothesis(rank=1, statement="rate card drifted", supports=["int_00001"]),
            Hypothesis(rank=2, statement="rounding", supports=[]),
        ],
        chosen_hypothesis_index=0,
        evidence_chain=[EvidenceRef(record_key="int_00001", role="intent")],
        amount_at_risk_paise=5_000,
        what_was_tried="fetched the rate card and the intent ledger",
        stop_reason=StopReason.SUFFICIENT_EVIDENCE,
        iterations_used=3,
    )
    base.update(overrides)
    return base


def test_a_well_formed_resolution_constructs():
    res = Resolution(**_valid())
    assert res.outcome == "PROPOSED"
    assert res.was_downgraded is False


def test_model_claimed_outcome_defaults_to_outcome():
    res = Resolution(**_valid(outcome="AUTO_RESOLVED"))
    assert res.model_claimed_outcome == "AUTO_RESOLVED"


def test_escalated_without_what_would_resolve_it_is_rejected():
    with pytest.raises(ValidationError, match="what_would_resolve_it"):
        Resolution(**_valid(outcome="ESCALATED_UNRESOLVED", what_would_resolve_it=None))


def test_escalated_with_what_would_resolve_it_is_accepted():
    res = Resolution(
        **_valid(
            outcome="ESCALATED_UNRESOLVED",
            what_would_resolve_it="a human decision on which bank credit belongs",
        )
    )
    assert res.outcome == "ESCALATED_UNRESOLVED"


def test_empty_evidence_chain_is_rejected():
    with pytest.raises(ValidationError):
        Resolution(**_valid(evidence_chain=[]))


def test_single_hypothesis_is_rejected_unless_trivial():
    one = [Hypothesis(rank=1, statement="only one", supports=[])]
    with pytest.raises(ValidationError, match="two ranked hypotheses"):
        Resolution(**_valid(hypotheses=one, chosen_hypothesis_index=0))


def test_single_hypothesis_is_allowed_when_trivially_determined():
    one = [Hypothesis(rank=1, statement="obvious", supports=[])]
    res = Resolution(**_valid(hypotheses=one, chosen_hypothesis_index=0, trivially_determined=True))
    assert res.trivially_determined is True


def test_confidence_bps_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        Resolution(**_valid(confidence_bps=10_001))
    with pytest.raises(ValidationError):
        Resolution(**_valid(confidence_bps=-1))
    assert Resolution(**_valid(confidence_bps=0)).confidence_bps == 0
    assert Resolution(**_valid(confidence_bps=10_000)).confidence_bps == 10_000


def test_chosen_hypothesis_index_out_of_range_is_rejected():
    with pytest.raises(ValidationError, match="out of range"):
        Resolution(**_valid(chosen_hypothesis_index=5))


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        Resolution(**_valid(severity="high"))


def test_downgrade_forces_proposed_and_preserves_the_claim():
    auto = Resolution(**_valid(outcome="AUTO_RESOLVED", confidence_bps=9_500))
    down = auto.downgrade("amount_above_threshold")

    assert down.outcome == "PROPOSED"
    assert down.was_downgraded is True
    assert down.downgrade_reason == "amount_above_threshold"
    assert down.model_claimed_outcome == "AUTO_RESOLVED"  # never overwritten

    assert auto.outcome == "AUTO_RESOLVED"  # original untouched (frozen -> new instance)
    assert auto.was_downgraded is False


def test_stop_reason_values_match_the_db_check_strings():
    assert StopReason.SUFFICIENT_EVIDENCE == "sufficient_evidence"
    assert StopReason.ITERATION_CAP == "iteration_cap"
    assert StopReason.BUDGET_EXHAUSTED == "budget_exhausted"
    assert StopReason.TOOL_FAILURE == "tool_failure"
    assert StopReason.RULES_ONLY == "rules_only"
