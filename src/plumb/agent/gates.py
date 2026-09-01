"""LLD §7.3 -- the two gates code applies to a claimed resolution
*after* the loop returns it. The loop does not call these; the caller
(run_investigation) does, in a fixed order: downgrade, then fabrication.

The downgrade gate is where code, not the model, decides the model's
autonomy (APP_FLOW §3): a claimed AUTO_RESOLVED is granted only if the
amount at risk is below the configured threshold *and* confidence is at
or above it. Otherwise the outcome is forced to PROPOSED, preserving
`model_claimed_outcome` so the audit shows the difference between what
was claimed and what was granted.

The fabrication gate is fatal. Every evidence reference must resolve to
a real record key; one that doesn't means the model invented it, and
"a fabricated number must always take down a run" (APP_FLOW §7). This
is the application-code half of the guarantee that
`resolution_evidence.record_key`'s foreign key into `record_index`
enforces at the storage layer.
"""

from plumb.agent.config import AgentConfig
from plumb.agent.evidence import RecordIndex
from plumb.agent.schema import Resolution
from plumb.errors import FabricationError


def apply_downgrade_gate(claimed: Resolution, cfg: AgentConfig) -> Resolution:
    if claimed.outcome != "AUTO_RESOLVED":
        return claimed
    if claimed.amount_at_risk_paise >= cfg.auto_resolve_threshold_paise:
        return claimed.downgrade("amount_above_threshold")
    # PRD-DEVIATION: PRD §10.4 phrases the bar as "confidence > threshold".
    # LLD §7.3's gate downgrades when confidence < threshold -- i.e. autonomy
    # is granted on >=. The gate code is authoritative; the boundary case
    # (confidence exactly at the threshold) is granted, not downgraded.
    if claimed.confidence_bps < cfg.confidence_threshold_bps:
        return claimed.downgrade("confidence_below_threshold")
    return claimed


def assert_evidence_resolves(res: Resolution, index: RecordIndex) -> None:
    """Raises FabricationError. Aborts the run. Not recoverable, not
    caught anywhere."""
    for ref in res.evidence_chain:
        if ref.record_key not in index:
            raise FabricationError(res.exception_id, ref.record_key)
