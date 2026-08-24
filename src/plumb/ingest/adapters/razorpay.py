"""BACKEND_SCHEMA.md §2 -- razorpay.json, paise already, Unix epoch
timestamps, id fields with their own pay_/txfr_/... prefixes.

One physical file, six logical entity streams (payments, transfers,
refunds, reversals, disputes, settlements) -- read() yields one
RawRecord per array entry across all six, in the file's own fixed array
order (never dict iteration, rule 7), tagged with which entity kind it
is so normalise() knows which canonical model to construct.

Every entity here already carries its own "id" field straight from the
source -- a real Razorpay API response's "id" *is* the entity's
identity. normalise() reuses it directly rather than deriving a new
one; nothing here needs derive_canonical_id (that's only for bank.csv/
intent.csv, where the source genuinely has no pre-existing id for the
entity being constructed).
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Literal

from plumb.domain.keys import IdSequence
from plumb.domain.models import Dispute, Payment, Refund, Reversal, SettlementRecon, Transfer
from plumb.ingest.normalise import CanonicalRecord, NormalResult, RawRecord, Transform

_ARRAYS = ("payments", "transfers", "refunds", "reversals", "disputes", "settlements")


def _utc_from_epoch(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_transform(field: str, epoch: int | None, transforms: list[Transform]) -> str | None:
    if epoch is None:
        return None
    utc = _utc_from_epoch(epoch)
    transforms.append(Transform(field, str(epoch), utc, "epoch_to_utc"))
    return utc


def _normalise_payment(payload: dict, transforms: list[Transform]) -> Payment:
    captured_at_utc = _epoch_transform("captured_at", payload["captured_at"], transforms)
    return Payment(
        payment_id=payload["id"],
        order_id=payload["order_id"],
        amount_paise=payload["amount"],
        method=payload["method"],
        status=payload["status"],
        captured_at_utc=captured_at_utc,
        fee_paise=payload["fee"],
        tax_paise=payload["tax"],
    )


def _normalise_transfer(payload: dict, transforms: list[Transform]) -> Transfer:
    on_hold_until_utc = _epoch_transform("on_hold_until", payload.get("on_hold_until"), transforms)
    settled_at_utc = _epoch_transform("settled_at", payload.get("settled_at"), transforms)
    return Transfer(
        transfer_id=payload["id"],
        payment_id=payload["payment_id"],
        linked_account_id=payload["recipient"],
        amount_paise=payload["amount"],
        on_hold=payload["on_hold"],
        on_hold_until_utc=on_hold_until_utc,
        settled_at_utc=settled_at_utc,
    )


def _normalise_refund(payload: dict, transforms: list[Transform]) -> Refund:
    created_at_utc = _epoch_transform("created_at", payload["created_at"], transforms)
    return Refund(
        refund_id=payload["id"],
        payment_id=payload["payment_id"],
        amount_paise=payload["amount"],
        created_at_utc=created_at_utc,
    )


def _normalise_reversal(payload: dict, transforms: list[Transform]) -> Reversal:
    created_at_utc = _epoch_transform("created_at", payload["created_at"], transforms)
    return Reversal(
        reversal_id=payload["id"],
        transfer_id=payload["transfer_id"],
        amount_paise=payload["amount"],
        created_at_utc=created_at_utc,
    )


def _normalise_dispute(payload: dict, _transforms: list[Transform]) -> Dispute:
    return Dispute(
        dispute_id=payload["id"],
        payment_id=payload["payment_id"],
        amount_paise=payload["amount"],
        status=payload["status"],
        deducted_amount_paise=payload["deducted_amount"],
    )


def _normalise_settlement(payload: dict, transforms: list[Transform]) -> SettlementRecon:
    settled_at_utc = _epoch_transform("settled_at", payload["settled_at"], transforms)
    return SettlementRecon(
        settlement_recon_id=payload["id"],
        entity_key=payload["entity_id"],
        entity_type=payload["entity_type"],
        settlement_id=payload["settlement_id"],
        utr=payload["utr"],
        amount_paise=payload["amount"],
        fee_paise=payload["fee"],
        tax_paise=payload["tax"],
        debit_paise=payload["debit"],
        credit_paise=payload["credit"],
        settled_at_utc=settled_at_utc,
        dispute_key=payload["dispute_id"],
    )


_NORMALISERS = {
    "payment": _normalise_payment,
    "transfer": _normalise_transfer,
    "refund": _normalise_refund,
    "reversal": _normalise_reversal,
    "dispute": _normalise_dispute,
    "settlement": _normalise_settlement,
}


class RazorpayAdapter:
    source_id: Literal["razorpay"] = "razorpay"
    source_tz: str = "UTC"
    amount_unit: Literal["paise_int"] = "paise_int"

    def __init__(self) -> None:
        self._ids = IdSequence()

    def read(self, path: Path) -> Iterator[RawRecord]:
        payload = json.loads(path.read_text())
        line_no = 0
        for array_name in _ARRAYS:  # fixed order, never dict iteration -- rule 7
            for entry in payload.get(array_name, []):
                line_no += 1
                kind = array_name[:-1]  # "payments" -> "payment"
                yield RawRecord(
                    raw_id=self._ids.next("raw_razorpay"),
                    source_id="razorpay",
                    line_no=line_no,
                    raw_payload={"_kind": kind, **entry},
                )

    def normalise(self, raw: RawRecord) -> NormalResult:
        payload = dict(raw.raw_payload)
        kind = payload.pop("_kind")
        transforms: list[Transform] = []

        normaliser = _NORMALISERS.get(kind)
        if normaliser is None:
            return NormalResult(record=None, transforms=[], quarantine_reason=f"unknown razorpay entity kind: {kind!r}")

        try:
            record: CanonicalRecord = normaliser(payload, transforms)
        except (KeyError, ValueError, TypeError) as exc:
            return NormalResult(record=None, transforms=transforms, quarantine_reason=f"malformed {kind} row: {exc}")

        return NormalResult(record=record, transforms=transforms, quarantine_reason=None)
