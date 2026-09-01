"""The L3 entry point: work the ranked exception queue, applying the
gates in a fixed order after each investigation.

Per exception: `investigate` (loop.py) -> `apply_downgrade_gate`
(code, not the model, grants autonomy) -> `assert_evidence_resolves`
(fatal on a fabricated reference). The order matters: the fabrication
check runs on the final, post-downgrade resolution.

`ablation="rules_only"` is a real code path (TRD §7.5), not a
hand-edited report: L3 is bypassed entirely and every queue entry
becomes an ESCALATED_UNRESOLVED with `what_was_tried = "rules-only
configuration"`.

`batch_token_budget` is optional and separate from AgentConfig's
per-exception `token_budget` (LLD §7.1). When set, once cumulative
spend reaches it the rest of the queue -- the cheapest exceptions,
since the queue is rupees-descending -- is escalated with
`budget_exhausted` rather than dropped (APP_FLOW §3). A batch budget is
not yet a config field; it is passed here by the orchestration caller.
"""

from plumb.agent.config import AgentConfig
from plumb.agent.evidence import RecordIndex
from plumb.agent.gates import apply_downgrade_gate, assert_evidence_resolves
from plumb.agent.loop import grounding_refs, investigate
from plumb.agent.model import ModelClient
from plumb.agent.prompts import Prompts
from plumb.agent.queue import Exception_
from plumb.agent.schema import Hypothesis, Resolution, StopReason
from plumb.agent.tools import Toolbox


def _rules_only_escalation(exc: Exception_) -> Resolution:
    return Resolution(
        exception_id=exc.exception_id,
        outcome="ESCALATED_UNRESOLVED",
        confidence_bps=0,
        hypotheses=[Hypothesis(rank=1, statement="not investigated -- rules-only configuration", supports=[])],
        chosen_hypothesis_index=None,
        evidence_chain=grounding_refs(exc, []),
        amount_at_risk_paise=exc.amount_at_risk_paise,
        what_was_tried="rules-only configuration",
        what_would_resolve_it="L3 investigation, which is disabled in this ablation arm",
        trivially_determined=True,
        stop_reason=StopReason.RULES_ONLY,
        iterations_used=0,
    )


def _batch_budget_escalation(exc: Exception_) -> Resolution:
    return Resolution(
        exception_id=exc.exception_id,
        outcome="ESCALATED_UNRESOLVED",
        confidence_bps=0,
        hypotheses=[Hypothesis(rank=1, statement="not investigated -- batch token budget exhausted", supports=[])],
        chosen_hypothesis_index=None,
        evidence_chain=grounding_refs(exc, []),
        amount_at_risk_paise=exc.amount_at_risk_paise,
        what_was_tried="the batch token budget was exhausted before this exception was reached",
        what_would_resolve_it="more batch token budget -- this exception was below the cutoff",
        trivially_determined=True,
        stop_reason=StopReason.BUDGET_EXHAUSTED,
        iterations_used=0,
    )


def run_investigation(
    queue: list[Exception_],
    toolbox: Toolbox,
    index: RecordIndex,
    client: ModelClient,
    cfg: AgentConfig,
    prompts: Prompts,
    *,
    ablation: str = "hybrid",
    batch_token_budget: int | None = None,
) -> list[Resolution]:
    if ablation == "rules_only":
        return [_rules_only_escalation(exc) for exc in queue]

    resolutions: list[Resolution] = []
    spent = 0
    for exc in queue:  # already in queue_rank order
        if batch_token_budget is not None and spent >= batch_token_budget:
            resolutions.append(_batch_budget_escalation(exc))
            continue
        resolution, state = investigate(exc, toolbox, client, cfg, prompts)
        spent += state.tokens_in + state.tokens_out
        resolution = apply_downgrade_gate(resolution, cfg)
        assert_evidence_resolves(resolution, index)  # fatal -- fabrication aborts the run
        resolutions.append(resolution)
    return resolutions
