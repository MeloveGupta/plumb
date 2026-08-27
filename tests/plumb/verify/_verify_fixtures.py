"""Hand-buildable fixtures shared by tests/plumb/verify/*.py -- one
order's worth of intent/razorpay/bank/sellers records with sensible
defaults, plus helpers to build the ingest_result dict and a hand-built
MatchResult, so a test only has to override what it's actually
exercising. Same pattern as tests/plumb/match/_match_fixtures.py.
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
from plumb.verify.trace import reevaluate_trace
from plumb.match.engine import MatchGroup, MatchResult

_RULE_ID = {"P0": "ID_CHAIN", "P1": "EXACT_COMPOSITE", "P2": "GROUP_SUBSET_SUM", "P3": "TOL_BAND"}
_CONFIDENCE_BPS = {"P0": 10_000, "P1": 9_500, "P2": 9_000, "P3": 7_000}


def order(n, amount=100_000, seller_id="sel_00001", category="electronics", placed_at="2026-07-01T00:00:00Z"):
    return Order(
        order_id=f"ord_{n:05d}", seller_id=seller_id, gross_paise=amount, category=category,
        placed_at_utc=placed_at, status="captured", is_interstate=False,
    )


def intent(n, order_n, commission_bps=1500, seller_id="sel_00001", tcs_paise=0, tds_paise=0, amount=98_000):
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


def refund(n, payment_n, amount, created_at="2026-07-02T00:00:00Z"):
    return Refund(refund_id=f"rfnd_{n:05d}", payment_id=f"pay_{payment_n:05d}", amount_paise=amount, created_at_utc=created_at)


def dispute(n, payment_n, deducted_amount, gross=100_000, status="resolved"):
    return Dispute(
        dispute_id=f"disp_{n:05d}", payment_id=f"pay_{payment_n:05d}", amount_paise=gross, status=status,
        deducted_amount_paise=deducted_amount,
    )


def reversal(n, transfer_n, amount, created_at="2026-07-06T00:00:00Z"):
    return Reversal(reversal_id=f"rvsl_{n:05d}", transfer_id=f"txfr_{transfer_n:05d}", amount_paise=amount, created_at_utc=created_at)


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


def match_group(pass_, members):
    """members: list of (record_key, side) tuples."""
    return MatchGroup(
        rule_id=_RULE_ID[pass_], pass_=pass_, confidence_bps=_CONFIDENCE_BPS[pass_],
        members=tuple(sorted(members)),
    )


def match_result(groups=(), unmatched=(), ambiguous=()):
    return MatchResult(groups=tuple(groups), unmatched=tuple(unmatched), ambiguous=tuple(ambiguous))


def assert_trace_reevaluates(finding):
    """P2.11/LLD §5.4 -- every step in a real Finding's trace must
    re-evaluate to its own recorded output_paise. Wired into each
    check's own "fires" test(s) so a check that produces a trace no
    evaluator can re-derive is caught immediately, not just described
    as a property in a docstring."""
    reevaluate_trace(finding.trace)
