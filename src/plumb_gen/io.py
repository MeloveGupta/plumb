"""TRD §3.2 -- dataset/ is the engine's only data argument, and
BACKEND_SCHEMA.md §2 says its actual content is the three heterogeneous
transactional source files, not a generic canonical export. Replaces
P0.6's write_dataset (a canonical per-entity JSON dump) -- that was an
explicitly flagged stand-in until this task existed; nothing reads it
once dataset/ holds the real three files, so it's retired rather than
kept alongside.

sellers.csv joins those three as of the intent.csv-gap fix: a seller
master/reference file, not per-order, closing the seller_id<->name and
rate-card-sourcing gaps intent.py's own ingest found had no path into
the engine at all.
"""

import csv
import json
from pathlib import Path

from plumb_gen.sources import (
    BANK_CSV_COLUMNS,
    INTENT_CSV_COLUMNS,
    SELLERS_CSV_COLUMNS,
    bank_csv_rows,
    intent_csv_rows,
    razorpay_json_payload,
    sellers_csv_rows,
)
from plumb_gen.world import World


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_sources(world: World, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "sellers.csv", SELLERS_CSV_COLUMNS, sellers_csv_rows(world))
    _write_csv(out_dir / "intent.csv", INTENT_CSV_COLUMNS, intent_csv_rows(world))
    (out_dir / "razorpay.json").write_text(
        json.dumps(razorpay_json_payload(world), indent=2, sort_keys=True) + "\n"
    )
    _write_csv(out_dir / "bank.csv", BANK_CSV_COLUMNS, bank_csv_rows(world))
