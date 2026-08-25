"""LLD §4.2 -- grouped matching's subset-sum, and the ambiguity rule.

The only genuinely algorithmic component of the matcher. Two things
matter more than the arithmetic: the search is bounded (a hang is not
an answer), and when more than one subset fits, the caller is told all
of them rather than one being picked (a coin flip recorded as a match
is exactly how a silent error gets manufactured).
"""

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from typing import Protocol

from plumb.domain.keys import RecordKey
from plumb.domain.money import Paise, sum_paise

MAX_PARTITION_SIZE = 40


class HasAmountAndKey(Protocol):
    amount_paise: Paise
    record_key: RecordKey


class SubsetStatus(StrEnum):
    NO_MATCH = "no_match"
    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    TOO_LARGE = "too_large"  # partition exceeds MAX_PARTITION_SIZE -- routed to L3, never enumerated


@dataclass(frozen=True)
class SubsetResult:
    status: SubsetStatus
    members: tuple[RecordKey, ...] = ()
    candidates: tuple[tuple[RecordKey, ...], ...] = field(default_factory=tuple)


def find_subset(
    target_paise: Paise,
    candidates: list[tuple[RecordKey, Paise]],
    max_members: int = 5,
) -> SubsetResult:
    """Deterministic bounded subset-sum.

    candidates: (record_key, amount_paise) pairs -- callers pass plain
    tuples rather than domain entities so this module has no dependency
    on `plumb.ingest`/`plumb.domain.models` (match <- ingest is fine,
    but this file has no need of it).

    1. Fast path: if the whole partition sums to target, that's the
       answer -- the common real case, tried before any combinatorial
       search.
    2. Otherwise enumerate combinations of size 2..max_members over
       candidates sorted by (amount_paise, record_key), so enumeration
       order -- and therefore which duplicate-sum ties get found -- does
       not depend on input order or hash randomisation.
    3. Collect ALL subsets that sum to target; do not stop at the first.
    """
    if len(candidates) > MAX_PARTITION_SIZE:
        return SubsetResult(status=SubsetStatus.TOO_LARGE)

    if candidates and sum_paise(amount for _, amount in candidates) == target_paise:
        whole = tuple(sorted((key for key, _ in candidates)))
        return SubsetResult(status=SubsetStatus.UNIQUE, members=whole)

    sorted_candidates = sorted(candidates, key=lambda c: (c[1], c[0]))
    upper = min(max_members, len(sorted_candidates))
    matches: list[tuple[RecordKey, ...]] = []
    for k in range(2, upper + 1):
        for combo in combinations(sorted_candidates, k):
            if sum_paise(amount for _, amount in combo) == target_paise:
                matches.append(tuple(key for key, _ in combo))

    if len(matches) == 0:
        return SubsetResult(status=SubsetStatus.NO_MATCH)
    if len(matches) == 1:
        return SubsetResult(status=SubsetStatus.UNIQUE, members=matches[0])
    return SubsetResult(status=SubsetStatus.AMBIGUOUS, candidates=tuple(matches))
