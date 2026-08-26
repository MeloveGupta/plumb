"""LLD §5.2 -- the Check protocol and the registry that runs them.

LLD §5.2's `Check.run(self, unit, ctx: CheckContext)` governs over an
older, simpler TRD §6.1 version with no `ctx` and no `requires` field.
# TRD-DEVIATION: TRD §6.1's Check protocol is superseded by LLD §5.2 --
D02's own pseudocode calls `ctx.tolerance.within(...)`, so a `ctx`-less
signature cannot implement it. Built to the LLD version.

`requires` lets the registry skip a check a unit cannot support, and --
more usefully -- report *why* a check never ran on some units (LLD
§5.2: "D08 was not evaluated on 41 units: no bank credit. Silence about
a check that never ran is the kind of gap a panelist finds.") The
registry enforces `requires` itself rather than trusting each check's
own `applies_to` to remember to -- `requires` is the registry's
contract; `applies_to` is a check's own additional data-availability
guard on top of it (e.g. D01 also needs a resolved rate card).
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from plumb.domain.tolerance import ToleranceProfile
from plumb.rules.ratebook import RateBook
from plumb.verify.trace import Finding, VerifyConfig
from plumb.verify.unit import Completeness, SettlementUnit


@dataclass(frozen=True)
class CheckContext:
    ratebook: RateBook
    tolerance: ToleranceProfile  # plumb.domain.tolerance -- the exact instance MatchEngine/PassP3 used, never reconstructed
    as_of: date
    config: VerifyConfig


class Check(Protocol):
    defect_id: str
    requires: frozenset[Completeness]

    def applies_to(self, unit: SettlementUnit) -> bool: ...
    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None: ...


@dataclass(frozen=True)
class SkipSummary:
    defect_id: str
    reason: str
    unit_count: int


@dataclass(frozen=True)
class RegistryResult:
    findings_by_unit: dict[str, list[Finding]]  # every unit_id present, even with an empty list
    skipped: list[SkipSummary]


def run_checks(units: list[SettlementUnit], checks: list[Check], ctx: CheckContext) -> RegistryResult:
    findings_by_unit: dict[str, list[Finding]] = {u.unit_id: [] for u in units}
    skip_counts: dict[tuple[str, str], int] = {}

    for unit in units:
        for check in checks:
            if unit.completeness not in check.requires:
                reason = f"completeness={unit.completeness.value} not in requires"
                skip_counts[(check.defect_id, reason)] = skip_counts.get((check.defect_id, reason), 0) + 1
                continue
            if not check.applies_to(unit):
                reason = "applies_to() declined"
                skip_counts[(check.defect_id, reason)] = skip_counts.get((check.defect_id, reason), 0) + 1
                continue
            finding = check.run(unit, ctx)
            if finding is not None:
                findings_by_unit[unit.unit_id].append(finding)

    skipped = [
        SkipSummary(defect_id=defect_id, reason=reason, unit_count=count)
        for (defect_id, reason), count in skip_counts.items()
    ]
    return RegistryResult(findings_by_unit=findings_by_unit, skipped=skipped)
