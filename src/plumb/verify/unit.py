"""LLD §5.1 -- SettlementUnit and the builder that assembles it.

`Completeness` and `SettlementUnit` are transcribed from LLD §5.1 exactly.
The builder itself has no pseudocode in any spec (`build_units` is named
nowhere) -- its join logic and the `_classify` rule below are grounded in
reading match/passes.py's own FK edges (`_join_pairs`) and
plumb_gen/world.py's actual generation logic, not invented; see the
inline notes at each decision point.

`RecordSet.from_ingest` (match/engine.py) tags every record "intent"/
"razorpay"/"bank" but never merges Payment/Transfer/Refund/Reversal/
Dispute/SettlementRecon into one joined object -- the builder walks the
same FK chain the matcher's own `_join_pairs` walks
(Order.order_id == Intent.order_id == Payment.order_id;
Payment.payment_id == Transfer/Refund/Dispute.payment_id;
Transfer.transfer_id == Reversal.transfer_id ==
SettlementRecon.entity_key where entity_type == "transfer") to gather
each order's full entity lists, independent of match output.

`BankCredit` is the one entity with no FK back into this chain at all
(confirmed: domain/models.py's BankCredit carries only bank_ref/utr/
amount_paise/credited_on/narration) -- so `unit.bank_credit` can only
come from the match result, never from a join.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from plumb.domain.keys import IdSequence, RecordKey
from plumb.domain.models import (
    BankCredit,
    Dispute,
    Intent,
    Order,
    OrderLine,
    Payment,
    Refund,
    Reversal,
    SellerRateCard,
    SettlementRecon,
    Transfer,
)
from plumb.match.engine import MatchResult, RecordSet


class Completeness(StrEnum):
    FULL = "full"  # intent + razorpay + bank
    MISSING_BANK = "missing_bank"
    MISSING_SETTLEMENT = "missing_settlement"
    INTENT_ONLY = "intent_only"


@dataclass(frozen=True)
class SettlementUnit:
    unit_id: str
    completeness: Completeness
    order: Order
    lines: list[OrderLine]
    intent: Intent
    payments: list[Payment]
    refunds: list[Refund]
    transfers: list[Transfer]
    reversals: list[Reversal]
    disputes: list[Dispute]
    recon_rows: list[SettlementRecon]
    bank_credit: BankCredit | None
    rate_card: SellerRateCard | None
    match_id: str | None


def _classify(
    payments: list[Payment], bank_credit: BankCredit | None, recon_rows: list[SettlementRecon]
) -> Completeness:
    """Confirmed against plumb_gen/world.py:443-479, not guessed: a
    SettlementRecon and a BankCredit are created in the same `if
    settled_at is not None:` block -- both exist, or neither does. So
    `recon_rows` empty means the transfer never settled at all (on hold,
    or past batch_as_of) -- MISSING_SETTLEMENT. `recon_rows` present but
    `bank_credit is None` can only happen because the *matcher* failed to
    attach an existing bank credit to this order's identity chain (LLD
    §4.1's pending-group mechanism) -- BankCredit has no FK, so the
    matcher's own output is the only way to see this distinction at all.
    That is MISSING_BANK, including the T2 in-flight case: a genuinely
    partial, utr=None bank credit still exists in bank.csv, but fails
    every matcher pass (no utr edge, amount far outside any exact or
    tolerance-band comparison) and never attaches.
    """
    if not payments:
        return Completeness.INTENT_ONLY
    if bank_credit is not None:
        return Completeness.FULL
    if recon_rows:
        return Completeness.MISSING_BANK
    return Completeness.MISSING_SETTLEMENT


def _resolve_rate_card(
    seller_id: str, category: str, placed_at_utc: str, sellers_records: list
) -> SellerRateCard | None:
    """As-of lookup by seller+category against every SellerRateCard the
    sellers.csv adapter produced (SellerRateCard is not one of
    RecordSet's three matchable sides -- it never appears there at all,
    per RecordSet.from_ingest's own docstring -- so it has to be read
    straight from ingest_result["sellers"]["records"]).

    Today's generator emits exactly one card per seller
    (rate_card_version hardcoded "v1" in plumb_gen/world.py), so this is
    a no-op against real fixtures -- built correctly anyway, since a real
    seller could be repriced mid-period and D01 exists to catch exactly
    that.
    """
    as_of = date.fromisoformat(placed_at_utc[:10])
    candidates = [
        rc
        for rc in sellers_records
        if isinstance(rc, SellerRateCard)
        and rc.seller_id == seller_id
        and rc.category == category
        and date.fromisoformat(rc.effective_from) <= as_of
        and (rc.effective_to is None or as_of <= date.fromisoformat(rc.effective_to))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda rc: rc.effective_from)


def build_units(
    ingest_result: dict, match_result: MatchResult, match_ids: dict[int, str], ids: IdSequence
) -> list[SettlementUnit]:
    """`match_ids` is the {index into match_result.groups: match_id} dict
    `match.engine.persist()` already returns when writing to a real
    run.sqlite connection -- pass that straight through; build one by
    hand only in a pure unit test with no DB connection.
    """
    records = RecordSet.from_ingest(ingest_result)
    sellers_records = list(ingest_result["sellers"]["records"])

    intent_by_order: dict[str, Intent] = {}
    payments_by_order: dict[str, list[Payment]] = {}
    refunds_by_payment: dict[str, list[Refund]] = {}
    transfers_by_payment: dict[str, list[Transfer]] = {}
    reversals_by_transfer: dict[str, list[Reversal]] = {}
    disputes_by_payment: dict[str, list[Dispute]] = {}
    recon_by_transfer: dict[str, list[SettlementRecon]] = {}

    for key in records.all_keys():  # dict insertion order -- deterministic, not a set (rule 7)
        rec = records.get(key)
        if isinstance(rec, Intent):
            intent_by_order[rec.order_id] = rec
        elif isinstance(rec, Payment):
            payments_by_order.setdefault(rec.order_id, []).append(rec)
        elif isinstance(rec, Refund):
            refunds_by_payment.setdefault(rec.payment_id, []).append(rec)
        elif isinstance(rec, Transfer):
            transfers_by_payment.setdefault(rec.payment_id, []).append(rec)
        elif isinstance(rec, Reversal):
            reversals_by_transfer.setdefault(rec.transfer_id, []).append(rec)
        elif isinstance(rec, Dispute):
            disputes_by_payment.setdefault(rec.payment_id, []).append(rec)
        elif isinstance(rec, SettlementRecon) and rec.entity_type == "transfer" and rec.entity_key is not None:
            recon_by_transfer.setdefault(rec.entity_key, []).append(rec)

    group_index_by_order: dict[str, int] = {}
    for index, group in enumerate(match_result.groups):
        for member_key, _side in group.members:
            member = records.get(member_key)
            if isinstance(member, Order):
                group_index_by_order[member.order_id] = index

    unmatched = frozenset(match_result.unmatched)  # membership test only, never iterated (rule 7)

    units: list[SettlementUnit] = []
    for key in records.all_keys():
        order = records.get(key)
        if not isinstance(order, Order):
            continue
        order_key = order.order_id

        intent = intent_by_order.get(order_key)
        if intent is None:
            # intent.py's own adapter returns [Order, Intent] from one raw
            # line, never one without the other -- an Order with no paired
            # Intent means that invariant broke upstream. Fail loudly
            # rather than silently emit a half-built unit.
            raise AssertionError(f"order {order_key} has no paired intent -- ingest invariant violated")

        payments = payments_by_order.get(order_key, [])
        refunds = [r for p in payments for r in refunds_by_payment.get(p.payment_id, [])]
        transfers = [t for p in payments for t in transfers_by_payment.get(p.payment_id, [])]
        reversals = [rv for t in transfers for rv in reversals_by_transfer.get(t.transfer_id, [])]
        disputes = [d for p in payments for d in disputes_by_payment.get(p.payment_id, [])]
        recon_rows = [r for t in transfers for r in recon_by_transfer.get(t.transfer_id, [])]

        if order_key in group_index_by_order:
            index = group_index_by_order[order_key]
            group = match_result.groups[index]
            match_id = match_ids[index]
            # `members` is sorted by build_group, so this pick is
            # deterministic. A group can legitimately carry more than one
            # bank leg -- T2's n:1 batching/1:n splitting means several
            # orders can share one bank credit, or one order's settlement
            # can span several -- but SettlementUnit.bank_credit is
            # singular per LLD §5.1.
            #
            # CLOSED, not deferred: audited every one of D03-D08's actual
            # field needs (P2.5 review). D03/D04/D05 read recon_rows/
            # refunds/disputes/order/intent plus a RateBook lookup -- never
            # bank_credit. D06 is Transfer-scoped only (an orphaned hold
            # has no bank leg yet, by definition). D07 is Reversal vs
            # Refund. D08 ("sum of GST-on-fee across the settlement file
            # != the period tax invoice", PRD §6) is a batch-wide
            # aggregate against one external figure, and the GST-on-fee
            # data itself lives on Payment.tax_paise/SettlementRecon.
            # tax_paise (already plural list fields here) -- BankCredit
            # carries no fee/tax field at all, so it was never a candidate
            # source for D08 either. No defect in the fixed 8-class
            # taxonomy (CLAUDE.md rule 5) ever dereferences bank_credit's
            # value for a money computation -- it feeds only _classify()
            # below, for Completeness (presence/absence). "First sorted
            # bank leg" is correct and permanent for that purpose; this
            # field does not need widening to a list.
            bank_keys = [k for k, side in group.members if side == "bank"]
            bank_credit = records.get(bank_keys[0]) if bank_keys else None
        elif order_key in unmatched:
            bank_credit = None
            match_id = None
        else:
            raise AssertionError(f"order {order_key} neither grouped nor unmatched -- matcher invariant violated")

        completeness = _classify(payments, bank_credit, recon_rows)
        rate_card = _resolve_rate_card(order.seller_id, order.category, order.placed_at_utc, sellers_records)

        units.append(
            SettlementUnit(
                unit_id=ids.next("unit"),
                completeness=completeness,
                order=order,
                lines=[],  # no adapter emits OrderLine yet (ingest/normalise.py) -- unread by D01/D02
                intent=intent,
                payments=payments,
                refunds=refunds,
                transfers=transfers,
                reversals=reversals,
                disputes=disputes,
                recon_rows=recon_rows,
                bank_credit=bank_credit,
                rate_card=rate_card,
                match_id=match_id,
            )
        )
    return units
