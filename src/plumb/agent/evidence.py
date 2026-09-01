"""The read-only backing store the L3 tools query, plus the record
index the fabrication gate checks against.

Built entirely from `run_ingest()`'s canonical output -- the same dict
`RecordSet.from_ingest` and `build_units` already consume. No DB round
trip (there is no L3 persistence layer yet; the tools work from
in-memory canonical records exactly as P2's checks do).

`EvidenceStore` exposes narrow, typed lookups -- one per tool in
`tools.py`. Every list result is sorted by record key so a tool called
twice with the same args returns byte-identical output (rule 7 / the
per-call `result_sha256` in the audit log).

`RecordIndex` is a frozenset of every canonical record key in the run.
It is the in-memory equivalent of the `record_index` table that
`resolution_evidence.record_key`'s foreign key points at
(BACKEND_SCHEMA §3.6): a resolution whose evidence names a key absent
from here is a fabrication (gates.py).
"""

from dataclasses import dataclass
from datetime import date

from plumb.domain.models import (
    BankCredit,
    Dispute,
    Intent,
    Order,
    OrderLine,
    Payment,
    Refund,
    Reversal,
    Seller,
    SellerRateCard,
    SettlementRecon,
    Transfer,
)

# Every canonical entity -> the attribute holding its record key. The
# nine matchable entities plus the four that never reach the matcher
# (Order/Seller/SellerRateCard/OrderLine) -- all of them can be the
# target of an evidence reference, so all of them belong in the index.
_KEY_FIELD: dict[type, str] = {
    Order: "order_id",
    Intent: "intent_id",
    Payment: "payment_id",
    Refund: "refund_id",
    Transfer: "transfer_id",
    Reversal: "reversal_id",
    Dispute: "dispute_id",
    SettlementRecon: "settlement_recon_id",
    BankCredit: "bank_credit_id",
    SellerRateCard: "rate_card_id",
    Seller: "seller_id",
    OrderLine: "line_id",
}


def _all_records(ingest_result: dict) -> list:
    """Every record across all four ingest sides, in a fixed side order
    (rule 7 -- never dict iteration)."""
    out: list = []
    for side in ("intent", "razorpay", "bank", "sellers"):
        out.extend(ingest_result[side]["records"])
    return out


def _record_key(record: object) -> str:
    return getattr(record, _KEY_FIELD[type(record)])


class RecordIndex:
    """Membership only. Never iterated on a path that feeds output."""

    def __init__(self, keys: frozenset[str]) -> None:
        self._keys = keys

    def __contains__(self, key: str) -> bool:
        return key in self._keys

    def __len__(self) -> int:
        return len(self._keys)

    @staticmethod
    def from_ingest(ingest_result: dict) -> "RecordIndex":
        return RecordIndex(frozenset(_record_key(r) for r in _all_records(ingest_result)))


@dataclass(frozen=True)
class EvidenceStore:
    _payments: dict[str, Payment]
    _transfers: dict[str, Transfer]
    _disputes: dict[str, Dispute]
    _refunds_by_payment: dict[str, list[Refund]]
    _recon_by_date: dict[str, list[SettlementRecon]]
    _rate_cards: list[SellerRateCard]
    _intents: list[Intent]
    _seller_ids: frozenset[str]

    def payment(self, payment_id: str) -> Payment | None:
        return self._payments.get(payment_id)

    def transfer(self, transfer_id: str) -> Transfer | None:
        return self._transfers.get(transfer_id)

    def dispute(self, dispute_id: str) -> Dispute | None:
        return self._disputes.get(dispute_id)

    def has_payment(self, payment_id: str) -> bool:
        return payment_id in self._payments

    def has_seller(self, seller_id: str) -> bool:
        return seller_id in self._seller_ids

    def refunds_for_payment(self, payment_id: str) -> list[Refund]:
        return sorted(self._refunds_by_payment.get(payment_id, []), key=lambda r: r.refund_id)

    def settlement_recon_on(self, day: str) -> list[SettlementRecon]:
        return sorted(self._recon_by_date.get(day, []), key=lambda r: r.settlement_recon_id)

    def rate_cards_for(self, seller_id: str, as_of: str) -> list[SellerRateCard]:
        """As-of lookup by seller across every category. `as_of` is an
        ISO date (YYYY-MM-DD). Returns every card whose effective window
        covers that date, sorted by key -- the model picks the relevant
        category itself from the returned set."""
        target = date.fromisoformat(as_of)
        hits = [
            rc
            for rc in self._rate_cards
            if rc.seller_id == seller_id
            and date.fromisoformat(rc.effective_from) <= target
            and (rc.effective_to is None or target <= date.fromisoformat(rc.effective_to))
        ]
        return sorted(hits, key=lambda rc: rc.rate_card_id)

    def intents(self, order_id: str | None, seller_id: str | None) -> list[Intent]:
        hits = [
            it
            for it in self._intents
            if (order_id is None or it.order_id == order_id)
            and (seller_id is None or it.seller_id == seller_id)
        ]
        return sorted(hits, key=lambda it: it.intent_id)

    @staticmethod
    def from_ingest(ingest_result: dict) -> "EvidenceStore":
        payments: dict[str, Payment] = {}
        transfers: dict[str, Transfer] = {}
        disputes: dict[str, Dispute] = {}
        refunds_by_payment: dict[str, list[Refund]] = {}
        recon_by_date: dict[str, list[SettlementRecon]] = {}
        rate_cards: list[SellerRateCard] = []
        intents: list[Intent] = []
        seller_ids: set[str] = set()

        for rec in _all_records(ingest_result):
            if isinstance(rec, Payment):
                payments[rec.payment_id] = rec
            elif isinstance(rec, Transfer):
                transfers[rec.transfer_id] = rec
            elif isinstance(rec, Dispute):
                disputes[rec.dispute_id] = rec
            elif isinstance(rec, Refund):
                refunds_by_payment.setdefault(rec.payment_id, []).append(rec)
            elif isinstance(rec, SettlementRecon):
                recon_by_date.setdefault(rec.settled_at_utc[:10], []).append(rec)
            elif isinstance(rec, SellerRateCard):
                rate_cards.append(rec)
            elif isinstance(rec, Intent):
                intents.append(rec)
            elif isinstance(rec, Seller):
                seller_ids.add(rec.seller_id)

        return EvidenceStore(
            _payments=payments,
            _transfers=transfers,
            _disputes=disputes,
            _refunds_by_payment=refunds_by_payment,
            _recon_by_date=recon_by_date,
            _rate_cards=rate_cards,
            _intents=intents,
            _seller_ids=frozenset(seller_ids),
        )
