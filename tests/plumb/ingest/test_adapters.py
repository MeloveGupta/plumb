"""Each adapter against real plumb-gen output, not hand-written rows --
declares its own source_tz/amount_unit, and normalise() is pure (same
input -> same output, called twice).
"""

from pathlib import Path

from plumb.domain.models import BankCredit
from plumb.ingest.adapters.bank import BankAdapter
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
