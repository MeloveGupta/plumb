"""LLD §2 — Paise/Bps are documentation, not enforcement.

apply_bps is the rules module's (P0.5) consumer; sum_paise is match/
subsets.py's (P1.7). format_inr, parse_rupee_string stay deferred --
nothing consumes them yet.
"""

from typing import Iterable

Paise = int
Bps = int


def apply_bps(amount_paise: Paise, rate_bps: Bps) -> Paise:
    """Apply a rate. ROUND_HALF_UP on magnitude, applied exactly once.

    Sign is handled explicitly: floor division rounds toward negative
    infinity, which for a negative amount is round-half-DOWN. A refund
    or adjustment would then round the wrong way and disagree with the
    counterparty's arithmetic by one paisa.
    """
    sign = -1 if amount_paise < 0 else 1
    magnitude = abs(amount_paise)
    return sign * ((magnitude * rate_bps + 5_000) // 10_000)


def sum_paise(values: Iterable[Paise]) -> Paise:
    return sum(values)  # exact; no accumulation error by construction
