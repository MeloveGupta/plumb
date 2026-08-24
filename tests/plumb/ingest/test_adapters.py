"""Each adapter against real plumb-gen output, not hand-written rows --
declares its own source_tz/amount_unit, and normalise() is pure (same
input -> same output, called twice).
"""

from pathlib import Path

from plumb.domain.models import BankCredit, Dispute, Payment, Refund, Reversal, SettlementRecon, Transfer
from plumb.ingest.adapters.bank import BankAdapter
from plumb.ingest.adapters.razorpay import RazorpayAdapter
from plumb_gen.config import GeneratorConfig
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
