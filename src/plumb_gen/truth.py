"""BACKEND_SCHEMA.md §4 / TRD §8.2 -- the truth schema shapes, built as
plain dataclasses here and written to truth.sqlite by truth_db.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TruthRecord:
    record_key: str
    true_counterparts: list[str]
    true_obligation: dict[str, int]
    resolvable_from_available_data: bool


@dataclass(frozen=True)
class InjectedDefect:
    instance_id: str
    record_key: str
    defect_class: str
    amount_at_risk_paise: int
    within_tolerance: bool
    params: dict[str, object]
