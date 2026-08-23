"""PRD §4 domain entities.

Field names translate PRD §4's pseudocode through BACKEND_SCHEMA.md §1's
naming laws (PRD predates that doc): every money field ends _paise, every
rate ends _bps, every timestamp ends _utc. PKs/FKs are RecordKey; genuinely
external identifiers (Transfer.linked_account_id is Razorpay's own Route
account id, not one of ours) stay plain str.

model_config is strict=True, not just Pydantic's default lax mode: a float
passed to an int-typed _paise field must raise, not get silently coerced to
an int. That silent coercion is exactly what TRD Rule 1 exists to prevent,
and the domain model boundary is where it would otherwise slip through
unnoticed.
"""

from pydantic import BaseModel, ConfigDict

from plumb.domain.keys import RecordKey
from plumb.domain.money import Bps, Paise


class PlumbEntity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Order(PlumbEntity):
    order_id: RecordKey
    seller_id: str
    gross_amount_paise: Paise
    category: str
    placed_at_utc: str
    status: str
    is_interstate: bool


class OrderLine(PlumbEntity):
    line_id: RecordKey
    order_id: RecordKey
    sku: str
    taxable_value_paise: Paise
    gst_rate_bps: Bps
    gst_amount_paise: Paise


class Intent(PlumbEntity):
    # 1:1 with Order — order_id is both this record's identity and its FK.
    order_id: RecordKey
    seller_id: str
    expected_seller_amount_paise: Paise
    expected_commission_paise: Paise
    commission_rate_applied_bps: Bps
    expected_tcs_paise: Paise
    expected_tds_paise: Paise
    rate_card_version: str


class Payment(PlumbEntity):
    payment_id: RecordKey
    order_id: RecordKey
    amount_paise: Paise
    method: str
    status: str
    captured_at_utc: str
    fee_paise: Paise
    tax_paise: Paise


class Refund(PlumbEntity):
    refund_id: RecordKey
    payment_id: RecordKey
    amount_paise: Paise
    created_at_utc: str


class Transfer(PlumbEntity):
    transfer_id: RecordKey
    payment_id: RecordKey
    linked_account_id: str  # Razorpay Route account id — not our record_key scheme
    amount_paise: Paise
    on_hold: bool
    on_hold_until_utc: str | None = None
    settled_at_utc: str | None = None


class Reversal(PlumbEntity):
    reversal_id: RecordKey
    transfer_id: RecordKey
    amount_paise: Paise
    created_at_utc: str


class Dispute(PlumbEntity):
    dispute_id: RecordKey
    payment_id: RecordKey
    amount_paise: Paise
    status: str
    deducted_amount_paise: Paise


class SettlementRecon(PlumbEntity):
    entity_id: RecordKey  # points at a payment_id or transfer_id per entity_type
    entity_type: str
    settlement_id: str
    utr: str | None = None  # LLD §3.2 — sub-0.60-confidence narration is null, not quarantined
    amount_paise: Paise
    fee_paise: Paise
    tax_paise: Paise
    debit_paise: Paise
    credit_paise: Paise
    settled_at_utc: str
    dispute_id: RecordKey | None = None


class BankCredit(PlumbEntity):
    bank_ref: RecordKey
    utr: str | None = None
    amount_paise: Paise
    credited_at_utc: str
    narration: str  # raw source text; UTR extraction happens downstream in ingest


class SellerRateCard(PlumbEntity):
    # PRD §4 lists no id for this entity, but BACKEND_SCHEMA §1.2 gives it the
    # rate_ prefix and §1 states every domain row's PK is record_key with no
    # exception. PRD §4's own header permits extending the field list, so
    # this completes it rather than overriding anything.
    rate_card_id: RecordKey
    seller_id: str
    category: str
    commission_rate_bps: Bps
    effective_from_utc: str
    effective_to_utc: str | None = None
    version: str
