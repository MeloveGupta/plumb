"""sellers.csv -- the seller master/reference file, not one of
BACKEND_SCHEMA §2's three transactional sources. Closes the gap
intent.py's ingest found: neither seller_id<->seller_name nor
SellerRateCard data has any path into the engine from
intent.csv/razorpay.json/bank.csv alone.

Same "platform DB export" framing as intent.csv (source_tz=
"Asia/Kolkata"), even though no timestamp here needs converting.
amount_unit is "not_applicable" -- commission_bps is a rate, not a
money amount, and forcing a "paise_int"/"rupee_string" declaration onto
a source with no money field at all would be a false claim rather than
a true one.

One raw row -> [Seller, SellerRateCard], the same "one line, two
canonical records" pattern intent.py already established for
Order+Intent -- seller_id is already present in the row, so
derive_canonical_id isn't needed here (unlike bank_credit_id/intent_id).
"""

import csv
from pathlib import Path
from typing import Iterator, Literal

from plumb.domain.keys import IdSequence
from plumb.domain.models import Seller, SellerRateCard
from plumb.ingest.normalise import NormalResult, RawRecord, Transform, derive_canonical_id


class SellersAdapter:
    source_id: Literal["sellers"] = "sellers"
    source_tz: str = "Asia/Kolkata"
    amount_unit: Literal["not_applicable"] = "not_applicable"

    def __init__(self) -> None:
        self._ids = IdSequence()

    def read(self, path: Path) -> Iterator[RawRecord]:
        with path.open(newline="") as f:
            for line_no, row in enumerate(csv.DictReader(f), start=1):
                yield RawRecord(
                    raw_id=self._ids.next("raw_sellers"),
                    source_id="sellers",
                    line_no=line_no,
                    raw_payload=dict(row),
                )

    def normalise(self, raw: RawRecord) -> NormalResult:
        payload = raw.raw_payload
        transforms: list[Transform] = []

        try:
            commission_bps = int(payload["commission_bps"])

            effective_to_raw = payload.get("effective_to", "")
            effective_to = effective_to_raw or None
            transforms.append(Transform("effective_to", effective_to_raw, effective_to, "empty_string_to_null"))

            seller = Seller(
                seller_id=payload["seller_id"],
                seller_name=payload["seller_name"],
                category=payload["category"],
            )
            rate_card = SellerRateCard(
                rate_card_id=derive_canonical_id(raw.raw_id, "rate"),
                seller_id=payload["seller_id"],
                category=payload["category"],
                commission_bps=commission_bps,
                effective_from=payload["effective_from"],
                effective_to=effective_to,
                version=payload["version"],
            )
        except (KeyError, ValueError) as exc:
            return NormalResult(record=None, transforms=transforms, quarantine_reason=f"malformed sellers row: {exc}")

        return NormalResult(record=[seller, rate_card], transforms=transforms, quarantine_reason=None)
