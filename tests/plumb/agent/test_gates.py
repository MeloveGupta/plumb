"""P3 step 8 -- the downgrade gate (LLD §7.3) and the fabrication gate.

Thresholds are AgentConfig's defaults (auto_resolve_threshold_paise
10_000, confidence_threshold_bps 9_000); each boundary case states its
arithmetic. The fabrication case is demonstrated by feeding a genuinely
invented record key through the gate, not by reading the check.
"""

import pytest

from plumb.agent.config import AgentConfig
from plumb.agent.evidence import RecordIndex
from plumb.agent.gates import apply_downgrade_gate, assert_evidence_resolves
from plumb.agent.schema import EvidenceRef, Hypothesis, Resolution, StopReason
from plumb.errors import FabricationError

_CFG = AgentConfig()


def _resolution(**overrides) -> Resolution:
    base = dict(
        exception_id="exc_00001",
        outcome="AUTO_RESOLVED",
        confidence_bps=9_500,
        hypotheses=[Hypothesis(rank=1, statement="a", supports=[]), Hypothesis(rank=2, statement="b", supports=[])],
        chosen_hypothesis_index=0,
        evidence_chain=[EvidenceRef(record_key="pay_00001", role="payment")],
        amount_at_risk_paise=5_000,
        what_was_tried="checked",
        stop_reason=StopReason.SUFFICIENT_EVIDENCE,
        iterations_used=2,
    )
    base.update(overrides)
    return Resolution(**base)


# --- downgrade gate ---


def test_auto_resolved_within_both_bounds_is_granted():
    # amount 5_000 < 10_000; confidence 9_500 >= 9_000 -> untouched
    res = apply_downgrade_gate(_resolution(), _CFG)
    assert res.outcome == "AUTO_RESOLVED"
    assert res.was_downgraded is False


def test_amount_at_or_above_threshold_is_downgraded():
    # 10_000 >= 10_000 -> downgrade
    res = apply_downgrade_gate(_resolution(amount_at_risk_paise=10_000, confidence_bps=10_000), _CFG)
    assert res.outcome == "PROPOSED"
    assert res.was_downgraded is True
    assert res.downgrade_reason == "amount_above_threshold"
    assert res.model_claimed_outcome == "AUTO_RESOLVED"


def test_confidence_below_threshold_is_downgraded():
    # 8_999 < 9_000 -> downgrade
    res = apply_downgrade_gate(_resolution(amount_at_risk_paise=1_000, confidence_bps=8_999), _CFG)
    assert res.outcome == "PROPOSED"
    assert res.downgrade_reason == "confidence_below_threshold"


def test_confidence_exactly_at_threshold_is_granted():
    # 9_000 >= 9_000 -> not downgraded
    res = apply_downgrade_gate(_resolution(amount_at_risk_paise=1_000, confidence_bps=9_000), _CFG)
    assert res.outcome == "AUTO_RESOLVED"


def test_amount_is_checked_before_confidence():
    res = apply_downgrade_gate(_resolution(amount_at_risk_paise=50_000, confidence_bps=100), _CFG)
    assert res.downgrade_reason == "amount_above_threshold"


def test_non_auto_resolved_outcomes_pass_through_untouched():
    proposed = _resolution(outcome="PROPOSED")
    assert apply_downgrade_gate(proposed, _CFG) is proposed

    escalated = _resolution(
        outcome="ESCALATED_UNRESOLVED", what_would_resolve_it="a human decision", confidence_bps=0
    )
    assert apply_downgrade_gate(escalated, _CFG) is escalated


# --- fabrication gate ---


def test_a_fabricated_evidence_reference_fails_the_run():
    index = RecordIndex(frozenset({"pay_00001", "int_00001"}))
    res = _resolution(
        evidence_chain=[EvidenceRef(record_key="pay_00001", role="payment"),
                        EvidenceRef(record_key="pay_99999", role="payment")],
    )
    with pytest.raises(FabricationError, match="pay_99999") as caught:
        assert_evidence_resolves(res, index)
    assert caught.value.record_key == "pay_99999"
    assert caught.value.exception_id == "exc_00001"


def test_an_all_real_evidence_chain_passes():
    index = RecordIndex(frozenset({"pay_00001", "int_00001"}))
    res = _resolution(
        evidence_chain=[EvidenceRef(record_key="pay_00001", role="payment"),
                        EvidenceRef(record_key="int_00001", role="intent")],
    )
    assert_evidence_resolves(res, index)  # must not raise
