"""PRD §5 / LLD §6 — the tax & fee rules module.

Every constant here carries its statute and effective date. Nothing may be
inlined elsewhere (CLAUDE.md rule 10).

Predecessor rates (the 1% TDS and 1% TCS rates that preceded the current
0.1%/0.5% ones) are deliberately not encoded: PRD §5 states the transition
dates but not when the predecessor rates themselves started, and that is
not a fact to guess or web-search mid-build. A query for a pre-transition
date correctly raises NoApplicableRate rather than returning a guessed
number. GST_ON_FEES (PRD §5.3, 18%) has the same gap -- no sourced
effective_from in PRD -- so the RateKind exists but no rule is registered
for it yet; it gets a real entry when D08 (P2.10) needs one.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Final

from plumb.domain.money import Bps
from plumb.errors import NoApplicableRate
from plumb.rules.basis import Basis


class RateKind(StrEnum):
    TDS = "tds"
    TCS = "tcs"
    GST_ON_FEES = "gst_on_fees"


@dataclass(frozen=True)
class RateRule:
    rule_id: str
    rate_bps: Bps
    basis: Basis = field(kw_only=True)  # positional-hostile: D04/D05 are basis errors
    effective_from: date
    effective_to: date | None
    provision: str
    legacy_provision: str | None
    source_url: str


class RateBook:
    # UTC date, not IST local date: this repo's dev sandbox is IST
    # (UTC+5:30); CI runs in UTC. "Today" in IST can still be "yesterday"
    # in UTC, which made the freshness test below read this date as being
    # in the future on the first CI run. Set from the UTC calendar date.
    VERIFIED_ON: Final[date] = date(2026, 8, 23)

    def __init__(self, rules_by_kind: dict[RateKind, list[RateRule]]):
        self._rules_by_kind = rules_by_kind

    def rate_for(self, kind: RateKind, as_of: date) -> RateRule:
        """As-of lookup. Raises NoApplicableRate -- never silently falls
        back to 'current'."""
        for rule in self._rules_by_kind.get(kind, []):
            in_range = rule.effective_from <= as_of and (
                rule.effective_to is None or as_of <= rule.effective_to
            )
            if in_range:
                return rule
        raise NoApplicableRate(f"no {kind.value} rate applicable as of {as_of.isoformat()}")


_TDS_STANDARD = RateRule(
    "TDS_STANDARD",
    10,
    basis=Basis.GROSS,
    effective_from=date(2024, 10, 1),
    effective_to=None,
    provision=(
        "Income-tax Act 2025 s.393(1), Table Sl. No. 8(v), payment code 1035 "
        "(effective 1 April 2026)"
    ),
    legacy_provision="Section 194-O, Income-tax Act 1961",
    source_url="PRD §5.1 -- rate cut 1% to 0.1% per Finance (No. 2) Act 2024, effective 1 Oct 2024",
)

_TCS_STANDARD = RateRule(
    "TCS_STANDARD",
    50,
    basis=Basis.NET_OF_RETURNS,
    effective_from=date(2024, 7, 10),
    effective_to=None,
    provision="Section 52, CGST Act 2017",
    legacy_provision=None,
    source_url=(
        "PRD §5.2 -- rate cut 1% to 0.5% per CBIC Notification No. 15/2024 / "
        "IGST Notification No. 01/2024, effective 10 Jul 2024"
    ),
)


def default_ratebook() -> RateBook:
    return RateBook(
        {
            RateKind.TDS: [_TDS_STANDARD],
            RateKind.TCS: [_TCS_STANDARD],
        }
    )
