"""LLD §3.1 -- the adapter contract and normalise()'s pure-function shape.

CanonicalRecord = the existing plumb.domain.models entities the three
sources actually carry (Order, Intent, Payment, Refund, Transfer,
Reversal, Dispute, SettlementRecon, BankCredit) -- P0.2 already built
these for exactly this purpose; no new type needed. OrderLine and
SellerRateCard are out of scope for P1.1-P1.4: neither is needed by
this session's acceptance criteria, and OrderLine's taxable/GST
breakdown isn't consumed by matching (P1.5+) either.

NormalResult.record is widened from LLD's literal
`CanonicalRecord | None` to `CanonicalRecord | list[CanonicalRecord] | None`:
one intent.csv line carries both order-level fields (gross_amount,
category, placed_at_ist, status, is_interstate) and intent-level fields
(expected_commission, commission_rate_bps, expected_tcs, expected_tds)
-- nowhere else in any of the three sources does order-level ground
truth appear, and Intent has no fields to hold the order-level half.
One raw line genuinely becomes two canonical records (an Order and an
Intent). Flagged and documented, not a silent deviation -- razorpay.py
and bank.py's adapters return a single record, matching LLD's literal
shape exactly.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal, Protocol

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

CanonicalRecord = (
    Order | Intent | Payment | Refund | Transfer | Reversal | Dispute | SettlementRecon | BankCredit
)


@dataclass(frozen=True)
class RawRecord:
    raw_id: str
    source_id: Literal["intent", "razorpay", "bank"]
    line_no: int
    raw_payload: dict  # verbatim source fields -- json.dumps'd as-is at write time


@dataclass(frozen=True)
class Transform:
    field: str
    before_text: str | None
    after_text: str | None
    rule_id: str


@dataclass(frozen=True)
class NormalResult:
    record: CanonicalRecord | list[CanonicalRecord] | None  # None => quarantined
    transforms: list[Transform] = field(default_factory=list)
    quarantine_reason: str | None = None


class SourceAdapter(Protocol):
    source_id: Literal["intent", "razorpay", "bank"]
    source_tz: str  # "Asia/Kolkata" | "UTC"
    amount_unit: Literal["rupee_string", "paise_int"]

    def read(self, path: Path) -> Iterator[RawRecord]: ...
    def normalise(self, raw: RawRecord) -> NormalResult: ...


def derive_canonical_id(raw_id: str, prefix: str) -> str:
    """A canonical entity id, deterministically derived from its
    RawRecord's already-fixed raw_id -- never a freshly-consulted
    counter inside normalise() itself. normalise() must be a pure
    function (LLD §3.1): calling it twice on the same RawRecord has to
    produce the same record, and an internal IdSequence.next() call
    would silently break that (same input, different id, every call).
    Used only for entities the source itself doesn't already carry an
    id for (bank_credit_id, intent_id) -- razorpay.json's payments/
    transfers/etc. already carry their own "id" field and that's reused
    directly, not re-derived.
    """
    suffix = raw_id.rsplit("_", 1)[1]
    return f"{prefix}_{suffix}"
