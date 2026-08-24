"""Each adapter against real plumb-gen output, not hand-written rows --
declares its own source_tz/amount_unit, and normalise() is pure (same
input -> same output, called twice).
"""

from pathlib import Path

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
from plumb.ingest.adapters.bank import BankAdapter
from plumb.ingest.adapters.intent import IntentAdapter
from plumb.ingest.adapters.razorpay import RazorpayAdapter
from plumb.ingest.adapters.sellers import SellersAdapter
from plumb_gen.config import GeneratorConfig
from plumb_gen.fixtures import SELLER_COUNT
from plumb_gen.io import write_sources
from plumb_gen.world import build_world


def _write_real_batch(tmp_path: Path, seed: int = 42, batch_size: int = 50) -> Path:
    world = build_world(GeneratorConfig(seed=seed, batch_id="batch_test", batch_size=batch_size))
    out_dir = tmp_path / "dataset"
    write_sources(world, out_dir)
    return out_dir


def test_bank_adapter_declares_its_own_vocabulary():
    adapter = BankAdapter()
    assert adapter.source_id == "bank"
    assert adapter.source_tz == "Asia/Kolkata"
    assert adapter.amount_unit == "rupee_string"


def test_bank_adapter_normalises_every_row_against_real_data(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = BankAdapter()
    raw_records = list(adapter.read(dataset_dir / "bank.csv"))
    assert raw_records  # not vacuously testing zero rows

    for raw in raw_records:
        result = adapter.normalise(raw)
        assert result.record is not None, result.quarantine_reason
        assert result.quarantine_reason is None
        assert isinstance(result.record, BankCredit)
        # credited_on stays a bare date -- no fabricated time-of-day.
        assert result.record.credited_on == raw.raw_payload["value_date"]
        # every field touched gets a transform, in order: credit, value_date, narration
        fields_touched = [t.field for t in result.transforms]
        assert fields_touched == ["credit", "value_date", "narration"]


def test_bank_adapter_normalise_is_pure(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = BankAdapter()
    raw = next(adapter.read(dataset_dir / "bank.csv"))
    first = adapter.normalise(raw)
    second = adapter.normalise(raw)
    assert first.record == second.record
    assert first.transforms == second.transforms


def test_bank_adapter_date_only_converts_to_ist_midnight_utc(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = BankAdapter()
    raw = next(adapter.read(dataset_dir / "bank.csv"))
    result = adapter.normalise(raw)

    date_transform = next(t for t in result.transforms if t.field == "value_date")
    assert date_transform.rule_id == "date_only_ist_midnight"
    assert date_transform.before_text == raw.raw_payload["value_date"]
    # Hand-computed: date D at IST midnight = UTC (D-1) 18:30:00.
    year, month, day = (int(p) for p in date_transform.before_text.split("-"))
    from datetime import date, timedelta

    expected_utc_date = date(year, month, day) - timedelta(days=1)
    assert date_transform.after_text == f"{expected_utc_date.isoformat()}T18:30:00Z"


def test_bank_adapter_quarantines_unparseable_credit_amount():
    from plumb.ingest.normalise import RawRecord

    adapter = BankAdapter()
    raw = RawRecord(
        raw_id="raw_bank_00001",
        source_id="bank",
        line_no=1,
        raw_payload={"bank_ref": "RB1", "credit": "not-a-number", "debit": "", "value_date": "2026-01-01", "narration": "X"},
    )
    result = adapter.normalise(raw)
    assert result.record is None
    assert result.quarantine_reason is not None
    assert "credit" in result.quarantine_reason


def test_razorpay_adapter_declares_its_own_vocabulary():
    adapter = RazorpayAdapter()
    assert adapter.source_id == "razorpay"
    assert adapter.source_tz == "UTC"
    assert adapter.amount_unit == "paise_int"


_KIND_TO_MODEL = {
    "payment": Payment,
    "transfer": Transfer,
    "refund": Refund,
    "reversal": Reversal,
    "dispute": Dispute,
    "settlement": SettlementRecon,
}


def test_razorpay_adapter_normalises_every_row_against_real_data(tmp_path):
    # dispute_rate_bps bumped well above the 200 (2%) default -- disputes
    # are otherwise too rare to reliably exercise all six arrays in one
    # batch regardless of seed.
    world = build_world(GeneratorConfig(seed=42, batch_id="batch_test", batch_size=200, dispute_rate_bps=3000))
    dataset_dir = tmp_path / "dataset"
    write_sources(world, dataset_dir)
    adapter = RazorpayAdapter()
    raw_records = list(adapter.read(dataset_dir / "razorpay.json"))
    assert raw_records  # not vacuously testing zero rows

    seen_kinds: set[str] = set()
    for raw in raw_records:
        kind = raw.raw_payload["_kind"]
        seen_kinds.add(kind)
        result = adapter.normalise(raw)
        assert result.record is not None, result.quarantine_reason
        assert result.quarantine_reason is None
        assert isinstance(result.record, _KIND_TO_MODEL[kind])

    # all six arrays in razorpay.json actually got exercised, not just some
    assert seen_kinds == {"payment", "transfer", "refund", "reversal", "dispute", "settlement"}


def test_razorpay_adapter_settlement_carries_utr(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = RazorpayAdapter()
    settlement_raws = [r for r in adapter.read(dataset_dir / "razorpay.json") if r.raw_payload["_kind"] == "settlement"]
    assert settlement_raws
    for raw in settlement_raws:
        result = adapter.normalise(raw)
        assert result.record.utr  # non-empty -- Razorpay always states its own reference


def test_razorpay_adapter_normalise_is_pure(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = RazorpayAdapter()
    raw = next(adapter.read(dataset_dir / "razorpay.json"))
    first = adapter.normalise(raw)
    second = adapter.normalise(raw)
    assert first.record == second.record
    assert first.transforms == second.transforms


def test_razorpay_adapter_epoch_converts_to_utc(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = RazorpayAdapter()
    payment_raw = next(r for r in adapter.read(dataset_dir / "razorpay.json") if r.raw_payload["_kind"] == "payment")
    result = adapter.normalise(payment_raw)

    epoch = payment_raw.raw_payload["captured_at"]
    transform = next(t for t in result.transforms if t.field == "captured_at")
    assert transform.rule_id == "epoch_to_utc"
    assert transform.before_text == str(epoch)
    # Hand-computed: epoch seconds -> UTC ISO string via the same
    # calendar.timegm-inverse conversion the generator itself used.
    from datetime import UTC, datetime

    expected = datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert transform.after_text == expected
    assert result.record.captured_at_utc == expected


def test_razorpay_adapter_reuses_the_sources_own_id_not_a_derived_one(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = RazorpayAdapter()
    payment_raw = next(r for r in adapter.read(dataset_dir / "razorpay.json") if r.raw_payload["_kind"] == "payment")
    result = adapter.normalise(payment_raw)
    assert result.record.payment_id == payment_raw.raw_payload["id"]


def test_intent_adapter_declares_its_own_vocabulary():
    adapter = IntentAdapter()
    assert adapter.source_id == "intent"
    assert adapter.source_tz == "Asia/Kolkata"
    assert adapter.amount_unit == "rupee_string"


def test_intent_adapter_produces_an_order_and_an_intent_per_row(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = IntentAdapter()
    raw_records = list(adapter.read(dataset_dir / "intent.csv"))
    assert raw_records  # not vacuously testing zero rows

    for raw in raw_records:
        result = adapter.normalise(raw)
        assert result.quarantine_reason is None, result.quarantine_reason
        assert isinstance(result.record, list)
        assert len(result.record) == 2
        order, intent = result.record
        assert isinstance(order, Order)
        assert isinstance(intent, Intent)
        # order_id is reused directly from the source, not derived --
        # intent.csv already carries it.
        assert order.order_id == raw.raw_payload["order_id"]
        assert intent.order_id == raw.raw_payload["order_id"]
        # intent_id has no source field, so it IS derived.
        assert intent.intent_id != raw.raw_id


def test_intent_adapter_normalise_is_pure(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = IntentAdapter()
    raw = next(adapter.read(dataset_dir / "intent.csv"))
    first = adapter.normalise(raw)
    second = adapter.normalise(raw)
    assert first.record == second.record
    assert first.transforms == second.transforms


def test_intent_adapter_ist_converts_to_utc(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = IntentAdapter()
    raw = next(adapter.read(dataset_dir / "intent.csv"))
    result = adapter.normalise(raw)

    ist_transform = next(t for t in result.transforms if t.field == "placed_at_ist")
    assert ist_transform.rule_id == "ist_to_utc"
    # Hand-computed: IST is UTC+5:30, so subtract 5:30 from the naive
    # IST wall-clock time to get the UTC instant.
    from datetime import datetime, timedelta

    ist_dt = datetime.strptime(ist_transform.before_text, "%Y-%m-%d %H:%M:%S")
    expected_utc = (ist_dt - timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert ist_transform.after_text == expected_utc
    order, _intent = result.record
    assert order.placed_at_utc == expected_utc


def test_intent_adapter_y_n_converts_to_bool(tmp_path):
    dataset_dir = _write_real_batch(tmp_path, batch_size=200)  # ensure both Y and N appear
    adapter = IntentAdapter()
    seen_values: set[bool] = set()
    for raw in adapter.read(dataset_dir / "intent.csv"):
        result = adapter.normalise(raw)
        order, _intent = result.record
        assert isinstance(order.is_interstate, bool)
        assert order.is_interstate == (raw.raw_payload["is_interstate"] == "Y")
        seen_values.add(order.is_interstate)
    assert seen_values == {True, False}


def _seller_lookup_from_real_sellers_csv(dataset_dir: Path) -> dict[str, list[str]]:
    import csv as csv_module

    lookup: dict[str, list[str]] = {}
    with (dataset_dir / "sellers.csv").open(newline="") as f:
        for row in csv_module.DictReader(f):
            lookup.setdefault(row["seller_name"], []).append(row["seller_id"])
    return lookup


def test_intent_adapter_with_no_lookup_reports_seller_name_not_found(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = IntentAdapter()  # no seller_lookup at all
    raw = next(adapter.read(dataset_dir / "intent.csv"))
    result = adapter.normalise(raw)

    seller_transform = next(t for t in result.transforms if t.field == "seller_name")
    assert seller_transform.rule_id == "seller_name_not_found"
    order, intent = result.record
    assert order.seller_id == raw.raw_payload["seller_name"]
    assert intent.seller_id == raw.raw_payload["seller_name"]


def test_intent_adapter_resolves_seller_id_via_real_sellers_csv(tmp_path):
    dataset_dir = _write_real_batch(tmp_path, batch_size=200)
    seller_lookup = _seller_lookup_from_real_sellers_csv(dataset_dir)
    adapter = IntentAdapter(seller_lookup=seller_lookup)

    outcomes: dict[str, int] = {}
    for raw in adapter.read(dataset_dir / "intent.csv"):
        result = adapter.normalise(raw)
        seller_transform = next(t for t in result.transforms if t.field == "seller_name")
        outcomes[seller_transform.rule_id] = outcomes.get(seller_transform.rule_id, 0) + 1

        order, intent = result.record
        if seller_transform.rule_id == "seller_name_resolved":
            assert order.seller_id == seller_transform.after_text
            assert order.seller_id != raw.raw_payload["seller_name"]
        elif seller_transform.rule_id == "seller_name_ambiguous":
            # never arbitrarily pick one -- seller_id stays the raw name.
            assert order.seller_id == raw.raw_payload["seller_name"]
            candidates = seller_transform.after_text.split(",")
            assert len(candidates) >= 2

    # "Sharma Electronics" (sel_00001, sel_00011) makes this batch's
    # collision real, not hypothetical -- confirms both outcomes actually
    # fire against real generated data, not just a hand-built fixture.
    assert outcomes.get("seller_name_resolved", 0) > 0
    assert outcomes.get("seller_name_ambiguous", 0) > 0
    assert outcomes.get("seller_name_not_found", 0) == 0  # every real name is in sellers.csv


def test_intent_adapter_seller_name_ambiguous_lists_both_candidates(tmp_path):
    lookup = {"Sharma Electronics": ["sel_00001", "sel_00011"]}
    adapter = IntentAdapter(seller_lookup=lookup)
    from plumb.ingest.normalise import RawRecord

    raw = RawRecord(
        raw_id="raw_intent_00001", source_id="intent", line_no=1,
        raw_payload={
            "order_id": "ord_00001", "seller_name": "Sharma Electronics", "category": "electronics",
            "gross_amount": "1000.00", "taxable_value": "847.46", "gst_amount": "152.54",
            "placed_at_ist": "2026-01-01 10:00:00", "status": "completed", "is_interstate": "N",
            "expected_commission": "150.00", "commission_rate_bps": "1500",
            "expected_tcs": "5.00", "expected_tds": "1.00", "rate_card_version": "v1",
        },
    )
    result = adapter.normalise(raw)
    order, _intent = result.record
    assert order.seller_id == "Sharma Electronics"  # unresolved, not guessed
    seller_transform = next(t for t in result.transforms if t.field == "seller_name")
    assert seller_transform.rule_id == "seller_name_ambiguous"
    assert set(seller_transform.after_text.split(",")) == {"sel_00001", "sel_00011"}


def test_sellers_adapter_declares_its_own_vocabulary():
    adapter = SellersAdapter()
    assert adapter.source_id == "sellers"
    assert adapter.source_tz == "Asia/Kolkata"
    assert adapter.amount_unit == "not_applicable"


def test_sellers_adapter_produces_a_seller_and_a_rate_card_per_row(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = SellersAdapter()
    raw_records = list(adapter.read(dataset_dir / "sellers.csv"))
    assert len(raw_records) == SELLER_COUNT

    for raw in raw_records:
        result = adapter.normalise(raw)
        assert result.quarantine_reason is None, result.quarantine_reason
        assert isinstance(result.record, list)
        assert len(result.record) == 2
        seller, rate_card = result.record
        assert isinstance(seller, Seller)
        assert isinstance(rate_card, SellerRateCard)
        assert seller.seller_id == raw.raw_payload["seller_id"]
        assert rate_card.seller_id == raw.raw_payload["seller_id"]
        assert rate_card.commission_bps == int(raw.raw_payload["commission_bps"])


def test_sellers_adapter_normalise_is_pure(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = SellersAdapter()
    raw = next(adapter.read(dataset_dir / "sellers.csv"))
    first = adapter.normalise(raw)
    second = adapter.normalise(raw)
    assert first.record == second.record
    assert first.transforms == second.transforms


def test_sellers_adapter_empty_effective_to_becomes_none(tmp_path):
    dataset_dir = _write_real_batch(tmp_path)
    adapter = SellersAdapter()
    raw = next(adapter.read(dataset_dir / "sellers.csv"))
    result = adapter.normalise(raw)
    assert raw.raw_payload["effective_to"] == ""  # generator never sets one today
    _seller, rate_card = result.record
    assert rate_card.effective_to is None
