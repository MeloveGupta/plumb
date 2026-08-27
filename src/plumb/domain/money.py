"""LLD §2 — Paise/Bps are documentation, not enforcement.

apply_bps is the rules module's (P0.5) consumer; sum_paise is match/
subsets.py's (P1.7); format_inr is report/'s (P2.12). parse_rupee_string
stays deferred -- nothing consumes it yet.
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


def format_inr(amount_paise: Paise) -> str:
    """UIUX_BRIEF §2.3/§2.4: right-aligned on the decimal, always two
    places, always with the rupee sign -- ₹1,200.00, never ₹1200,
    never ₹1.2k. Pure integer arithmetic throughout (divmod, string
    slicing), no float anywhere -- this is domain/, not report/, and
    the no-float rule applies here regardless of what calls it.

    Indian digit grouping (last 3 digits, then groups of 2 --
    1,20,000.00 not 120,000.00): the domain's own convention, chosen
    because nothing in UIUX_BRIEF gives a large-number example to
    confirm the grouping scheme against. A documented choice, not a
    transcribed spec number -- revisit if the brief is ever amended
    with one.
    """
    sign = "-" if amount_paise < 0 else ""
    rupees, paise = divmod(abs(amount_paise), 100)
    rupees_str = str(rupees)
    if len(rupees_str) > 3:
        last3, rest = rupees_str[-3:], rupees_str[:-3]
        groups: list[str] = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        rupees_str = ",".join(groups) + "," + last3
    return f"{sign}₹{rupees_str}.{paise:02d}"
