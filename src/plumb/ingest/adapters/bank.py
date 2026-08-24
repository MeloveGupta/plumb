"""BACKEND_SCHEMA.md §2 -- bank.csv, date-only, no time, UTR buried in
free-text narration.

Date-only -> UTC instant: bank.csv is an India-side CSV artifact, same
as intent.csv (BACKEND_SCHEMA §2's own framing), so this adapter
declares source_tz="Asia/Kolkata" like intent's -- razorpay.json (API,
epoch) is the only source with a real claim to "UTC". A date-only value
converts to a UTC instant as IST midnight of that calendar date (date D
-> UTC (D-1) 18:30:00), the standard "a date is the start of that day"
reading. This conversion is captured only as a transform_log entry
(rule_id "date_only_ist_midnight") -- BankCredit.credited_on itself
stays exactly the date it already was. A prior session deliberately
removed a credited_at_utc field from this model: the SQL schema's own
comment says "the bank gives no time," so inventing a fake instant on
the canonical record itself would misrepresent the source's actual
precision. The transform log is where the derived UTC anchor lives,
inspectable, not silently promoted into a false-precision field.
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Literal

from plumb.domain.keys import IdSequence
from plumb.domain.models import BankCredit
from plumb.ingest.narration import extract_utr
from plumb.ingest.normalise import NormalResult, RawRecord, Transform, derive_canonical_id

IST_OFFSET = timedelta(hours=5, minutes=30)


def _paise_from_rupee_string(rupee_string: str) -> int:
    cleaned = rupee_string.replace(",", "")
    rupees_str, _, paise_str = cleaned.partition(".")
    rupees = int(rupees_str)
    paise = int(paise_str.ljust(2, "0")[:2]) if paise_str else 0
    return rupees * 100 + paise


def _ist_midnight_to_utc(date_str: str) -> str:
    ist_midnight = datetime.strptime(date_str, "%Y-%m-%d")
    utc_instant = ist_midnight - IST_OFFSET
    return utc_instant.strftime("%Y-%m-%dT%H:%M:%SZ")


class BankAdapter:
    source_id: Literal["bank"] = "bank"
    source_tz: str = "Asia/Kolkata"
    amount_unit: Literal["rupee_string"] = "rupee_string"

    def __init__(self) -> None:
        self._ids = IdSequence()

    def read(self, path: Path) -> Iterator[RawRecord]:
        with path.open(newline="") as f:
            for line_no, row in enumerate(csv.DictReader(f), start=1):
                yield RawRecord(
                    raw_id=self._ids.next("raw_bank"),
                    source_id="bank",
                    line_no=line_no,
                    raw_payload=dict(row),
                )

    def normalise(self, raw: RawRecord) -> NormalResult:
        payload = raw.raw_payload
        transforms: list[Transform] = []

        bank_ref = payload.get("bank_ref", "")
        credit_str = payload.get("credit", "")
        value_date = payload.get("value_date", "")
        narration = payload.get("narration", "")

        try:
            amount_paise = _paise_from_rupee_string(credit_str)
        except (ValueError, AttributeError):
            return NormalResult(
                record=None, transforms=transforms,
                quarantine_reason=f"unparseable credit amount: {credit_str!r}",
            )
        transforms.append(Transform("credit", credit_str, str(amount_paise), "rupee_to_paise"))

        try:
            credited_at_utc = _ist_midnight_to_utc(value_date)
        except ValueError:
            return NormalResult(
                record=None, transforms=transforms,
                quarantine_reason=f"unparseable value_date: {value_date!r}",
            )
        transforms.append(Transform("value_date", value_date, credited_at_utc, "date_only_ist_midnight"))

        utr, _confidence, pattern_name = extract_utr(narration)
        transforms.append(Transform("narration", narration, utr, pattern_name))

        record = BankCredit(
            bank_credit_id=derive_canonical_id(raw.raw_id, "bank"),
            bank_ref=bank_ref,
            utr=utr,
            amount_paise=amount_paise,
            credited_on=value_date,
            narration=narration,
        )
        return NormalResult(record=record, transforms=transforms, quarantine_reason=None)
