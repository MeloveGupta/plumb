"""LLD §8's score_match calls truth.counterpart_closure(group.anchor_key)
without saying what anchor_key is -- the matcher that will supply it
(P1) doesn't exist yet, and could plausibly anchor a match on any leg
(payment, transfer, settlement_recon, bank_credit), not necessarily the
order's own record_key. TruthStore is built as a symmetric reverse
index instead of an order-keyed lookup: every key that belongs to a
truth closure -- the order itself and every one of its true
counterparts -- maps to the SAME closure set, so counterpart_closure
works no matter which member the future matcher picks as its anchor.

The closure itself is leg-only (true_counterparts, never including the
order's own record_key). match_member.side is constrained to
('intent','razorpay','bank') -- the three raw source files -- and an
order is never independently ingested as its own raw record with a
"side"; it's the grouping key, synthesized during ingest from its
legs, not one of them. So a real match_group's members can only ever
be leg keys (payment/transfer/settlement_recon/bank_credit), never the
order's own key -- counterpart_closure has to return the leg-only set
regardless of which key (order or leg) was used to look it up, or a
correct match_group's members could never equal it. Caught by hand-
computing the first fixture, not by inspection.

A key found in neither position is fabrication (TRD §8.3): the engine
claimed a record_key that ground truth never heard of.
"""

import json
import sqlite3
from dataclasses import dataclass

from plumb_eval.errors import TruthJoinError


@dataclass(frozen=True)
class TruthStore:
    _closure_by_key: dict[str, frozenset[str]]
    _order_key_by_member: dict[str, str]
    _obligation_by_key: dict[str, dict[str, int]]
    _resolvable_by_key: dict[str, bool]
    _defects_by_key: dict[str, list[dict]]

    @classmethod
    def from_db(cls, conn: sqlite3.Connection) -> "TruthStore":
        closure_by_key: dict[str, frozenset[str]] = {}
        order_key_by_member: dict[str, str] = {}
        obligation_by_key: dict[str, dict[str, int]] = {}
        resolvable_by_key: dict[str, bool] = {}

        rows = conn.execute(
            "SELECT record_key, true_counterparts_json, true_obligation_json, "
            "resolvable_from_available_data FROM truth_record"
        ).fetchall()
        for record_key, counterparts_json, obligation_json, resolvable in rows:
            counterparts = json.loads(counterparts_json)
            closure = frozenset(counterparts)  # leg-only -- never includes record_key itself

            closure_by_key[record_key] = closure
            order_key_by_member[record_key] = record_key
            for leg in counterparts:
                closure_by_key[leg] = closure
                order_key_by_member[leg] = record_key

            obligation_by_key[record_key] = json.loads(obligation_json)
            resolvable_by_key[record_key] = bool(resolvable)

        defects_by_key: dict[str, list[dict]] = {}
        for instance_id, record_key, defect_class, amount_at_risk_paise, within_tolerance, params_json in (
            conn.execute(
                "SELECT instance_id, record_key, defect_class, amount_at_risk_paise, "
                "within_tolerance, params_json FROM injected_defect"
            ).fetchall()
        ):
            defects_by_key.setdefault(record_key, []).append(
                {
                    "instance_id": instance_id,
                    "record_key": record_key,
                    "defect_class": defect_class,
                    "amount_at_risk_paise": amount_at_risk_paise,
                    "within_tolerance": bool(within_tolerance),
                    "params": json.loads(params_json),
                }
            )

        return cls(closure_by_key, order_key_by_member, obligation_by_key, resolvable_by_key, defects_by_key)

    def counterpart_closure(self, key: str) -> frozenset[str]:
        try:
            return self._closure_by_key[key]
        except KeyError:
            raise TruthJoinError(f"record_key {key!r} resolves to no truth closure") from None

    def order_key_for(self, key: str) -> str:
        """The order-level record_key for whichever closure `key` belongs
        to -- `key` may already be the order key, or one of its legs.
        """
        try:
            return self._order_key_by_member[key]
        except KeyError:
            raise TruthJoinError(f"record_key {key!r} resolves to no truth closure") from None

    def order_keys(self) -> list[str]:
        """Every order (truth_record.record_key), not every closure member."""
        return list(self._obligation_by_key)

    def true_obligation(self, order_key: str) -> dict[str, int]:
        return self._obligation_by_key[order_key]

    def is_resolvable(self, order_key: str) -> bool:
        return self._resolvable_by_key[order_key]

    def defects_for(self, order_key: str) -> list[dict]:
        return self._defects_by_key.get(order_key, [])

    def all_defects(self) -> list[dict]:
        return [d for defects in self._defects_by_key.values() for d in defects]
