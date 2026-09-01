"""Hand-buildable fixtures for tests/plumb/agent/*.py.

Same per-directory pattern as tests/plumb/verify/_verify_fixtures.py and
tests/plumb/match/_match_fixtures.py (pytest's prepend import mode makes
a `_*.py` helper importable only from tests in its own directory, so the
small builders are duplicated rather than shared). Only the records the
L3 layer actually reads are here.
"""

from plumb.domain.models import (
    BankCredit,
    Dispute,
    Intent,
    Order,
    Payment,
    Refund,
    Reversal,
    Seller,
    SellerRateCard,
    SettlementRecon,
    Transfer,
)


def order(n, amount=100_000, seller_id="sel_00001", category="electronics", placed_at="2026-07-01T00:00:00Z"):
    return Order(
        order_id=f"ord_{n:05d}", seller_id=seller_id, gross_paise=amount, category=category,
        placed_at_utc=placed_at, status="captured", is_interstate=False,
    )


def intent(n, order_n, commission_bps=1500, seller_id="sel_00001", amount=98_000, tcs_paise=0, tds_paise=0):
    return Intent(
        intent_id=f"int_{n:05d}", order_id=f"ord_{order_n:05d}", seller_id=seller_id,
        expected_seller_amount_paise=amount, expected_commission_paise=0,
        commission_rate_applied_bps=commission_bps, expected_tcs_paise=tcs_paise, expected_tds_paise=tds_paise,
        rate_card_version="v1",
    )


def payment(n, order_n, amount=100_000, fee_paise=0, tax_paise=0, method="upi"):
    return Payment(
        payment_id=f"pay_{n:05d}", order_id=f"ord_{order_n:05d}", amount_paise=amount, method=method,
        status="captured", captured_at_utc="2026-07-01T00:00:00Z", fee_paise=fee_paise, tax_paise=tax_paise,
    )


def transfer(n, payment_n, amount=98_000, on_hold=False, on_hold_until=None, settled_at="2026-07-03T00:00:00Z"):
    return Transfer(
        transfer_id=f"txfr_{n:05d}", payment_id=f"pay_{payment_n:05d}", linked_account_id="acc_X",
        amount_paise=amount, on_hold=on_hold, on_hold_until_utc=on_hold_until, settled_at_utc=settled_at,
    )


def refund(n, payment_n, amount, created_at="2026-07-02T00:00:00Z"):
    return Refund(refund_id=f"rfnd_{n:05d}", payment_id=f"pay_{payment_n:05d}", amount_paise=amount, created_at_utc=created_at)


def reversal(n, transfer_n, amount, created_at="2026-07-06T00:00:00Z"):
    return Reversal(reversal_id=f"rvsl_{n:05d}", transfer_id=f"txfr_{transfer_n:05d}", amount_paise=amount, created_at_utc=created_at)


def dispute(n, payment_n, deducted_amount, gross=100_000, status="resolved"):
    return Dispute(
        dispute_id=f"disp_{n:05d}", payment_id=f"pay_{payment_n:05d}", amount_paise=gross, status=status,
        deducted_amount_paise=deducted_amount,
    )


def recon(n, transfer_n, settlement_id="stlbatch_2026-07-05", utr="UTR000001", credit_paise=98_000,
          debit_paise=0, settled_at="2026-07-05T00:00:00Z"):
    return SettlementRecon(
        settlement_recon_id=f"setl_{n:05d}", entity_key=f"txfr_{transfer_n:05d}", entity_type="transfer",
        settlement_id=settlement_id, utr=utr, amount_paise=credit_paise, fee_paise=0, tax_paise=0,
        debit_paise=debit_paise, credit_paise=credit_paise, settled_at_utc=settled_at,
    )


def bank_credit(n, amount, credited_on="2026-07-05", utr=None, bank_ref="RB1", narration=None):
    return BankCredit(
        bank_credit_id=f"bank_{n:05d}", bank_ref=bank_ref, utr=utr, amount_paise=amount,
        credited_on=credited_on, narration=narration or ("UTR:X" if utr else "unparseable text"),
    )


def seller(seller_id="sel_00001", name="Acme", category="electronics"):
    return Seller(seller_id=seller_id, seller_name=name, category=category)


def rate_card(n, seller_id="sel_00001", category="electronics", commission_bps=1500,
              effective_from="2024-01-01", effective_to=None, version="v1"):
    return SellerRateCard(
        rate_card_id=f"rate_{n:05d}", seller_id=seller_id, category=category, commission_bps=commission_bps,
        effective_from=effective_from, effective_to=effective_to, version=version,
    )


def ingest_result(intent_records=(), razorpay_records=(), bank_records=(), sellers_records=()):
    return {
        "sellers": {"records": list(sellers_records)},
        "intent": {"records": list(intent_records)},
        "razorpay": {"records": list(razorpay_records)},
        "bank": {"records": list(bank_records)},
    }
