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

from typing import Literal

from pydantic import BaseModel, ConfigDict

from plumb.domain.keys import RecordKey
from plumb.domain.money import Bps, Paise


class PlumbEntity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Order(PlumbEntity):
    order_id: RecordKey
    seller_id: str
    gross_paise: Paise
    category: str
    placed_at_utc: str
    status: str
    is_interstate: bool


class OrderLine(PlumbEntity):
    line_id: RecordKey
    order_id: RecordKey
    sku: str
    taxable_paise: Paise
    gst_bps: Bps
    gst_paise: Paise


class Intent(PlumbEntity):
    # SCHEMA-FIX: P0.2 originally had order_id doing double duty as both
    # identity and FK. BACKEND_SCHEMA.md §3.3's actual DDL gives intent its
    # own record_key distinct from order_key, found while building the
    # generator (P0.6) and needing an id to actually assign. Caught the
    # same class of gap for SellerRateCard back in P0.3 but missed this one
    # at the time.
    intent_id: RecordKey
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
    method: Literal["upi", "card", "netbanking", "wallet"]  # BACKEND_SCHEMA.md §3.3
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
    # SCHEMA-FIX (found alongside the Intent one, same audit): this model
    # was missing its own record_key (BACKEND_SCHEMA §1.2 gives it the
    # setl_ prefix), had entity_key misnamed entity_id, dispute_key
    # misnamed dispute_id, and wrongly made utr nullable — that nullability
    # belongs to bank_credit.utr (extracted from narration, can fail), not
    # here. Razorpay's own settlement file always states its own utr; only
    # the bank statement's narration-based extraction can fail.
    settlement_recon_id: RecordKey
    entity_key: RecordKey | None = None  # points at a payment_id or transfer_id per entity_type
    entity_type: str
    settlement_id: str
    utr: str
    amount_paise: Paise
    fee_paise: Paise
    tax_paise: Paise
    debit_paise: Paise
    credit_paise: Paise
    settled_at_utc: str
    dispute_key: RecordKey | None = None


class BankCredit(PlumbEntity):
    # SCHEMA-FIX: same audit -- was missing its own record_key (bank_
    # prefix per BACKEND_SCHEMA §1.2); bank_ref is a separate, external
    # bank-provided reference, not our own key format. credited_at_utc
    # renamed to credited_on -- the SQL comment is explicit that this is a
    # date, not a timestamp ("the bank gives no time"), which is also why
    # it doesn't carry the _utc suffix.
    bank_credit_id: RecordKey
    bank_ref: str
    utr: str | None = None
    amount_paise: Paise
    credited_on: str
    narration: str  # raw source text; UTR extraction happens downstream in ingest


class SellerRateCard(PlumbEntity):
    # PRD §4 lists no id for this entity, but BACKEND_SCHEMA §1.2 gives it the
    # rate_ prefix and §1 states every domain row's PK is record_key with no
    # exception. PRD §4's own header permits extending the field list, so
    # this completes it rather than overriding anything.
    rate_card_id: RecordKey
    seller_id: str
    category: str
    commission_bps: Bps
    effective_from: str
    effective_to: str | None = None
    version: str
