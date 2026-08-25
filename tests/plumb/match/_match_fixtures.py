"""Hand-buildable chain fixtures shared by test_passes.py and
test_engine.py -- one order's worth of intent/razorpay/bank records with
sensible defaults, so a test only has to override what it's actually
exercising.
"""

from plumb.domain.models import BankCredit, Intent, Order, Payment, SettlementRecon, Transfer
from plumb.match.engine import RecordSet


def _order(n, amount=100_000):
    return Order(
        order_id=f"ord_{n:05d}", seller_id="sel_00001", gross_paise=amount,
        category="electronics", placed_at_utc="2026-07-01T00:00:00Z", status="captured", is_interstate=False,
    )


def _intent(n, order_n, amount=98_000):
    return Intent(
        intent_id=f"int_{n:05d}", order_id=f"ord_{order_n:05d}", seller_id="sel_00001",
        expected_seller_amount_paise=amount, expected_commission_paise=2_000,
        commission_rate_applied_bps=200, expected_tcs_paise=0, expected_tds_paise=0,
        rate_card_version="v1",
    )


def _payment(n, order_n, amount=100_000):
    return Payment(
        payment_id=f"pay_{n:05d}", order_id=f"ord_{order_n:05d}", amount_paise=amount,
        method="upi", status="captured", captured_at_utc="2026-07-01T00:00:00Z", fee_paise=0, tax_paise=0,
    )


def _transfer(n, payment_n, amount=98_000):
    return Transfer(
        transfer_id=f"txfr_{n:05d}", payment_id=f"pay_{payment_n:05d}", linked_account_id="acc_X",
        amount_paise=amount, on_hold=False, settled_at_utc="2026-07-03T00:00:00Z",
    )


def _recon(n, transfer_n, settlement_id, utr, credit_paise=98_000, settled_at="2026-07-05T00:00:00Z"):
    return SettlementRecon(
        settlement_recon_id=f"setl_{n:05d}", entity_key=f"txfr_{transfer_n:05d}", entity_type="transfer",
        settlement_id=settlement_id, utr=utr, amount_paise=credit_paise, fee_paise=0, tax_paise=0,
        debit_paise=0, credit_paise=credit_paise, settled_at_utc=settled_at,
    )


def _bank_credit(n, amount, credited_on="2026-07-05", utr=None, bank_ref="RB1"):
    return BankCredit(
        bank_credit_id=f"bank_{n:05d}", bank_ref=bank_ref, utr=utr, amount_paise=amount,
        credited_on=credited_on, narration="UTR:X" if utr else "unparseable text",
    )


def _record_set(*records):
    by_key, side_by_key = {}, {}
    sides = {
        Order: "intent", Intent: "intent", Payment: "razorpay", Transfer: "razorpay",
        SettlementRecon: "razorpay", BankCredit: "bank",
    }
    field_for = {
        Order: "order_id", Intent: "intent_id", Payment: "payment_id", Transfer: "transfer_id",
        SettlementRecon: "settlement_recon_id", BankCredit: "bank_credit_id",
    }
    for r in records:
        key = getattr(r, field_for[type(r)])
        by_key[key] = r
        side_by_key[key] = sides[type(r)]
    return RecordSet(by_key=by_key, side_by_key=side_by_key)
