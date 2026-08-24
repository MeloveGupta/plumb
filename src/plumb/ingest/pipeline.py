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
from plumb.ingest.normalise import RawRecord, SourceAdapter
from plumb.store.writer import write_quarantine, write_raw_record, write_source_file, write_transform_log


def run_adapter(adapter: SourceAdapter, path: Path, conn, ids: IdSequence) -> dict:
    """Returns {"total": n, "normalised": n, "quarantined": n}."""
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

    return {"total": len(raw_records), "normalised": normalised, "quarantined": quarantined}
