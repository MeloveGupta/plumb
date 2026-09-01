"""P3 step 7 -- the investigation loop, driven entirely by ScriptedClient
(no API key, no network). LLD §7.2's four exits: submit, iteration cap,
budget, and degrade-on-failure.
"""

from _agent_fixtures import bank_credit, ingest_result, intent, order, payment, recon, seller, transfer

from plumb.agent.config import AgentConfig
from plumb.agent.evidence import EvidenceStore
from plumb.agent.loop import investigate
from plumb.agent.model import ModelResponse, ScriptedClient, ToolCall, Usage
from plumb.agent.prompts import load_prompts
from plumb.agent.queue import Exception_
from plumb.agent.schema import StopReason
from plumb.agent.tools import Toolbox
from plumb.domain.keys import IdSequence
from plumb.verify.trace import EvidenceRef as VerifyEvidenceRef
from plumb.verify.trace import Finding, Severity, TraceBuilder

_PROMPTS = load_prompts()


def _toolbox() -> Toolbox:
    batch = ingest_result(
        intent_records=[order(1), intent(1, 1)],
        razorpay_records=[payment(1, 1), transfer(1, 1), recon(1, 1, settled_at="2026-07-05T00:00:00Z")],
        bank_records=[bank_credit(1, 500_000)],
        sellers_records=[seller("sel_00001")],
    )
    return Toolbox(EvidenceStore.from_ingest(batch), IdSequence())


def _exc(**kw) -> Exception_:
    base = dict(
        exception_id="exc_00001", origin="UNMATCHED", record_key="bank_00001", finding_id=None,
        amount_at_risk_paise=500_000, queue_rank=1, reason="residual: unmatched record",
    )
    base.update(kw)
    return Exception_(**base)


def _tool_turn(name, args, usage=(10, 10)):
    return ModelResponse(stop_reason="tool_use", tool_calls=[ToolCall("t", name, args)], usage=Usage(*usage))


def _submit_turn(usage=(10, 10), **overrides):
    args = dict(
        outcome="PROPOSED", confidence_bps=8_000,
        hypotheses=[{"rank": 1, "statement": "a", "supports": []}, {"rank": 2, "statement": "b", "supports": []}],
        chosen_hypothesis_index=0,
        evidence_chain=[{"record_key": "pay_00001", "role": "payment"}],
        what_was_tried="fetched the payment", what_would_resolve_it=None, trivially_determined=False,
    )
    args.update(overrides)
    return ModelResponse(stop_reason="tool_use", tool_calls=[ToolCall("s", "submit_resolution", args)], usage=Usage(*usage))


def test_happy_path_reaches_a_submitted_resolution():
    client = ScriptedClient([
        _tool_turn("fetch_payment", {"payment_id": "pay_00001"}),
        _submit_turn(),
    ])
    resolution, state = investigate(_exc(), _toolbox(), client, AgentConfig(), _PROMPTS)

    assert resolution.outcome == "PROPOSED"
    assert resolution.stop_reason == StopReason.SUFFICIENT_EVIDENCE
    assert resolution.iterations_used == 2
    assert resolution.amount_at_risk_paise == 500_000  # from the exception, not the model
    # agent_calls: turn1 model_turn, fetch_payment, turn2 submit_resolution
    tools_logged = [c.tool for c in state.agent_calls]
    assert tools_logged == ["model_turn", "fetch_payment", "submit_resolution"]
    assert any(e.record_key == "pay_00001" for e in state.evidence)


def test_iteration_cap_forces_a_valid_escalation():
    client = ScriptedClient([_tool_turn("fetch_settlement_recon", {"date": "2026-07-05"}) for _ in range(8)])
    resolution, state = investigate(_exc(), _toolbox(), client, AgentConfig(), _PROMPTS)

    assert resolution.outcome == "ESCALATED_UNRESOLVED"
    assert resolution.stop_reason == StopReason.ITERATION_CAP
    assert resolution.what_would_resolve_it  # non-null -- the DB CHECK would demand it
    assert resolution.iterations_used == 8
    assert len(client.calls) == 8  # the 9th was never made -- checked before the call


def test_budget_reserve_stops_before_the_next_call():
    # one turn spends 57_000; remaining 3_000 < reserve 4_000 -> stop before turn 2
    client = ScriptedClient([
        _tool_turn("fetch_settlement_recon", {"date": "2026-07-05"}, usage=(57_000, 0)),
        _submit_turn(),  # must never be reached
    ])
    resolution, state = investigate(_exc(), _toolbox(), client, AgentConfig(), _PROMPTS)

    assert resolution.outcome == "ESCALATED_UNRESOLVED"
    assert resolution.stop_reason == StopReason.BUDGET_EXHAUSTED
    assert len(client.calls) == 1
    assert state.tokens_in + state.tokens_out == 57_000  # recorded spend stayed under the 60_000 budget


def test_a_single_huge_turn_also_stops_and_makes_no_further_call():
    client = ScriptedClient([
        _tool_turn("fetch_settlement_recon", {"date": "2026-07-05"}, usage=(200_000, 0)),
        _submit_turn(),
    ])
    resolution, _ = investigate(_exc(), _toolbox(), client, AgentConfig(), _PROMPTS)
    assert resolution.stop_reason == StopReason.BUDGET_EXHAUSTED


def test_a_tool_failure_degrades_and_the_loop_continues():
    client = ScriptedClient([
        _tool_turn("fetch_payment", {"payment_id": "pay_99999"}),  # no such payment
        _submit_turn(),
    ])
    resolution, state = investigate(_exc(), _toolbox(), client, AgentConfig(), _PROMPTS)

    assert resolution.outcome == "PROPOSED"  # the run did not abort on the bad call
    bad = [c for c in state.agent_calls if c.tool == "fetch_payment"][0]
    assert bad.result_row_count == 0


def test_an_invalid_submit_is_fed_back_and_the_model_can_correct_it():
    client = ScriptedClient([
        # one hypothesis, not trivial -> Resolution invariant violation
        _submit_turn(hypotheses=[{"rank": 1, "statement": "only one", "supports": []}]),
        _submit_turn(),  # corrected
    ])
    resolution, state = investigate(_exc(), _toolbox(), client, AgentConfig(), _PROMPTS)

    assert resolution.outcome == "PROPOSED"
    assert resolution.iterations_used == 2
    assert any(
        isinstance(m.get("content"), list)
        and any(b.get("is_error") for b in m["content"] if isinstance(b, dict))
        for m in state.messages
    )


def test_no_tool_call_gets_nudged():
    client = ScriptedClient([
        ModelResponse(stop_reason="end_turn", text="I'm thinking about it."),
        _submit_turn(),
    ])
    resolution, state = investigate(_exc(), _toolbox(), client, AgentConfig(), _PROMPTS)
    assert resolution.outcome == "PROPOSED"
    assert resolution.iterations_used == 2


def test_escalation_on_a_finding_exception_grounds_on_the_findings_evidence():
    trace = TraceBuilder().step("delta", "expected - actual", {"expected": 100, "actual": 40}, 60).conclude("short")
    finding = Finding(
        defect_id="D01", unit_id="unit_00001", severity=Severity.HIGH, amount_at_risk_paise=250_000,
        on_matched_record=True, conclusion="commission drift", trace=trace,
        evidence=(VerifyEvidenceRef(record_key="int_00001", role="intent"),),
    )
    exc = _exc(exception_id="exc_00002", origin="FINDING", record_key=None, finding_id="fnd_00001",
               amount_at_risk_paise=250_000, finding=finding)
    # every tool call fails -> no gathered evidence -> fall back to the finding's own refs
    client = ScriptedClient([_tool_turn("fetch_payment", {"payment_id": "pay_99999"}) for _ in range(8)])
    resolution, state = investigate(exc, _toolbox(), client, AgentConfig(), _PROMPTS)
    assert resolution.outcome == "ESCALATED_UNRESOLVED"
    assert state.evidence == []
    assert {e.record_key for e in resolution.evidence_chain} == {"int_00001"}
