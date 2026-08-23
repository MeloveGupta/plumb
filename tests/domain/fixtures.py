"""One realistic fixture per PRD §4 entity, paired with its model class.

Realistic, not placeholder: record-key-shaped ids, plausible paise amounts,
ISO-8601 UTC timestamps — so a round-trip failure here means a real
modelling bug, not a fixture that was already too loose to catch one.
"""

from plumb.domain.models import (
    BankCredit,
    Dispute,
    Intent,
    Order,
    OrderLine,
    Payment,
    Refund,
    Reversal,
    SellerRateCard,
    SettlementRecon,
    Transfer,
)

ENTITY_FIXTURES = [
    (
        Order,
        {
            "order_id": "ord_00042",
            "seller_id": "sel_00007",
            "gross_amount_paise": 118000,
            "category": "electronics",
            "placed_at_utc": "2026-07-15T10:30:00Z",
            "status": "captured",
            "is_interstate": False,
        },
    ),
    (
        OrderLine,
        {
            "line_id": "oln_00042",
            "order_id": "ord_00042",
            "sku": "SKU-4471",
            "taxable_value_paise": 100000,
            "gst_rate_bps": 1800,
            "gst_amount_paise": 18000,
        },
    ),
    (
        Intent,
        {
            "order_id": "ord_00042",
            "seller_id": "sel_00007",
            "expected_seller_amount_paise": 100000,
            "expected_commission_paise": 15000,
            "commission_rate_applied_bps": 1500,
            "expected_tcs_paise": 500,
            "expected_tds_paise": 118,
            "rate_card_version": "v3",
        },
    ),
    (
        Payment,
        {
            "payment_id": "pay_00042",
            "order_id": "ord_00042",
            "amount_paise": 118000,
            "method": "upi",
            "status": "captured",
            "captured_at_utc": "2026-07-15T10:31:12Z",
            "fee_paise": 2000,
            "tax_paise": 360,
        },
    ),
    (
        Refund,
        {
            "refund_id": "rfnd_00042",
            "payment_id": "pay_00042",
            "amount_paise": 5000,
            "created_at_utc": "2026-07-16T09:00:00Z",
        },
    ),
    (
        Transfer,
        {
            "transfer_id": "txfr_00042",
            "payment_id": "pay_00042",
            "linked_account_id": "acc_LinkedSellerXYZ",
            "amount_paise": 85000,
            "on_hold": True,
            "on_hold_until_utc": "2026-07-19T00:00:00Z",
            "settled_at_utc": None,
        },
    ),
    (
        Reversal,
        {
            "reversal_id": "rvsl_00042",
            "transfer_id": "txfr_00042",
            "amount_paise": 2000,
            "created_at_utc": "2026-07-20T00:00:00Z",
        },
    ),
    (
        Dispute,
        {
            "dispute_id": "disp_00042",
            "payment_id": "pay_00042",
            "amount_paise": 118000,
            "status": "open",
            "deducted_amount_paise": 0,
        },
    ),
    (
        SettlementRecon,
        {
            "entity_id": "txfr_00042",
            "entity_type": "transfer",
            "settlement_id": "setl_00042",
            "utr": "UTR1234567890123",
            "amount_paise": 85000,
            "fee_paise": 1500,
            "tax_paise": 270,
            "debit_paise": 0,
            "credit_paise": 85000,
            "settled_at_utc": "2026-07-19T06:00:00Z",
            "dispute_id": None,
        },
    ),
    (
        BankCredit,
        {
            "bank_ref": "bank_00042",
            "utr": "UTR1234567890123",
            "amount_paise": 85000,
            "credited_at_utc": "2026-07-19T06:05:00Z",
            "narration": "NEFT/UTR1234567890123/PLATFORM SETTLEMENT",
        },
    ),
    (
        SellerRateCard,
        {
            "rate_card_id": "rate_00042",
            "seller_id": "sel_00007",
            "category": "electronics",
            "commission_rate_bps": 1500,
            "effective_from_utc": "2026-07-01T00:00:00Z",
            "effective_to_utc": None,
            "version": "v3",
        },
    ),
]
