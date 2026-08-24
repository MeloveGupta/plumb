"""TRD §8.1 -- declarative defect injection config.

Only D01 carries a configurable severity_range_paise, matching TRD's own
example. The other seven defects' magnitudes emerge from the scenario
itself (the live tolerance band for D02, the actual refund/transfer/
reversal amount for D03/D06/D07, the actual return/MDR size for D04/D05/
D08) -- a configurable range on those would be a knob controlling
nothing real.
"""

from dataclasses import dataclass, field

DEFECT_IDS = ("D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08")


@dataclass(frozen=True)
class DefectSpec:
    count: int
    severity_range_paise: tuple[int, int] | None = None


@dataclass(frozen=True)
class InjectionConfig:
    defects: dict[str, DefectSpec] = field(default_factory=dict)

    def count_for(self, defect_id: str) -> int:
        spec = self.defects.get(defect_id)
        return spec.count if spec else 0

    def total_count(self) -> int:
        return sum(spec.count for spec in self.defects.values())
