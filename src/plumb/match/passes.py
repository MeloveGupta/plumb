"""LLD §4.1, TRD §5.2 -- the four matching passes.

Sequencing correction made during implementation (see DEVLOG, not the
original session plan): P0's exact-id union-find cannot commit every
>=2-side component the moment it forms one -- see MatchEngine.run()'s
own docstring in engine.py for why. P0 instead returns three pools:
`groups` (already >=2 sides, nothing more to wait for), `remaining`
(single-side, nothing to attach), and `pending` (a settlement_recon
chain missing its bank leg -- an open slot P1/P2/P3 each get a turn to
fill).

"counterparty" (TRD §5.2's third composite dimension) is deliberately
absent from P1/P3's comparison: `BankCredit` carries no counterparty
field, and `plumb_gen/narration.py` confirms bank narration only ever
encodes a UTR reference or is unparseable -- never a name. This domain
has exactly one real settlement counterparty (Razorpay's own settlement
engine crediting the platform's bank account), so the dimension is
structurally constant here; (amount, date) are what actually
discriminate. Flagged to the user before writing this.
"""

from dataclasses import dataclass

from plumb.domain.keys import RecordKey
from plumb.domain.models import (
    BankCredit,
    Dispute,
    Intent,
    Order,
    Payment,
    Refund,
    Reversal,
    SettlementRecon,
    Transfer,
)
from plumb.match.engine import AmbiguousMatch, MatchConfig, MatchGroup, Pass, RecordSet
from plumb.match.subsets import SubsetResult, SubsetStatus, find_subset
from plumb.match.tolerance import ToleranceProfile, dates_within_window

_RULE_ID: dict[Pass, str] = {
    "P0": "ID_CHAIN",
    "P1": "EXACT_COMPOSITE",
    "P2": "GROUP_SUBSET_SUM",
    "P3": "TOL_BAND",
}
_CONFIDENCE_BPS: dict[Pass, int] = {"P0": 10_000, "P1": 9_500, "P2": 9_000, "P3": 7_000}


def build_group(pass_: Pass, members: list[RecordKey], records: RecordSet) -> MatchGroup:
    sorted_members = sorted(set(members))
    return MatchGroup(
        rule_id=_RULE_ID[pass_],
        pass_=pass_,
        confidence_bps=_CONFIDENCE_BPS[pass_],
        members=tuple((k, records.side_of(k)) for k in sorted_members),
    )


def _join_pairs(record) -> list[tuple[str, str]]:
    """The exact-identifier edges P0 walks. Every field here is always
    populated on real generated data except BankCredit.utr (nullable
    when narration parsing fails, LLD §3.2) -- defects corrupt values
    (rates, amounts), never these identifiers.
    """
    if isinstance(record, (Order, Intent)):
        return [("order_id", record.order_id)]
    if isinstance(record, Payment):
        return [("order_id", record.order_id), ("payment_id", record.payment_id)]
    if isinstance(record, Transfer):
        return [("payment_id", record.payment_id), ("transfer_id", record.transfer_id)]
    if isinstance(record, Refund):
        return [("payment_id", record.payment_id)]
    if isinstance(record, Reversal):
        return [("transfer_id", record.transfer_id)]
    if isinstance(record, Dispute):
        return [("payment_id", record.payment_id)]
    if isinstance(record, SettlementRecon):
        pairs = [("utr", record.utr)]
        if record.entity_key is not None:
            # entity_type is "transfer" for every row plumb_gen emits today
            # (plumb_gen/world.py); keyed generically rather than assumed,
            # so a future entity_type doesn't silently join on the wrong field.
            key_field = "transfer_id" if record.entity_type == "transfer" else f"{record.entity_type}_id"
            pairs.append((key_field, record.entity_key))
        return pairs
    if isinstance(record, BankCredit):
        return [("utr", record.utr)] if record.utr is not None else []
    return []


def _find(parent: dict[RecordKey, RecordKey], x: RecordKey) -> RecordKey:
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:
        parent[x], x = root, parent[x]
    return root


def _union(parent: dict[RecordKey, RecordKey], a: RecordKey, b: RecordKey) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[rb] = ra


def _components(records: RecordSet, keys: list[RecordKey]) -> list[list[RecordKey]]:
    parent = {k: k for k in keys}
    edges: dict[tuple[str, str], list[RecordKey]] = {}
    for key in keys:
        for field_name, value in _join_pairs(records.get(key)):
            edges.setdefault((field_name, value), []).append(key)
    for keys_sharing_value in edges.values():
        first = keys_sharing_value[0]
        for other in keys_sharing_value[1:]:
            _union(parent, first, other)

    grouped: dict[RecordKey, list[RecordKey]] = {}
    for key in keys:  # preserves `keys`'s own order -- deterministic, not a set (rule 7)
        grouped.setdefault(_find(parent, key), []).append(key)
    return list(grouped.values())


@dataclass(frozen=True)
class _PendingGroup:
    """A P0-linked chain (order/intent/payment/transfer/settlement_recon)
    that spans >=2 sides but has no bank-side member yet."""

    members: tuple[RecordKey, ...]
    settlement_id: str
    target_paise: int  # sum of credit_paise across every settlement_recon in this chain
    settled_date: str  # ISO date or the date-prefix of an ISO timestamp


class PassP0:
    def run(
        self, records: RecordSet, remaining: list[RecordKey]
    ) -> tuple[list[MatchGroup], list[RecordKey], list["_PendingGroup"]]:
        groups: list[MatchGroup] = []
        new_remaining: list[RecordKey] = []
        pending: list[_PendingGroup] = []
        for members in _components(records, remaining):
            sides = {records.side_of(k) for k in members}
            recon_keys = [k for k in members if isinstance(records.get(k), SettlementRecon)]
            if recon_keys and "bank" not in sides:
                recons = [records.get(k) for k in recon_keys]
                pending.append(
                    _PendingGroup(
                        members=tuple(sorted(members)),
                        settlement_id=recons[0].settlement_id,
                        target_paise=sum(r.credit_paise for r in recons),
                        settled_date=recons[0].settled_at_utc,
                    )
                )
            elif len(sides) >= 2:
                groups.append(build_group("P0", members, records))
            else:
                new_remaining.extend(sorted(members))
        return groups, new_remaining, pending


def _attach_one_to_one(
    records: RecordSet,
    pending: list[_PendingGroup],
    orphan_bank_keys: list[RecordKey],
    pass_: Pass,
    comparator,
) -> tuple[list[MatchGroup], list[_PendingGroup], list[RecordKey], list[AmbiguousMatch]]:
    """Shared by P1 (exact composite) and P3 (tolerance band) -- both are
    1:1 pairings between a pending group and an orphan bank credit,
    differing only in `comparator`. A pairing is only claimed when it is
    unique from *both* sides: the pending group matches exactly one bank
    credit, and that bank credit matches exactly one pending group.
    Anything else is ambiguous, not guessed at -- same shape as P2's
    subset ambiguity.
    """
    pg_matches: list[list[RecordKey]] = [[] for _ in pending]
    bc_matches: dict[RecordKey, list[int]] = {bk: [] for bk in orphan_bank_keys}
    for pi, pg in enumerate(pending):
        for bk in orphan_bank_keys:
            if comparator(pg, records.get(bk)):
                pg_matches[pi].append(bk)
                bc_matches[bk].append(pi)

    groups: list[MatchGroup] = []
    ambiguous: list[AmbiguousMatch] = []
    resolved_pi: set[int] = set()
    claimed_bk: set[RecordKey] = set()
    contested_bk: set[RecordKey] = set()

    for pi, pg in enumerate(pending):
        matched = pg_matches[pi]
        if len(matched) == 1 and len(bc_matches[matched[0]]) == 1:
            bk = matched[0]
            groups.append(build_group(pass_, list(pg.members) + [bk], records))
            resolved_pi.add(pi)
            claimed_bk.add(bk)
        elif matched:
            # The bank leg is contested, not the chain itself -- the
            # chain's own identity (order/intent/payment/transfer/recon)
            # was already certain via P0's exact ids, so it finalises as
            # P0 regardless of which pass found the contested attachment.
            # The contested bank credit(s) stay out of every later pass's
            # pool but still surface in the final unmatched list -- an
            # ambiguous tie is not the same as a resolved claim.
            ambiguous.append(
                AmbiguousMatch(
                    pass_=pass_,
                    reason=f"settlement_id {pg.settlement_id}: {len(matched)} bank credit candidate(s)",
                    candidates=tuple(tuple(sorted(list(pg.members) + [bk])) for bk in matched),
                )
            )
            groups.append(build_group("P0", list(pg.members), records))
            resolved_pi.add(pi)
            contested_bk.update(matched)

    still_pending = [pg for pi, pg in enumerate(pending) if pi not in resolved_pi]
    still_orphan_bank = [bk for bk in orphan_bank_keys if bk not in claimed_bk and bk not in contested_bk]
    return groups, still_pending, still_orphan_bank, ambiguous, contested_bk


class PassP1:
    def run(self, records: RecordSet, pending: list[_PendingGroup], orphan_bank_keys: list[RecordKey]):
        def exact_match(pg: _PendingGroup, bc: BankCredit) -> bool:
            return pg.target_paise == bc.amount_paise and pg.settled_date[:10] == bc.credited_on[:10]

        return _attach_one_to_one(records, pending, orphan_bank_keys, "P1", exact_match)


def _match_target(target_paise: int, candidates: list[tuple[RecordKey, int]], max_members: int) -> SubsetResult:
    """find_subset only enumerates combinations of size >=2 (a size-1
    exact match is what P1 already covers for a single pending group vs
    a single bank credit) -- but here `target_paise` can be the *summed*
    total of several pending groups sharing one settlement_id, so a
    single bank credit equal to that combined total is a real, meaningful
    n:1 answer P1 never had the chance to find. Check size-1 first.
    """
    singles = [c for c in candidates if c[1] == target_paise]
    if len(singles) == 1:
        return SubsetResult(status=SubsetStatus.UNIQUE, members=(singles[0][0],))
    if len(singles) > 1:
        return SubsetResult(status=SubsetStatus.AMBIGUOUS, candidates=tuple((c[0],) for c in singles))
    return find_subset(target_paise, candidates, max_members)


class PassP2:
    def __init__(self, cfg: MatchConfig):
        self.cfg = cfg

    def run(self, records: RecordSet, pending: list[_PendingGroup], orphan_bank_keys: list[RecordKey]):
        groups: list[MatchGroup] = []
        ambiguous: list[AmbiguousMatch] = []
        resolved_pi: set[int] = set()
        claimed_bk: set[RecordKey] = set()
        contested_bk: set[RecordKey] = set()

        by_settlement: dict[str, list[int]] = {}
        for pi, pg in enumerate(pending):
            by_settlement.setdefault(pg.settlement_id, []).append(pi)

        for settlement_id, indices in by_settlement.items():
            target = sum(pending[pi].target_paise for pi in indices)
            candidates = [(bk, records.get(bk).amount_paise) for bk in orphan_bank_keys if bk not in claimed_bk]
            result = _match_target(target, candidates, self.cfg.max_subset_members)
            group_members = sorted(m for pi in indices for m in pending[pi].members)

            if result.status == SubsetStatus.UNIQUE:
                groups.append(build_group("P2", group_members + list(result.members), records))
                resolved_pi.update(indices)
                claimed_bk.update(result.members)
            elif result.status == SubsetStatus.AMBIGUOUS:
                ambiguous.append(
                    AmbiguousMatch(
                        pass_="P2",
                        reason=f"settlement_id {settlement_id}: {len(result.candidates)} bank-credit subsets sum to the same target",
                        candidates=tuple(tuple(sorted(group_members + list(c))) for c in result.candidates),
                    )
                )
                # Same reasoning as _attach_one_to_one: each pending
                # group's own identity chain was already certain via P0;
                # only the bank attachment is contested.
                for pi in indices:
                    groups.append(build_group("P0", list(pending[pi].members), records))
                resolved_pi.update(indices)
                contested_bk.update(key for c in result.candidates for key in c)

        still_pending = [pg for pi, pg in enumerate(pending) if pi not in resolved_pi]
        still_orphan_bank = [bk for bk in orphan_bank_keys if bk not in claimed_bk and bk not in contested_bk]
        return groups, still_pending, still_orphan_bank, ambiguous, contested_bk


class PassP3:
    def __init__(self, tolerance: ToleranceProfile):
        self.tolerance = tolerance

    def run(self, records: RecordSet, pending: list[_PendingGroup], orphan_bank_keys: list[RecordKey]):
        def within_band(pg: _PendingGroup, bc: BankCredit) -> bool:
            return self.tolerance.within(pg.target_paise, bc.amount_paise) and dates_within_window(
                pg.settled_date, bc.credited_on, self.tolerance.date_window_days
            )

        return _attach_one_to_one(records, pending, orphan_bank_keys, "P3", within_band)
