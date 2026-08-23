"""Canonical JSON dump of the generated world, for byte-identical testing
today. This is NOT yet the three genuinely heterogeneous per-source
formats (CSV-rupees-IST / JSON-paise-epoch / CSV-narration) -- that's
P0.7's job. One canonical file per entity, sorted keys, stable formatting,
written to {out_dir}/dataset per TRD §3.2's path convention.
"""

import json
from pathlib import Path

from plumb_gen.world import World

_ENTITY_FILES = (
    ("seller_rate_cards", "seller_rate_card.json"),
    ("orders", "order.json"),
    ("order_lines", "order_line.json"),
    ("intents", "intent.json"),
    ("payments", "payment.json"),
    ("refunds", "refund.json"),
    ("transfers", "transfer.json"),
    ("reversals", "reversal.json"),
    ("disputes", "dispute.json"),
    ("settlement_recons", "settlement_recon.json"),
    ("bank_credits", "bank_credit.json"),
)


def write_dataset(world: World, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for attr, filename in _ENTITY_FILES:
        records = [record.model_dump(mode="json") for record in getattr(world, attr)]
        text = json.dumps(records, indent=2, sort_keys=True) + "\n"
        (out_dir / filename).write_text(text)
