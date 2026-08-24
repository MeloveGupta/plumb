"""TRD §5.3 / LLD §5.2-5.3 -- ToleranceProfile.

Lives in domain/, not match/ (LLD §1's module map), because TRD §3.3
requires the generator to import the *same* profile the engine uses for
D02 ("the generator imports the profile so the two cannot drift apart"),
and plumb_gen may only import plumb.domain (TRD §3.1) -- match/ is
engine-only and unreachable from there. Deliberate deviation from LLD's
literal module map, not a silent one; match/tolerance.py (P1.8) is free
to import this and add engine-side matching logic on top.
"""

from dataclasses import dataclass
from typing import Final

from plumb.domain.money import Bps, Paise, apply_bps


@dataclass(frozen=True)
class ToleranceProfile:
    name: str
    amount_abs_paise: Paise
    amount_rel_bps: Bps
    date_window_days: int

    def band_paise(self, amount_paise: Paise) -> Paise:
        return max(self.amount_abs_paise, apply_bps(amount_paise, self.amount_rel_bps))

    def within(self, expected_paise: Paise, actual_paise: Paise) -> bool:
        return abs(expected_paise - actual_paise) <= self.band_paise(expected_paise)


DEFAULT_V1: Final[ToleranceProfile] = ToleranceProfile(
    name="default_v1",
    amount_abs_paise=100,
    amount_rel_bps=10,
    date_window_days=2,
)
