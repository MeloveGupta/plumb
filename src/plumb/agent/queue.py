"""APP_FLOW §2 -- turning L1's residual and L2's findings into the
ranked exception queue L3 works through.

One `Exception_` per unmatched record, per ambiguous candidate set, and
per finding. The queue is processed strictly descending by
`amount_at_risk_paise` (APP_FLOW §2): if the token budget runs out, what
goes uninvestigated is the cheapest, never a random tail.

`Exception_` mirrors the `exception` table's columns (BACKEND_SCHEMA
§3.6) plus two fields that are context for the investigation prompt and
are not persisted on the row: `candidates` (the competing member sets
of an ambiguous match -- PRD §10.2.3, "resolve genuine ambiguity") and
`finding` (the full L2 finding, so the loop can ground the prompt in
its recompute trace without a DB read).

This session routes only the matcher's own `AmbiguousMatch` subsets.
The ambiguous-seller-name case (HANDOFF §4) stays a scored
correct-abstention -- routing it needs an `exception.origin` value that
doesn't exist yet, deferred.
"""

from dataclasses import dataclass
from typing import Literal, Sequence

from plumb.domain.keys import IdSequence
from plumb.match.engine import AmbiguousMatch, MatchResult, RecordSet
from plumb.verify.trace import Finding

Origin = Literal["UNMATCHED", "FINDING"]


@dataclass(frozen=True)
class Exception_:
    exception_id: str
    origin: Origin
    record_key: str | None
    finding_id: str | None
    amount_at_risk_paise: int
    queue_rank: int
    reason: str
    candidates: tuple[tuple[str, ...], ...] = ()
    finding: Finding | None = None


def _amount_for_key(records: RecordSet, key: str) -> int:
    """The record's own money value, for ranking. 0 if the key isn't in
    the set (a matcher candidate key always is; being defensive here
    costs nothing and keeps a surprise from crashing the queue)."""
    if key not in records.by_key:
        return 0
    record = records.get(key)
    for attr in ("amount_paise", "gross_paise", "expected_seller_amount_paise", "credit_paise"):
        value = getattr(record, attr, None)
        if value is not None:
            return value
    return 0


def _contested_key(match: AmbiguousMatch) -> str:
    """The record the candidates disagree about: present in some
    candidate member sets but not all. Falls back to the first key of
    the first candidate if every candidate is identical (shouldn't
    happen -- an AmbiguousMatch with one distinct candidate isn't
    ambiguous)."""
    in_every: set[str] | None = None
    seen: set[str] = set()
    for candidate in match.candidates:
        seen.update(candidate)
        in_every = set(candidate) if in_every is None else (in_every & set(candidate))
    contested = sorted(seen - (in_every or set()))
    if contested:
        return contested[0]
    return match.candidates[0][0]


def build_exception_queue(
    match_result: MatchResult,
    records: RecordSet,
    findings: Sequence[tuple[str, Finding]],
    ids: IdSequence,
) -> list[Exception_]:
    """`findings` is (finding_id, Finding) pairs -- the id assignment is
    the caller's (the persistence bridge writes findings and gets their
    ids, then passes them here). Everything is built unranked, then
    sorted descending by amount with a stable string tie-break, then
    `queue_rank` and `exception_id` are assigned in that order so
    exc_00001 is always the costliest break."""

    @dataclass
    class _Pending:
        origin: Origin
        record_key: str | None
        finding_id: str | None
        amount: int
        reason: str
        candidates: tuple[tuple[str, ...], ...]
        finding: Finding | None
        tiebreak: str

    pending: list[_Pending] = []

    for key in match_result.unmatched:
        amount = _amount_for_key(records, key)
        pending.append(_Pending("UNMATCHED", key, None, amount, "residual: unmatched record", (), None, key))

    for match in match_result.ambiguous:
        contested = _contested_key(match)
        amount = _amount_for_key(records, contested)
        pending.append(
            _Pending("UNMATCHED", contested, None, amount, match.reason, tuple(match.candidates), None, contested)
        )

    for finding_id, finding in findings:
        pending.append(
            _Pending(
                "FINDING", None, finding_id, finding.amount_at_risk_paise,
                f"{finding.defect_id}: {finding.conclusion}", (), finding, finding_id,
            )
        )

    pending.sort(key=lambda p: (-p.amount, p.tiebreak))

    queue: list[Exception_] = []
    for rank, p in enumerate(pending, start=1):
        queue.append(
            Exception_(
                exception_id=ids.next("exc"),
                origin=p.origin,
                record_key=p.record_key,
                finding_id=p.finding_id,
                amount_at_risk_paise=p.amount,
                queue_rank=rank,
                reason=p.reason,
                candidates=p.candidates,
                finding=p.finding,
            )
        )
    return queue
