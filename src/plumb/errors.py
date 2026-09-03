"""LLD §9 — error hierarchy. Only the exceptions with a real consumer today
are defined; the rest of LLD §9's tree gets added when each one's consumer
arrives.
"""


class PlumbError(Exception): ...


class NoApplicableRate(PlumbError):
    """Recoverable -- becomes a finding, not a crash. rate_for raises this
    instead of silently falling back to a current or default rate."""


class ToolError(PlumbError):
    """L3, recoverable -- LLD §9. A read-only tool could not answer (bad
    id, no such record). The loop catches this, wraps it as a
    ToolFailure result the model can see, and continues: "degrade
    gracefully inside the agent loop" (LLD §9). One flaky call must
    never abort a batch (TRD §12)."""


class BudgetExhausted(PlumbError):
    """L3, recoverable -- LLD §9. The per-exception token budget would be
    overspent by the next model call. Becomes a forced
    ESCALATED_UNRESOLVED with stop_reason=budget_exhausted, never a
    crash (TRD §7.1)."""


class CassetteMiss(PlumbError):
    """L3, replay mode -- no recorded response for this request under
    fixtures/llm/. CI runs in replay (TRD §9.1: "a panelist forking the
    repo must get a green build"); a miss means the cassettes are stale
    and must be re-recorded locally with an API key."""

    def __init__(self, request_key: str) -> None:
        self.request_key = request_key
        super().__init__(
            f"no cassette for request {request_key[:12]} under fixtures/llm/. "
            f"Re-record locally with an API key: plumb run --ablation hybrid --record. "
            f"Inspect the request in reports/<run_id>/agent_calls.jsonl"
        )


class FabricationError(PlumbError):
    """L3, fatal -- LLD §7.3/§9. A resolution's evidence chain names a
    record_key that isn't in the run's record index. The model invented
    it. Aborts the whole run, non-zero exit -- "a fabricated number
    must always take down a run" (APP_FLOW §7). Not recoverable, not
    caught anywhere. This is the application-code half of the guarantee
    that resolution_evidence.record_key's FK into record_index also
    enforces at the storage layer (BACKEND_SCHEMA §3.6)."""

    def __init__(self, exception_id: str, record_key: str) -> None:
        self.exception_id = exception_id
        self.record_key = record_key
        super().__init__(
            f"exception {exception_id}: evidence references {record_key!r}, "
            f"which is not a real record in this run -- fabricated reference, run aborted"
        )
