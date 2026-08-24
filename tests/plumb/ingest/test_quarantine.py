"""Quarantine path (P1.4): bad rows counted with a reason, never
dropped. The generator never produces malformed data (that's the whole
point of a generator with a known-good schema), so these are
hand-crafted, not drawn from a real batch -- the one place in this
session's ingest tests where that's the right call rather than a
shortcut.
"""

import csv
import json

from plumb.ingest.adapters.bank import BankAdapter
from plumb.ingest.adapters.intent import IntentAdapter
from plumb.ingest.adapters.razorpay import RazorpayAdapter
from plumb.ingest.normalise import RawRecord
from plumb.ingest.pipeline import run_adapter
from plumb.domain.keys import IdSequence
from plumb.store.ddl import open_run_db


def test_bank_adapter_quarantines_unparseable_value_date():
    adapter = BankAdapter()
    raw = RawRecord(
        raw_id="raw_bank_00001", source_id="bank", line_no=1,
        raw_payload={"bank_ref": "RB1", "credit": "100.00", "debit": "", "value_date": "not-a-date", "narration": "X"},
    )
    result = adapter.normalise(raw)
    assert result.record is None
    assert result.quarantine_reason is not None
    assert "value_date" in result.quarantine_reason
    # the transform computed before the failure (credit) is still returned --
    # inspectable evidence, not thrown away just because the row quarantined.
    assert any(t.field == "credit" for t in result.transforms)


def test_intent_adapter_quarantines_unparseable_amount():
    adapter = IntentAdapter()
    raw = RawRecord(
        raw_id="raw_intent_00001", source_id="intent", line_no=1,
        raw_payload={
            "order_id": "ord_00001", "seller_name": "Acme", "category": "electronics",
            "gross_amount": "not-a-number", "taxable_value": "0.00", "gst_amount": "0.00",
            "placed_at_ist": "2026-01-01 10:00:00", "status": "completed", "is_interstate": "N",
            "expected_commission": "0.00", "commission_rate_bps": "250",
            "expected_tcs": "0.00", "expected_tds": "0.00", "rate_card_version": "v1",
        },
    )
    result = adapter.normalise(raw)
    assert result.record is None
    assert result.quarantine_reason is not None


def test_intent_adapter_quarantines_a_missing_required_field():
    adapter = IntentAdapter()
    raw = RawRecord(
        raw_id="raw_intent_00001", source_id="intent", line_no=1,
        raw_payload={"order_id": "ord_00001"},  # everything else missing
    )
    result = adapter.normalise(raw)
    assert result.record is None
    assert result.quarantine_reason is not None


def test_razorpay_adapter_quarantines_an_unknown_entity_kind():
    adapter = RazorpayAdapter()
    raw = RawRecord(
        raw_id="raw_razorpay_00001", source_id="razorpay", line_no=1,
        raw_payload={"_kind": "not_a_real_kind", "id": "xyz_00001"},
    )
    result = adapter.normalise(raw)
    assert result.record is None
    assert "not_a_real_kind" in result.quarantine_reason


def test_razorpay_adapter_quarantines_a_payment_missing_a_required_field():
    adapter = RazorpayAdapter()
    raw = RawRecord(
        raw_id="raw_razorpay_00001", source_id="razorpay", line_no=1,
        raw_payload={"_kind": "payment", "id": "pay_00001"},  # amount/method/etc missing
    )
    result = adapter.normalise(raw)
    assert result.record is None
    assert result.quarantine_reason is not None


def test_quarantined_rows_are_counted_and_never_dropped(tmp_path):
    # A hand-crafted bank.csv with one good row and one malformed row --
    # both must still be present in raw_record, and the quarantine count
    # must reflect exactly the bad one.
    path = tmp_path / "bank.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["bank_ref", "credit", "debit", "value_date", "narration"])
        writer.writeheader()
        writer.writerow({"bank_ref": "RB1", "credit": "100.00", "debit": "", "value_date": "2026-01-01", "narration": "UTR:ABCDEFGHIJKLMNO SETTLEMENT"})
        writer.writerow({"bank_ref": "RB2", "credit": "not-a-number", "debit": "", "value_date": "2026-01-01", "narration": "X"})

    conn = open_run_db(":memory:")
    ids = IdSequence()
    summary = run_adapter(BankAdapter(), path, conn, ids)

    assert summary["total"] == 2
    assert summary["normalised"] == 1
    assert summary["quarantined"] == 1
    # never dropped: both rows are still in raw_record
    assert conn.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 1
    reason = conn.execute("SELECT reason_code, detail FROM quarantine").fetchone()
    assert reason[0] == "normalise_failed"
    assert "credit" in reason[1]
    conn.close()
