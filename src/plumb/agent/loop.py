"""LLD §7.1/§7.2 -- the per-exception investigation loop.

One `investigate()` call per exception. It talks only to the
`ModelClient` protocol (model.py) and the `Toolbox` (tools.py); the
gates (gates.py) are applied by the caller afterward, not here.

The two stop checks run *before* each model call, with a reserve
(LLD §7.2, §12.4): checking after means the final call can overshoot
and the recorded spend exceeds the declared budget -- a number you then
have to explain. `reserve_tokens` guarantees there is always enough
budget left to emit a proper ESCALATED_UNRESOLVED with its
`what_would_resolve_it`.

Degradation, never abort (TRD §12, LLD §7.2): a tool that can't answer
comes back as a `ToolFailure` the model sees; a `submit_resolution`
whose payload fails validation is fed back as an error the model can
correct within the iteration cap. Only the iteration cap and the budget
force a stop, and both produce a valid escalation.

`finalise()` stamps the loop-owned facts (`stop_reason`,
`iterations_used`). Mapping `chosen_hypothesis_index` to a
`chosen_hypothesis_id` FK is the persistence bridge's job -- hypotheses
get their ids at write time.
"""

from dataclasses import dataclass, field

from pydantic import ValidationError

from plumb.agent.config import AgentConfig
from plumb.agent.model import ModelClient, ModelResponse, ToolCall
from plumb.agent.prompts import Prompts
from plumb.agent.queue import Exception_
from plumb.agent.schema import EvidenceRef, Hypothesis, Resolution, StopReason
from plumb.agent.tools import (
    TOOL_SCHEMAS,
    AgentCall,
    IntentListView,
    RateCardListView,
    ReconListView,
    RefundListView,
    Toolbox,
    ToolFailure,
    ToolResult,
)

SUBMIT_SCHEMA: dict = {
    "name": "submit_resolution",
    "description": (
        "Your final answer for this exception. Call this once you have gathered "
        "enough evidence, or to escalate if you cannot resolve it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": ["AUTO_RESOLVED", "PROPOSED", "ESCALATED_UNRESOLVED"]},
            "confidence_bps": {
                "type": "integer", "minimum": 0, "maximum": 10000,
                "description": "Confidence in basis points; 10000 = fully certain.",
            },
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {"type": "integer"},
                        "statement": {"type": "string"},
                        "supports": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["rank", "statement"],
                },
                "description": "At least two, ranked, unless the break is trivially determined.",
            },
            "chosen_hypothesis_index": {"type": ["integer", "null"]},
            "evidence_chain": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"record_key": {"type": "string"}, "role": {"type": "string"}},
                    "required": ["record_key", "role"],
                },
                "description": "Non-empty. Every record_key must be one a tool returned to you.",
            },
            "what_was_tried": {"type": "string"},
            "what_would_resolve_it": {
                "type": ["string", "null"],
                "description": "Required when outcome is ESCALATED_UNRESOLVED.",
            },
            "trivially_determined": {"type": "boolean"},
        },
        "required": ["outcome", "confidence_bps", "hypotheses", "evidence_chain", "what_was_tried"],
    },
}


@dataclass
class InvestigationState:
    exception_id: str
    iteration: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    messages: list[dict] = field(default_factory=list)
    agent_calls: list[AgentCall] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    stop_reason: StopReason | None = None

    def budget_remaining(self, cfg: AgentConfig) -> int:
        return cfg.token_budget - (self.tokens_in + self.tokens_out)


# --- evidence extraction -------------------------------------------------------

_LIST_REFS = {
    RefundListView: ("refunds", "refund_id", "refund"),
    ReconListView: ("recon_rows", "settlement_recon_id", "settlement_recon"),
    RateCardListView: ("rate_cards", "rate_card_id", "rate_card"),
    IntentListView: ("intents", "intent_id", "intent"),
}
_SINGULAR_REFS = {
    "Payment": ("payment_id", "payment"),
    "Transfer": ("transfer_id", "transfer"),
    "Dispute": ("dispute_id", "dispute"),
}


def _refs_from_result(result: ToolResult) -> list[EvidenceRef]:
    if isinstance(result, ToolFailure):
        return []
    spec = _LIST_REFS.get(type(result))
    if spec is not None:
        list_attr, key_attr, role = spec
        return [EvidenceRef(record_key=getattr(item, key_attr), role=role) for item in getattr(result, list_attr)]
    singular = _SINGULAR_REFS.get(type(result).__name__)
    if singular is not None:
        key_attr, role = singular
        return [EvidenceRef(record_key=getattr(result, key_attr), role=role)]
    return []


def _accumulate_evidence(state: InvestigationState, result: ToolResult) -> None:
    have = {(e.record_key, e.role) for e in state.evidence}
    for ref in _refs_from_result(result):
        if (ref.record_key, ref.role) not in have:
            state.evidence.append(ref)
            have.add((ref.record_key, ref.role))


# --- prompt / message construction -------------------------------------------


def _initial_user_message(exc: Exception_) -> dict:
    lines = [
        f"Exception {exc.exception_id} (queue rank {exc.queue_rank}).",
        f"Origin: {exc.origin}.",
        f"Amount at risk: {exc.amount_at_risk_paise} paise.",
        f"Context: {exc.reason}",
    ]
    if exc.record_key:
        lines.append(f"Subject record: {exc.record_key}")
    if exc.candidates:
        lines.append("Competing candidate member sets (exactly one is correct):")
        for i, candidate in enumerate(exc.candidates):
            lines.append(f"  candidate {i}: {', '.join(candidate)}")
    if exc.finding is not None:
        lines.append(f"L2 finding {exc.finding.defect_id}: {exc.finding.conclusion}")
        for step in exc.finding.trace.steps:
            lines.append(f"  step {step.step_no} [{step.label}] {step.formula} over {step.inputs} = {step.output_paise}")
        lines.append(f"  trace conclusion: {exc.finding.trace.conclusion}")
        if exc.finding.evidence:
            lines.append("  finding evidence: " + ", ".join(f"{e.record_key} ({e.role})" for e in exc.finding.evidence))
    lines.append(
        "\nInvestigate with the tools, then call submit_resolution. Escalate if you cannot resolve it."
    )
    return {"role": "user", "content": "\n".join(lines)}


def _assistant_message(resp: ModelResponse) -> dict:
    content: list[dict] = []
    if resp.text:
        content.append({"type": "text", "text": resp.text})
    for call in resp.tool_calls:
        content.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.args})
    return {"role": "assistant", "content": content}


def _tool_result_block(call: ToolCall, result: ToolResult) -> dict:
    return {"type": "tool_result", "tool_use_id": call.id, "content": result.model_dump_json()}


def _error_result_block(call: ToolCall, message: str) -> dict:
    return {"type": "tool_result", "tool_use_id": call.id, "content": message, "is_error": True}


# --- finalisation ------------------------------------------------------------


def _find_submit(resp: ModelResponse) -> ToolCall | None:
    return next((c for c in resp.tool_calls if c.name == "submit_resolution"), None)


def parse_submit(call: ToolCall) -> dict:
    """Turn the model's submit_resolution args into the sub-objects
    Resolution expects. Raises ValidationError on a malformed payload --
    the loop feeds that back and lets the model correct it."""
    args = dict(call.args)
    hypotheses = [Hypothesis(**h) for h in args.get("hypotheses", [])]
    evidence = [EvidenceRef(**e) for e in args.get("evidence_chain", [])]
    return {
        "outcome": args.get("outcome"),
        "confidence_bps": args.get("confidence_bps"),
        "hypotheses": hypotheses,
        "chosen_hypothesis_index": args.get("chosen_hypothesis_index"),
        "evidence_chain": evidence,
        "what_was_tried": args.get("what_was_tried", ""),
        "what_would_resolve_it": args.get("what_would_resolve_it"),
        "trivially_determined": args.get("trivially_determined", False),
    }


def finalise(claimed: dict, exc: Exception_, state: InvestigationState) -> Resolution:
    """Construct the Resolution, stamping the loop-owned facts.
    amount_at_risk_paise comes from the exception, never the model
    (PRD §10.5). Raises ValidationError if the claim breaks an invariant."""
    return Resolution(
        exception_id=exc.exception_id,
        amount_at_risk_paise=exc.amount_at_risk_paise,
        stop_reason=StopReason.SUFFICIENT_EVIDENCE,
        iterations_used=state.iteration,
        **claimed,
    )


_RESOLVE_HINT = {
    StopReason.ITERATION_CAP: (
        "more investigation -- the 8-iteration cap was reached before a conclusion could be drawn"
    ),
    StopReason.BUDGET_EXHAUSTED: (
        "more token budget -- the per-exception budget was exhausted before a conclusion could be drawn"
    ),
    StopReason.TOOL_FAILURE: (
        "a working data source -- a tool call needed for the investigation could not be completed"
    ),
}


def grounding_refs(exc: Exception_, gathered: list[EvidenceRef]) -> list[EvidenceRef]:
    """A real, non-empty evidence chain for an escalation: whatever the
    tools actually returned, else the finding's own evidence, else the
    exception's subject record. A FINDING exception with no evidence and
    nothing gathered has no real key to cite -- that is an upstream bug,
    raised loudly rather than fabricated around."""
    if gathered:
        return list(gathered)
    if exc.origin == "FINDING" and exc.finding is not None and exc.finding.evidence:
        return [EvidenceRef(record_key=e.record_key, role=e.role) for e in exc.finding.evidence]
    if exc.record_key:
        return [EvidenceRef(record_key=exc.record_key, role="exception_subject")]
    raise AssertionError(
        f"exception {exc.exception_id}: no real record key to ground an escalation on "
        f"-- a FINDING with no evidence is an upstream bug"
    )


def forced_escalation(exc: Exception_, state: InvestigationState, reason: StopReason) -> Resolution:
    """A valid ESCALATED_UNRESOLVED for a stop the loop forced. Always
    carries a real evidence chain and a non-null what_would_resolve_it."""
    tried = "; ".join(f"{c.tool}({c.args})" for c in state.agent_calls if c.tool not in ("model_turn", "submit_resolution"))
    return Resolution(
        exception_id=exc.exception_id,
        outcome="ESCALATED_UNRESOLVED",
        confidence_bps=0,
        hypotheses=state.hypotheses
        or [Hypothesis(rank=1, statement="investigation did not reach a conclusion", supports=[])],
        chosen_hypothesis_index=None,
        evidence_chain=grounding_refs(exc, state.evidence),
        amount_at_risk_paise=exc.amount_at_risk_paise,
        what_was_tried=tried or "the investigation was stopped before any tool call completed",
        what_would_resolve_it=_RESOLVE_HINT[reason],
        trivially_determined=True,  # a forced stop is not held to the >=2 hypotheses rule
        stop_reason=reason,
        iterations_used=state.iteration,
    )


# --- the loop --------------------------------------------------------------


def investigate(
    exc: Exception_, toolbox: Toolbox, client: ModelClient, cfg: AgentConfig, prompts: Prompts
) -> tuple[Resolution, InvestigationState]:
    state = InvestigationState(exception_id=exc.exception_id)
    state.messages.append(_initial_user_message(exc))
    tool_schemas = [*TOOL_SCHEMAS, SUBMIT_SCHEMA]

    while True:
        if state.iteration >= cfg.max_iterations:
            resolution = forced_escalation(exc, state, StopReason.ITERATION_CAP)
            state.stop_reason = resolution.stop_reason
            return resolution, state
        if state.budget_remaining(cfg) < cfg.reserve_tokens:
            resolution = forced_escalation(exc, state, StopReason.BUDGET_EXHAUSTED)
            state.stop_reason = resolution.stop_reason
            return resolution, state

        state.iteration += 1
        resp = client.call(prompts.system_text, state.messages, tool_schemas, cfg)
        state.tokens_in += resp.usage.input_tokens
        state.tokens_out += resp.usage.output_tokens

        submit = _find_submit(resp)
        label = "submit_resolution" if submit is not None else "model_turn"
        state.agent_calls.append(
            toolbox.record_model_turn(
                exception_id=exc.exception_id, iteration=state.iteration, label=label,
                tool_call_count=len(resp.tool_calls), text=resp.text,
                tokens_in=resp.usage.input_tokens, tokens_out=resp.usage.output_tokens,
            )
        )
        state.messages.append(_assistant_message(resp))

        if submit is not None:
            try:
                resolution = finalise(parse_submit(submit), exc, state)
            except ValidationError as exc_err:
                state.messages.append(
                    {
                        "role": "user",
                        "content": [
                            _error_result_block(
                                submit,
                                f"submit_resolution rejected: {exc_err}. Correct it and call submit_resolution again.",
                            )
                        ],
                    }
                )
                continue
            state.stop_reason = resolution.stop_reason
            return resolution, state

        if not resp.tool_calls:
            state.messages.append(
                {"role": "user", "content": "Call one of the tools to gather evidence, or call submit_resolution."}
            )
            continue

        result_blocks: list[dict] = []
        for call in resp.tool_calls:
            result, agent_call = toolbox.invoke(
                call.name, call.args, exception_id=exc.exception_id, iteration=state.iteration
            )
            state.agent_calls.append(agent_call)
            _accumulate_evidence(state, result)
            result_blocks.append(_tool_result_block(call, result))
        state.messages.append({"role": "user", "content": result_blocks})
