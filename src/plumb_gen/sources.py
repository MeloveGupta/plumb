"""BACKEND_SCHEMA.md §2 -- the three heterogeneous source shapes.

No float anywhere in these conversions. Rupee strings are built from
integer divmod + Python's int ",\" format spec, never paise/100 as a
float. Unix epoch uses calendar.timegm on a parsed UTC datetime, not
.timestamp() (which returns float).
"""

import calendar
from datetime import UTC, datetime, timedelta

from plumb_gen.fixtures import SELLER_NAMES
from plumb_gen.world import World

IST_OFFSET = timedelta(hours=5, minutes=30)


def _parse_utc(iso_z: str) -> datetime:
    return datetime.strptime(iso_z, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _rupee_string(paise: int) -> str:
    rupees, remainder_paise = divmod(paise, 100)
    return f"{rupees:,}.{remainder_paise:02d}"


def _ist_string(iso_z: str) -> str:
    dt = _parse_utc(iso_z) + IST_OFFSET
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _epoch_seconds(iso_z: str) -> int:
    return calendar.timegm(_parse_utc(iso_z).timetuple())


def _seller_name(seller_id: str) -> str:
    index = int(seller_id.split("_")[1]) - 1
    return SELLER_NAMES[index]


def intent_csv_rows(world: World) -> list[dict]:
    lines_by_order = {line.order_id: line for line in world.order_lines}
    intents_by_order = {intent.order_id: intent for intent in world.intents}
    rows = []
    for order in world.orders:
        line = lines_by_order[order.order_id]
        intent = intents_by_order[order.order_id]
        rows.append(
            {
                "order_id": order.order_id,
                "seller_name": _seller_name(order.seller_id),
                "category": order.category,
                "gross_amount": _rupee_string(order.gross_paise),
                "taxable_value": _rupee_string(line.taxable_paise),
                "gst_amount": _rupee_string(line.gst_paise),
                "placed_at_ist": _ist_string(order.placed_at_utc),
                "status": order.status,
                "is_interstate": "Y" if order.is_interstate else "N",
                "expected_commission": _rupee_string(intent.expected_commission_paise),
                "commission_rate_bps": str(intent.commission_rate_applied_bps),
                "expected_tcs": _rupee_string(intent.expected_tcs_paise),
                "expected_tds": _rupee_string(intent.expected_tds_paise),
                "rate_card_version": intent.rate_card_version,
            }
        )
    return rows


INTENT_CSV_COLUMNS = [
    "order_id",
    "seller_name",
    "category",
    "gross_amount",
    "taxable_value",
    "gst_amount",
    "placed_at_ist",
    "status",
    "is_interstate",
    "expected_commission",
    "commission_rate_bps",
    "expected_tcs",
    "expected_tds",
    "rate_card_version",
]


def razorpay_json_payload(world: World) -> dict:
    return {
        "payments": [
            {
                "id": p.payment_id,
                "order_id": p.order_id,
                "amount": p.amount_paise,
                "currency": "INR",
                "method": p.method,
                "status": p.status,
                "captured_at": _epoch_seconds(p.captured_at_utc),
                "fee": p.fee_paise,
                "tax": p.tax_paise,
            }
            for p in world.payments
        ],
        "transfers": [
            {
                "id": t.transfer_id,
                "payment_id": t.payment_id,
                "recipient": t.linked_account_id,
                "amount": t.amount_paise,
                "on_hold": t.on_hold,
                "on_hold_until": _epoch_seconds(t.on_hold_until_utc) if t.on_hold_until_utc else None,
                "settled_at": _epoch_seconds(t.settled_at_utc) if t.settled_at_utc else None,
            }
            for t in world.transfers
        ],
        "refunds": [
            {
                "id": r.refund_id,
                "payment_id": r.payment_id,
                "amount": r.amount_paise,
                "created_at": _epoch_seconds(r.created_at_utc),
            }
            for r in world.refunds
        ],
        "reversals": [
            {
                "id": rv.reversal_id,
                "transfer_id": rv.transfer_id,
                "amount": rv.amount_paise,
                "created_at": _epoch_seconds(rv.created_at_utc),
            }
            for rv in world.reversals
        ],
        "disputes": [
            {
                "id": d.dispute_id,
                "payment_id": d.payment_id,
                "amount": d.amount_paise,
                "status": d.status,
                "deducted_amount": d.deducted_amount_paise,
            }
            for d in world.disputes
        ],
        "settlements": [
            {
                "id": s.settlement_recon_id,
                "entity_id": s.entity_key,
                "entity_type": s.entity_type,
                "settlement_id": s.settlement_id,
                "utr": s.utr,
                "amount": s.amount_paise,
                "fee": s.fee_paise,
                "tax": s.tax_paise,
                "debit": s.debit_paise,
                "credit": s.credit_paise,
                "settled_at": _epoch_seconds(s.settled_at_utc),
                "dispute_id": s.dispute_key,
            }
            for s in world.settlement_recons
        ],
    }


def bank_csv_rows(world: World) -> list[dict]:
    # narration/utr are canonical fields, generated once in world.py so
    # settlement_recon.utr and bank_credit.utr/narration stay internally
    # consistent -- this just passes them through into the source shape.
    rows = []
    for bank_credit in world.bank_credits:
        rows.append(
            {
                "bank_ref": bank_credit.bank_ref,
                "credit": _rupee_string(bank_credit.amount_paise),
                "debit": "",
                "value_date": bank_credit.credited_on,
                "narration": bank_credit.narration,
            }
        )
    return rows


BANK_CSV_COLUMNS = ["bank_ref", "credit", "debit", "value_date", "narration"]
