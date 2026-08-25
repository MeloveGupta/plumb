"""LLD §4.3 -- the matcher's tolerance pass.

ToleranceProfile itself lives in `plumb.domain.tolerance`, not here --
see that module's own docstring and docs/HANDOFF.md §2 for why (TRD
§3.1's import boundary: plumb_gen may import plumb.domain only, and D02
must check against the exact same profile P3 matches against, so the
one definition has to live somewhere both sides can reach). This module
imports it rather than redefining it, and adds the one piece of
matching logic ToleranceProfile itself doesn't cover: the date-window
half of P3's check (band()/within() are amount-only).
"""

from datetime import date

from plumb.domain.tolerance import ToleranceProfile  # noqa: F401 -- re-exported for match/passes.py

__all__ = ["ToleranceProfile", "dates_within_window"]


def dates_within_window(a_date: str, b_date: str, window_days: int) -> bool:
    """a_date/b_date: ISO-8601 date strings, or the date portion of an
    ISO-8601 UTC timestamp (first 10 characters) -- callers pass
    whichever their record actually carries (BankCredit.credited_on is
    date-only; SettlementRecon.settled_at_utc is a timestamp).
    """
    a = date.fromisoformat(a_date[:10])
    b = date.fromisoformat(b_date[:10])
    return abs((a - b).days) <= window_days
