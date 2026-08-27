"""LLD §5.2/§6, TRD §6.2 -- Finding and its recompute trace.

`amount_at_risk_paise` (not PRD's `amount_at_risk_inr`): the DB column
(schema/run.sql's finding table), plumb_eval/run_reader.py's read-side
dataclass, and CLAUDE.md rule 1 all agree on paise; rupee formatting is
report-layer-only (domain/money.format_inr, deferred, unused until
report/ needs it).

RecomputeStep/RecomputeTrace/TraceBuilder are a minimal slice brought
forward from P2.11 (the full recompute_trace emitter, not scheduled
yet) because D02's own LLD §5.3 pseudocode already requires
`build_trace(...)` to return something real: steps plus a conclusion
string, no re-evaluation harness. P2.11 adds that on top without
changing this shape.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self

from plumb.domain.money import Paise


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class VerifyConfig:
    """Placeholder thresholds -- no spec gives real numbers for these.
    Pick real ones before the panel demo; the mechanism (one config-owned
    function every check calls) is what's being committed to now.

    d06_hold_age_days: comfortably above the legitimate
    hold_release_days=7 window (plumb_gen/config.py) so an ordinary,
    still-resolving hold never trips it, and comfortably below D06's own
    forced 21-day floor (min(hold_release_days + 14, order_lookback_days))
    so every injected instance is caught with margin either direction.
    verify/ can't import plumb_gen's config directly (TRD §3.1), so this
    is its own independent constant, not derived from it.
    """

    d06_hold_age_days: int = 14
    severity_medium_min_paise: Paise = 10_000  # >= Rs 100
    severity_high_min_paise: Paise = 100_000  # >= Rs 1,000


def classify_severity(amount_at_risk_paise: Paise, cfg: VerifyConfig) -> Severity:
    if amount_at_risk_paise >= cfg.severity_high_min_paise:
        return Severity.HIGH
    if amount_at_risk_paise >= cfg.severity_medium_min_paise:
        return Severity.MEDIUM
    return Severity.LOW


@dataclass(frozen=True)
class RecomputeStep:
    step_no: int
    label: str
    formula: str
    inputs: dict[str, int | str]
    output_paise: Paise


@dataclass(frozen=True)
class RecomputeTrace:
    steps: tuple[RecomputeStep, ...]
    conclusion: str


class TraceBuilder:
    def __init__(self) -> None:
        self._steps: list[RecomputeStep] = []

    def step(self, label: str, formula: str, inputs: dict[str, int | str], output_paise: Paise) -> Self:
        self._steps.append(RecomputeStep(len(self._steps) + 1, label, formula, dict(inputs), output_paise))
        return self

    def conclude(self, text: str) -> RecomputeTrace:
        return RecomputeTrace(steps=tuple(self._steps), conclusion=text)


@dataclass(frozen=True)
class EvidenceRef:
    record_key: str
    role: str


@dataclass(frozen=True)
class Finding:
    defect_id: str
    unit_id: str
    severity: Severity
    amount_at_risk_paise: Paise
    on_matched_record: bool
    conclusion: str
    trace: RecomputeTrace
    evidence: tuple[EvidenceRef, ...]
