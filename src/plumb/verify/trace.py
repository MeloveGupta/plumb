"""LLD §5.2/§6, TRD §6.2 -- Finding and its recompute trace.

`amount_at_risk_paise` (not PRD's `amount_at_risk_inr`): the DB column
(schema/run.sql's finding table), plumb_eval/run_reader.py's read-side
dataclass, and CLAUDE.md rule 1 all agree on paise; rupee formatting is
report-layer-only (domain/money.format_inr, deferred, unused until
report/ needs it).

RecomputeStep/RecomputeTrace/TraceBuilder shape is unchanged since P2.2
(D02's own LLD §5.3 pseudocode already required `build_trace(...)` to
return steps + a conclusion). P2.11 adds `reevaluate_step`/
`reevaluate_trace` on top without touching that shape -- LLD §5.4:
"Every step's output must be reachable from its declared inputs by the
stated formula -- asserted in tests by re-evaluating simple formulas
from the inputs dict... a trace can never describe arithmetic the code
didn't actually do." LLD gives no mechanism, only that requirement; the
one here is a small, restricted AST evaluator (`+ - * // /`, unary
minus, `abs()/min()/max()`, int constants, name lookups against
`inputs`) -- deliberately not a bare `eval()`, and deliberately not run
at check-time (LLD says "asserted in tests", and `recompute_step` has
no column to store a verified flag against, confirming this is a
test-time invariant, not a runtime one).

Every check's `.step()` calls were retrofitted to comply: a formula
must be a literal, executable expression over its own `inputs` dict --
no human-only annotations like "(round-half-up)" in the formula text,
no rate constants baked into an f-string, no list aggregate compressed
into a bare count. Where a step previously described more than one
arithmetic operation at once (e.g. D02/D03's multi-term expected-net
formulas), it was split into multiple smaller chained steps instead,
each individually re-evaluatable and each one's output feeding the
next's inputs -- closer to TRD §6.2's own worked example, which already
chains steps this way. A business-rule gate (D02's tolerance-band check,
D06's age threshold) is not itself a step -- only money arithmetic is;
the gate's outcome is described in the conclusion text instead.
"""

import ast
import operator
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


_ALLOWED_BINOPS: dict[type, "object"] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Div: operator.truediv,
}
_ALLOWED_CALLS = {"abs": abs, "min": min, "max": max}


def _eval_node(node: ast.AST, inputs: dict[str, int | str]) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        value = inputs[node.id]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"input {node.id!r} is not an int: {value!r}")
        return value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left, right = _eval_node(node.left, inputs), _eval_node(node.right, inputs)
        return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand, inputs)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_CALLS:
        args = [_eval_node(a, inputs) for a in node.args]
        return _ALLOWED_CALLS[node.func.id](*args)
    raise ValueError(f"unsupported expression node in formula: {ast.dump(node)}")


def reevaluate_step(step: RecomputeStep) -> int:
    """LLD §5.4's re-evaluation mechanism: parse `step.formula` as a
    restricted arithmetic expression and evaluate it against
    `step.inputs`. Any name the formula references that isn't a key in
    `inputs`, or any expression shape outside the small whitelist above,
    raises -- a step whose formula can't be independently re-derived
    from its own declared inputs is a bug in the step, not something to
    silently skip.
    """
    tree = ast.parse(step.formula, mode="eval")
    return _eval_node(tree.body, step.inputs)


def reevaluate_trace(trace: RecomputeTrace) -> None:
    """Asserts every step in `trace` re-evaluates to its own
    `output_paise` -- LLD §5.4: "asserted in tests," not a runtime
    check (recompute_step has no column for a stored verified flag).
    Raises AssertionError naming the offending step, not a bare
    assert, so a failure in CI points straight at which step lied.
    """
    for step in trace.steps:
        recomputed = reevaluate_step(step)
        if recomputed != step.output_paise:
            raise AssertionError(
                f"step {step.step_no} ({step.label!r}): formula {step.formula!r} over {step.inputs!r} "
                f"evaluates to {recomputed}, but output_paise was recorded as {step.output_paise}"
            )


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
