"""BACKEND_SCHEMA.md §2 -- intent.csv, rupees as decimal strings, IST
timestamps, seller names not ids. Platform DB export -- one row carries
both order-level facts (gross_amount, category, placed_at_ist, status,
is_interstate) and intent-level facts (expected_commission,
commission_rate_bps, expected_tcs, expected_tds). Nowhere else in any
of the three transactional sources does order-level ground truth
appear, and plumb.domain.models.Intent has no fields to hold the
order-level half -- normalise() returns [Order(...), Intent(...)] for
one raw line, using NormalResult.record's list-widened type (see
normalise.py's module docstring for the full reasoning).

TWO KNOWN GAPS this adapter originally flagged:

1. seller_id, resolved (mostly). sellers.csv (the seller master file)
   now supplies the seller_name<->seller_id mapping intent.csv itself
   never carried. __init__ takes an injected seller_lookup: dict[str,
   list[str]] (name -> candidate ids), built once by the pipeline from
   the sellers adapter's output *before* intent.csv is read -- an
   explicit ordering requirement, not a suggestion (see pipeline.py).
   normalise() stays pure with respect to this: the lookup is fixed at
   construction, never mutated mid-run, so the same raw + the same
   constructed adapter always give the same result.

   Real seller directories collide on display name (sellers.csv
   deliberately has one), so resolution has three honest outcomes, each
   its own transform_log rule_id -- never a silent guess:
     - exactly one candidate  -> resolved (rule_id "seller_name_resolved")
     - zero candidates        -> unresolved, name not in sellers.csv at
                                  all (rule_id "seller_name_not_found")
     - two or more candidates -> a genuine collision; seller_id stays
                                  the raw name rather than arbitrarily
                                  picking one (rule_id
                                  "seller_name_ambiguous", candidate ids
                                  listed in after_text) -- disambiguating
                                  this needs cross-source matching
                                  (P1.5+), not single-record ingest.

2. Intent.expected_seller_amount_paise's true formula (world.py) is
   gross - commission - MDR, but MDR depends on the payment method,
   which isn't known at intent.csv's own row -- intent.csv carries no
   MDR/fee column at all. Computed here as gross - commission only, the
   best available approximation from this source alone, flagged with
   its own transform_log entry (rule_id
   "expected_seller_amount_approximated_no_mdr"). Confirmed against
   PRD §6/TRD §6.2/LLD §5.1 that D01 (the only check whose recompute
   formula is fully spec'd) needs only the commission rate, never this
   field or MDR -- so this approximation is a documented limitation,
   not a blocker, and is staying as-is.
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Literal

from plumb.domain.keys import IdSequence
from plumb.domain.models import Intent, Order
from plumb.ingest.normalise import NormalResult, RawRecord, Transform, derive_canonical_id, paise_from_rupee_string

IST_OFFSET = timedelta(hours=5, minutes=30)


def _ist_to_utc(ist_str: str) -> str:
    naive = datetime.strptime(ist_str, "%Y-%m-%d %H:%M:%S")
    utc = naive - IST_OFFSET
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_seller_id(seller_name: str, seller_lookup: dict[str, list[str]]) -> tuple[str, Transform]:
    candidates = seller_lookup.get(seller_name, [])
    if len(candidates) == 1:
        return candidates[0], Transform("seller_name", seller_name, candidates[0], "seller_name_resolved")
    if len(candidates) == 0:
        return seller_name, Transform("seller_name", seller_name, None, "seller_name_not_found")
    return seller_name, Transform("seller_name", seller_name, ",".join(candidates), "seller_name_ambiguous")


class IntentAdapter:
    source_id: Literal["intent"] = "intent"
    source_tz: str = "Asia/Kolkata"
    amount_unit: Literal["rupee_string"] = "rupee_string"

    def __init__(self, seller_lookup: dict[str, list[str]] | None = None) -> None:
        self._ids = IdSequence()
        self._seller_lookup = seller_lookup or {}

    def read(self, path: Path) -> Iterator[RawRecord]:
        with path.open(newline="") as f:
            for line_no, row in enumerate(csv.DictReader(f), start=1):
                yield RawRecord(
                    raw_id=self._ids.next("raw_intent"),
                    source_id="intent",
                    line_no=line_no,
                    raw_payload=dict(row),
                )

    def normalise(self, raw: RawRecord) -> NormalResult:
        payload = raw.raw_payload
        transforms: list[Transform] = []

        try:
            gross_paise = paise_from_rupee_string(payload["gross_amount"])
            transforms.append(Transform("gross_amount", payload["gross_amount"], str(gross_paise), "rupee_to_paise"))

            placed_at_utc = _ist_to_utc(payload["placed_at_ist"])
            transforms.append(Transform("placed_at_ist", payload["placed_at_ist"], placed_at_utc, "ist_to_utc"))

            is_interstate = payload["is_interstate"] == "Y"
            transforms.append(Transform("is_interstate", payload["is_interstate"], str(is_interstate), "y_n_to_bool"))

            seller_id, seller_transform = _resolve_seller_id(payload["seller_name"], self._seller_lookup)
            transforms.append(seller_transform)

            expected_commission_paise = paise_from_rupee_string(payload["expected_commission"])
            transforms.append(
                Transform("expected_commission", payload["expected_commission"], str(expected_commission_paise), "rupee_to_paise")
            )
            expected_tcs_paise = paise_from_rupee_string(payload["expected_tcs"])
            transforms.append(Transform("expected_tcs", payload["expected_tcs"], str(expected_tcs_paise), "rupee_to_paise"))
            expected_tds_paise = paise_from_rupee_string(payload["expected_tds"])
            transforms.append(Transform("expected_tds", payload["expected_tds"], str(expected_tds_paise), "rupee_to_paise"))

            commission_rate_bps = int(payload["commission_rate_bps"])
        except (KeyError, ValueError) as exc:
            return NormalResult(record=None, transforms=transforms, quarantine_reason=f"malformed intent row: {exc}")

        order = Order(
            order_id=payload["order_id"],
            seller_id=seller_id,
            gross_paise=gross_paise,
            category=payload["category"],
            placed_at_utc=placed_at_utc,
            status=payload["status"],
            is_interstate=is_interstate,
        )
        expected_seller_amount_paise = gross_paise - expected_commission_paise
        transforms.append(
            Transform(
                "expected_seller_amount", None, str(expected_seller_amount_paise),
                "expected_seller_amount_approximated_no_mdr",
            )
        )

        intent = Intent(
            intent_id=derive_canonical_id(raw.raw_id, "int"),
            order_id=payload["order_id"],
            seller_id=seller_id,
            expected_seller_amount_paise=expected_seller_amount_paise,
            expected_commission_paise=expected_commission_paise,
            commission_rate_applied_bps=commission_rate_bps,
            expected_tcs_paise=expected_tcs_paise,
            expected_tds_paise=expected_tds_paise,
            rate_card_version=payload["rate_card_version"],
        )
        return NormalResult(record=[order, intent], transforms=transforms, quarantine_reason=None)
