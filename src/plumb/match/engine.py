"""LLD §4.1 -- the matcher's engine and its shared types.

RecordSet/MatchGroup/AmbiguousMatch/MatchResult/MatchConfig all live here
rather than in a fifth module: LLD §1's module map lists exactly
engine.py/passes.py/subsets.py/tolerance.py under match/, and these
types are the engine's own contract with passes.py, not an independent
concern. `MatchEngine.run()` imports passes.py lazily (inside the
method, not at module scope) because passes.py imports these types from
here -- a module-level import in both directions would be a real
circular import, not just an untidy one.
"""

from dataclasses import dataclass
from typing import Literal

from plumb.domain.keys import IdSequence, RecordKey
from plumb.domain.money import Bps
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
from plumb.domain.tolerance import ToleranceProfile
from plumb.ingest.normalise import CanonicalRecord
from plumb.store.writer import write_match_group, write_match_member

Side = Literal["intent", "razorpay", "bank"]
Pass = Literal["P0", "P1", "P2", "P3"]

_RECORD_KEY_FIELD: dict[type, str] = {
    Order: "order_id",
    Intent: "intent_id",
    Payment: "payment_id",
    Refund: "refund_id",
    Transfer: "transfer_id",
    Reversal: "reversal_id",
    Dispute: "dispute_id",
    SettlementRecon: "settlement_recon_id",
    BankCredit: "bank_credit_id",
}


def record_key_of(record: CanonicalRecord) -> RecordKey:
    return getattr(record, _RECORD_KEY_FIELD[type(record)])


@dataclass(frozen=True)
class RecordSet:
    by_key: dict[RecordKey, CanonicalRecord]
    side_by_key: dict[RecordKey, Side]

    def all_keys(self) -> list[RecordKey]:
        return list(self.by_key.keys())  # dict insertion order -- deterministic, not a set (rule 7)

    def get(self, key: RecordKey) -> CanonicalRecord:
        return self.by_key[key]

    def side_of(self, key: RecordKey) -> Side:
        return self.side_by_key[key]

    @staticmethod
    def from_ingest(ingest_result: dict) -> "RecordSet":
        """ingest_result is run_ingest()'s own return shape:
        {"sellers": {...}, "intent": {...}, "razorpay": {...}, "bank": {...}},
        each a run_adapter() summary with a "records" list. "sellers" is
        deliberately never read here -- sellers.csv is reference data
        (seller_id/rate-card lookup), not a matchable side;
        match_member.side has no 'sellers' value in schema/run.sql.
        """
        by_key: dict[RecordKey, CanonicalRecord] = {}
        side_by_key: dict[RecordKey, Side] = {}
        for side in ("intent", "razorpay", "bank"):  # fixed order, never dict iteration -- rule 7
            for record in ingest_result[side]["records"]:
                key = record_key_of(record)
                by_key[key] = record
                side_by_key[key] = side
        return RecordSet(by_key=by_key, side_by_key=side_by_key)


@dataclass(frozen=True)
class MatchGroup:
    rule_id: str
    pass_: Pass
    confidence_bps: Bps  # TRD §2.5: no float in the engine's own path -- 10000=1.00, 9500=0.95, ...
    members: tuple[tuple[RecordKey, Side], ...]  # (record_key, side), sorted by record_key


@dataclass(frozen=True)
class AmbiguousMatch:
    pass_: Pass
    reason: str
    candidates: tuple[tuple[RecordKey, ...], ...]


@dataclass(frozen=True)
class MatchResult:
    groups: tuple[MatchGroup, ...]
    unmatched: tuple[RecordKey, ...]
    ambiguous: tuple[AmbiguousMatch, ...]


@dataclass(frozen=True)
class MatchConfig:
    max_subset_members: int = 5


class MatchEngine:
    def __init__(self, tolerance: ToleranceProfile, cfg: MatchConfig | None = None) -> None:
        self.tolerance = tolerance
        self.cfg = cfg if cfg is not None else MatchConfig()

    def run(self, records: RecordSet) -> MatchResult:
        """P0 walks exact identifiers first. An order's intent+razorpay
        chain (order/intent/payment/transfer/settlement_recon) already
        spans >=2 sides even when the bank leg hasn't joined via a
        resolvable UTR -- committing that chain immediately would
        permanently claim the settlement_recon (a record is claimed
        exactly once, ever) before P1/P2/P3 get a chance to attach the
        orphaned bank_credit, and those passes would then never have a
        live settlement_recon left to pair against.

        So P0 only *provisionally* holds a chain with an unattached
        settlement_recon open as a "pending" group; P1 (exact
        composite), P2 (grouped subset-sum), P3 (tolerance band) each
        get a turn to attach an orphaned bank_credit to a still-open
        pending group. Whatever is still pending after P3 finalises as
        a plain P0 match -- the intent+razorpay linkage was always
        certain; a still-missing bank leg is a legitimate MISSING_BANK
        outcome for verify to classify later, not a matching failure. A
        pending group caught in an ambiguous tie still finalises as P0
        for its known members; the ambiguity over which bank credit
        belongs to it is reported separately so it doesn't block the
        part that was never actually in question.
        """
        from plumb.match.passes import PassP0, PassP1, PassP2, PassP3, build_group

        groups, remaining, pending = PassP0().run(records, records.all_keys())
        orphan_bank = [k for k in remaining if isinstance(records.get(k), BankCredit)]
        remaining = [k for k in remaining if k not in set(orphan_bank)]

        ambiguous: list[AmbiguousMatch] = []
        contested: set[RecordKey] = set()
        for pass_obj in (PassP1(), PassP2(self.cfg), PassP3(self.tolerance)):
            found, pending, orphan_bank, amb, pass_contested = pass_obj.run(records, pending, orphan_bank)
            groups.extend(found)
            ambiguous.extend(amb)
            contested.update(pass_contested)

        for pending_group in pending:
            groups.append(build_group("P0", list(pending_group.members), records))

        unmatched = sorted(set(remaining) | set(orphan_bank) | contested)
        return MatchResult(groups=tuple(groups), unmatched=tuple(unmatched), ambiguous=tuple(ambiguous))


def persist(conn, ids: IdSequence, result: MatchResult) -> dict[int, str]:
    """Writes every claimed MatchGroup to match_group/match_member.
    Ambiguous candidates and unmatched records get no DB row here -- the
    matcher made no claim for them, and match_group.pass's own CHECK
    constraint has no value to represent "ambiguous" with. Returns
    {index into result.groups: match_id} for callers that need to
    cross-reference (e.g. verify's SettlementUnit.match_id)."""
    match_ids: dict[int, str] = {}
    for index, group in enumerate(result.groups):
        match_id = write_match_group(
            conn, ids, rule_id=group.rule_id, pass_=group.pass_, confidence_bps=group.confidence_bps
        )
        for record_key, side in group.members:
            write_match_member(conn, match_id, record_key, side)
        match_ids[index] = match_id
    return match_ids
