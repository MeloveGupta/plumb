"""Orchestration seam: reads one source file end to end and writes its
full provenance chain (source_file, raw_record, transform_log,
quarantine) into run.sqlite.

ingest/ importing store is legal (store <- all layers) -- this is the
one place that crossing happens. Adapters themselves (read()/
normalise()) stay pure, untouched by any I/O concern, per LLD §3.1's
own framing.
"""

import hashlib
from pathlib import Path

from plumb.domain.keys import IdSequence
from plumb.domain.models import Seller
from plumb.ingest.adapters.bank import BankAdapter
from plumb.ingest.adapters.intent import IntentAdapter
from plumb.ingest.adapters.razorpay import RazorpayAdapter
from plumb.ingest.adapters.sellers import SellersAdapter
from plumb.ingest.normalise import CanonicalRecord, RawRecord, SourceAdapter
from plumb.store.writer import write_quarantine, write_raw_record, write_source_file, write_transform_log


def run_adapter(adapter: SourceAdapter, path: Path, conn, ids: IdSequence) -> dict:
    """Returns {"total": n, "normalised": n, "quarantined": n, "records": [...]}.

    "records" is every successfully normalised canonical record,
    flattened (a NormalResult.record that was itself a list -- Order+
    Intent, Seller+SellerRateCard -- contributes each element
    separately). Callers that need to use what got normalised, not just
    count it (run_ingest's seller lookup, below), read this instead of
    re-parsing the file a second time.
    """
    raw_bytes = path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    raw_records: list[RawRecord] = list(adapter.read(path))
    source_file_id = write_source_file(
        conn,
        ids,
        source_id=adapter.source_id,
        path=str(path),
        sha256=sha256,
        byte_size=len(raw_bytes),
        row_count=len(raw_records),
        file_format=path.suffix.lstrip("."),
    )

    normalised = 0
    quarantined = 0
    records: list[CanonicalRecord] = []
    for raw in raw_records:
        write_raw_record(conn, raw.raw_id, source_file_id, raw.line_no, raw.raw_payload)

        result = adapter.normalise(raw)
        transform_tuples = [(t.field, t.before_text, t.after_text, t.rule_id) for t in result.transforms]
        if transform_tuples:
            write_transform_log(conn, ids, raw.raw_id, transform_tuples)

        if result.record is None:
            write_quarantine(conn, raw.raw_id, "normalise_failed", result.quarantine_reason or "unknown reason")
            quarantined += 1
        else:
            normalised += 1
            if isinstance(result.record, list):
                records.extend(result.record)
            else:
                records.append(result.record)

    return {"total": len(raw_records), "normalised": normalised, "quarantined": quarantined, "records": records}


def run_ingest(
    sellers_path: Path, intent_path: Path, razorpay_path: Path, bank_path: Path, conn, ids: IdSequence
) -> dict:
    """Runs all four adapters in the one order that matters: sellers.csv
    must be read before intent.csv, since intent's seller_id resolution
    needs sellers.csv's name->id lookup already built -- an ordering
    requirement, not a style preference. razorpay/bank have no such
    dependency; run after for one unambiguous sequence rather than
    leaving the order to call-site discretion.
    """
    sellers_summary = run_adapter(SellersAdapter(), sellers_path, conn, ids)

    seller_lookup: dict[str, list[str]] = {}
    for record in sellers_summary["records"]:
        if isinstance(record, Seller):
            seller_lookup.setdefault(record.seller_name, []).append(record.seller_id)

    intent_summary = run_adapter(IntentAdapter(seller_lookup=seller_lookup), intent_path, conn, ids)
    razorpay_summary = run_adapter(RazorpayAdapter(), razorpay_path, conn, ids)
    bank_summary = run_adapter(BankAdapter(), bank_path, conn, ids)

    return {
        "sellers": sellers_summary,
        "intent": intent_summary,
        "razorpay": razorpay_summary,
        "bank": bank_summary,
    }
