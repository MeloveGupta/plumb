"""P3 step 3 -- EvidenceStore lookups and RecordIndex membership.

The expected keys/counts here are read straight off the hand-built
fixtures below, not derived from EvidenceStore's own output.
"""

from _agent_fixtures import (
    bank_credit,
    dispute,
    ingest_result,
    intent,
    order,
    payment,
    rate_card,
    recon,
    refund,
    seller,
    transfer,
)

from plumb.agent.evidence import EvidenceStore, RecordIndex


def _batch():
    return ingest_result(
        intent_records=[order(1), intent(1, 1), order(2, seller_id="sel_00002"), intent(2, 2, seller_id="sel_00002")],
        razorpay_records=[
            payment(1, 1),
            payment(2, 2),
            transfer(1, 1),
            refund(1, 1, 5_000),
            refund(2, 1, 3_000),
            dispute(1, 2, 1_200),
            recon(1, 1, settled_at="2026-07-05T00:00:00Z"),
            recon(2, 1, settled_at="2026-07-06T00:00:00Z"),
        ],
        bank_records=[bank_credit(1, 98_000)],
        sellers_records=[
            seller("sel_00001"),
            seller("sel_00002"),
            rate_card(1, seller_id="sel_00001", effective_from="2024-01-01", effective_to="2026-06-30"),
            rate_card(2, seller_id="sel_00001", effective_from="2026-07-01"),
        ],
    )


def test_singular_lookups_hit_and_miss():
    store = EvidenceStore.from_ingest(_batch())
    assert store.payment("pay_00001").payment_id == "pay_00001"
    assert store.payment("pay_99999") is None
    assert store.transfer("txfr_00001").payment_id == "pay_00001"
    assert store.transfer("txfr_00009") is None
    assert store.dispute("disp_00001").deducted_amount_paise == 1_200
    assert store.dispute("disp_00009") is None


def test_refunds_for_payment_are_sorted_and_scoped():
    store = EvidenceStore.from_ingest(_batch())
    refunds = store.refunds_for_payment("pay_00001")
    assert [r.refund_id for r in refunds] == ["rfnd_00001", "rfnd_00002"]
    assert store.refunds_for_payment("pay_00002") == []


def test_settlement_recon_by_date():
    store = EvidenceStore.from_ingest(_batch())
    assert [r.settlement_recon_id for r in store.settlement_recon_on("2026-07-05")] == ["setl_00001"]
    assert [r.settlement_recon_id for r in store.settlement_recon_on("2026-07-06")] == ["setl_00002"]
    assert store.settlement_recon_on("2026-07-07") == []


def test_rate_cards_as_of_window():
    store = EvidenceStore.from_ingest(_batch())
    # 2026-06-15 falls in rate_00001's window (2024-01-01 .. 2026-06-30) only
    before = store.rate_cards_for("sel_00001", "2026-06-15")
    assert [rc.rate_card_id for rc in before] == ["rate_00001"]
    # 2026-07-15 falls in rate_00002's window (2026-07-01 .. open) only
    after = store.rate_cards_for("sel_00001", "2026-07-15")
    assert [rc.rate_card_id for rc in after] == ["rate_00002"]
    # a seller with no card
    assert store.rate_cards_for("sel_00002", "2026-07-15") == []


def test_intent_ledger_search_filters():
    store = EvidenceStore.from_ingest(_batch())
    assert [it.intent_id for it in store.intents(order_id="ord_00001", seller_id=None)] == ["int_00001"]
    assert [it.intent_id for it in store.intents(order_id=None, seller_id="sel_00002")] == ["int_00002"]
    assert [it.intent_id for it in store.intents(order_id=None, seller_id=None)] == ["int_00001", "int_00002"]
    assert store.intents(order_id="ord_00001", seller_id="sel_00002") == []


def test_has_seller_and_has_payment():
    store = EvidenceStore.from_ingest(_batch())
    assert store.has_seller("sel_00002") is True
    assert store.has_seller("sel_09999") is False
    assert store.has_payment("pay_00001") is True
    assert store.has_payment("pay_09999") is False


def test_record_index_covers_every_side():
    index = RecordIndex.from_ingest(_batch())
    # 4 intent-side + 8 razorpay-side + 1 bank + 4 sellers-side = 17
    assert len(index) == 17
    for key in ("ord_00001", "int_00002", "pay_00001", "txfr_00001", "rfnd_00002",
                "disp_00001", "setl_00002", "bank_00001", "rate_00002", "sel_00002"):
        assert key in index
    assert "pay_99999" not in index
