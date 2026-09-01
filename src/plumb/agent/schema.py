"""LLD §7 / TRD §7.3 -- the agent's structured output.

The agent's final answer is a validated `submit_resolution` tool call,
never free text to be parsed (TRD §7.3). This module is that schema and
the invariants enforced in code rather than left to the model:

- `evidence_chain` is non-empty (TRD §7.3 / schema §3.6).
- `what_would_resolve_it` is present whenever the outcome is
  ESCALATED_UNRESOLVED -- the same guarantee the `resolution` table's
  final CHECK enforces at the storage layer.
- there are at least two ranked hypotheses unless the break was
  trivially determined (TRD §7.3, PRD §10.2.1 -- "plural, ordered,
  with reasoning. Not a single description").
- `confidence_bps` is a basis-point integer in 0..10000 (see
  config.py's deviation note on why not a float).

Two fields are populated by loop code, never taken from the model:
`amount_at_risk_paise` (authoritative value is on the exception -- PRD
§10.5 "no unsourced numbers"), and `stop_reason` / `iterations_used`
(loop-owned facts). The model supplies outcome, confidence, hypotheses,
evidence, and the two prose fields.

`model_claimed_outcome` records what the model asked for, before the
downgrade gate (gates.py) may have overridden it. It is set once, at
first construction, and `.downgrade()` preserves it -- the audit value
is in the difference between what was claimed and what code granted
(schema §3.6, APP_FLOW §3).
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Outcome = Literal["AUTO_RESOLVED", "PROPOSED", "ESCALATED_UNRESOLVED"]


class StopReason(StrEnum):
    """Values match resolution.stop_reason's CHECK constraint verbatim
    (schema §3.6) so an in-memory Resolution serialises straight to the
    column. LLD §7.2 names the members ITERATION_CAP / BUDGET_EXHAUSTED;
    the .value is what the DB stores.
    """

    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    ITERATION_CAP = "iteration_cap"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_FAILURE = "tool_failure"
    RULES_ONLY = "rules_only"


class EvidenceRef(BaseModel):
    """A pointer into the run's real records. Mirrors
    verify/trace.py::EvidenceRef but Pydantic -- the agent's output
    crosses a validation boundary the verifier's does not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_key: str
    role: str


class Hypothesis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int
    statement: str
    supports: list[str] = Field(default_factory=list)


class Resolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exception_id: str
    outcome: Outcome
    confidence_bps: int = Field(ge=0, le=10_000)
    hypotheses: list[Hypothesis]
    chosen_hypothesis_index: int | None = None
    evidence_chain: list[EvidenceRef] = Field(min_length=1)
    amount_at_risk_paise: int
    what_was_tried: str
    what_would_resolve_it: str | None = None
    trivially_determined: bool = False

    model_claimed_outcome: str | None = None
    was_downgraded: bool = False
    downgrade_reason: str | None = None

    stop_reason: StopReason
    iterations_used: int

    @model_validator(mode="before")
    @classmethod
    def _default_model_claimed_outcome(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("model_claimed_outcome") is None:
            return {**data, "model_claimed_outcome": data.get("outcome")}
        return data

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.outcome == "ESCALATED_UNRESOLVED" and not self.what_would_resolve_it:
            raise ValueError(
                "ESCALATED_UNRESOLVED requires what_would_resolve_it (TRD §7.3, "
                "resolution table CHECK)"
            )
        if not self.trivially_determined and len(self.hypotheses) < 2:
            raise ValueError(
                "at least two ranked hypotheses unless trivially_determined "
                "(TRD §7.3, PRD §10.2.1)"
            )
        if self.chosen_hypothesis_index is not None and not (
            0 <= self.chosen_hypothesis_index < len(self.hypotheses)
        ):
            raise ValueError(
                f"chosen_hypothesis_index {self.chosen_hypothesis_index} is out of "
                f"range for {len(self.hypotheses)} hypotheses"
            )
        return self

    def downgrade(self, reason: str) -> "Resolution":
        """LLD §7.3 -- returns a new Resolution with the outcome forced
        to PROPOSED, preserving `model_claimed_outcome` (the original
        claim is never overwritten) and recording the reason.
        model_copy, not re-construction, so the preserved claim can't be
        re-defaulted from the new outcome.
        """
        return self.model_copy(
            update={
                "outcome": "PROPOSED",
                "was_downgraded": True,
                "downgrade_reason": reason,
            }
        )
