"""TRD §8.1 -- the seeded world. Dependency order: sellers -> orders ->
order_lines -> intents -> payments -> transfers -> refunds -> reversals ->
disputes -> settlement_recons -> bank_credits. Every downstream amount is
computed from the upstream one, never independently re-rolled.

All randomness comes from the one Random instance created in build_world;
nothing here reads the system clock. Probability decisions use rng.randint
against a bps threshold (never rng.random()/rng.uniform() touching a paise
value) -- money stays int, full stop.

D06 avoidance in CLEAN data: on_hold=1 always comes with a real, non-null
on_hold_until_utc unless a defect assignment says otherwise. NULL +
on_hold=1 is created only by an explicit D06 assignment (P0.8).

Narration/utr generation (LLD §3.2 pattern variety, the unparseable case)
happens here too, not as a later transform in the source writers --
settlement_recon.utr and bank_credit.utr/narration must stay internally
consistent, which only works if they're assigned together at construction
time.

Defect injection (PRD §6, P0.8): _build_order takes an optional
DefectAssignment. Defect-assigned orders skip the normal probabilistic
refund/reversal/dispute/hold rolls entirely -- the assigned defect forces
whatever precondition it needs (D03/D04 force a partial refund; D06
forces an aged hold with no release date; D07 forces a reversal with no
refund), so no defect ever depends on random luck to be representable.
D01/D02/D05/D08 need no forced precondition -- they're otherwise-plain
settled orders with exactly one thing wrong, which is what keeps
attribution unambiguous (see the P0.8 plan's point 4).
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from random import Random

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
from plumb.domain.money import Paise, apply_bps
from plumb.domain.tolerance import DEFAULT_V1

from plumb_gen.config import GeneratorConfig
from plumb_gen.fixtures import (
    CATEGORIES,
    COMMISSION_BPS_BY_CATEGORY,
    GOODS_GST_BPS,
    MDR_BPS_BY_METHOD,
    SELLER_COUNT,
)
from plumb_gen.ids import IdSequence
from plumb_gen.injectors import (
    DefectAssignment,
    assign_defects,
    d01_wrong_commission_bps,
    d02_shortfall_paise,
    d05_wrong_tds_paise,
    d08_wrong_tax_paise,
)
from plumb_gen.narration import generate_settlement_reference
from plumb_gen.rates import GST_ON_FEES_BPS, TCS_BPS, TDS_BPS
from plumb_gen.truth import InjectedDefect, TruthRecord

METHODS = sorted(MDR_BPS_BY_METHOD)  # stable order for rng.choice -- never dict iteration order

# D05's wrong basis swaps TDS's rate onto the net/transfer amount instead of gross.
# D08's wrong GST rate -- a plausible mis-slab, not the correct 1800bps.
D08_WRONG_GST_BPS = 1200


@dataclass
class Seller:
    seller_id: str
    category: str
    commission_bps: int


@dataclass
class World:
    seller_rate_cards: list[SellerRateCard] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    order_lines: list[OrderLine] = field(default_factory=list)
    intents: list[Intent] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    refunds: list[Refund] = field(default_factory=list)
    transfers: list[Transfer] = field(default_factory=list)
    reversals: list[Reversal] = field(default_factory=list)
    disputes: list[Dispute] = field(default_factory=list)
    settlement_recons: list[SettlementRecon] = field(default_factory=list)
    bank_credits: list[BankCredit] = field(default_factory=list)
    truth_records: list[TruthRecord] = field(default_factory=list)
    injected_defects: list[InjectedDefect] = field(default_factory=list)


def _iso_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _roll(rng: Random, rate_bps: int) -> bool:
    return rng.randint(1, 10_000) <= rate_bps


def _batch_midnight(config: GeneratorConfig) -> datetime:
    d = config.batch_as_of
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _batch_end(config: GeneratorConfig) -> datetime:
    d = config.batch_as_of
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)


def _build_sellers(config: GeneratorConfig, rng: Random, ids: IdSequence, world: World) -> list[Seller]:
    sellers: list[Seller] = []
    effective_from = _batch_midnight(config) - timedelta(days=365)
    for i in range(1, SELLER_COUNT + 1):
        seller_id = f"sel_{i:05d}"
        category = rng.choice(CATEGORIES)
        commission_bps = COMMISSION_BPS_BY_CATEGORY[category]
        sellers.append(Seller(seller_id, category, commission_bps))
        world.seller_rate_cards.append(
            SellerRateCard(
                rate_card_id=ids.next("rate"),
                seller_id=seller_id,
                category=category,
                commission_bps=commission_bps,
                effective_from=_iso_date(effective_from),
                effective_to=None,
                version="v1",
            )
        )
    return sellers


def _build_order(
    config: GeneratorConfig,
    rng: Random,
    ids: IdSequence,
    world: World,
    seller: Seller,
    assignment: DefectAssignment | None,
) -> None:
    defect_id = assignment.defect_id if assignment else None

    gross_paise: Paise = rng.randint(50_000, 500_000)  # Rs 500 - Rs 5000

    # D06 wants an order clearly old enough to look "aged", not freshly
    # placed. Every other defect (and clean orders past the forced-clean
    # threshold below) just needs enough headroom to settle.
    if defect_id == "D06":
        min_age = min(config.hold_release_days + 14, config.order_lookback_days)
        days_ago = rng.randint(min_age, config.order_lookback_days)
    elif defect_id is not None:
        min_age = min(config.settlement_days + 5, config.order_lookback_days)
        days_ago = rng.randint(min_age, config.order_lookback_days)
    else:
        days_ago = rng.randint(1, config.order_lookback_days)

    placed_at = (_batch_midnight(config) - timedelta(days=days_ago)).replace(
        hour=rng.randint(0, 23), minute=rng.randint(0, 59), second=rng.randint(0, 59)
    )
    is_interstate = _roll(rng, config.interstate_rate_bps)

    order_id = ids.next("ord")
    world.orders.append(
        Order(
            order_id=order_id,
            seller_id=seller.seller_id,
            gross_paise=gross_paise,
            category=seller.category,
            placed_at_utc=_iso_datetime(placed_at),
            status="completed",
            is_interstate=is_interstate,
        )
    )

    # order_line: subtraction, not a second independent rounding, so the
    # two always sum to gross_paise exactly. Untouched by every defect --
    # none of D01-D08 concern the order's own tax-line composition.
    taxable_paise = (gross_paise * 10_000) // (10_000 + GOODS_GST_BPS)
    gst_paise = gross_paise - taxable_paise
    world.order_lines.append(
        OrderLine(
            line_id=ids.next("oln"),
            order_id=order_id,
            sku=f"SKU-{rng.randint(1000, 9999)}",
            taxable_paise=taxable_paise,
            gst_bps=GOODS_GST_BPS,
            gst_paise=gst_paise,
        )
    )

    # --- refund precondition, decided before intent so TCS's net-of-returns
    # basis (D04) can be computed correctly in the same pass ---
    force_refund = defect_id in ("D03", "D04")
    forced_refund_paise = 0
    if force_refund:
        forced_refund_paise = apply_bps(gross_paise, rng.randint(1_000, 4_000))  # 10-40% of gross

    net_of_returns_paise = gross_paise - forced_refund_paise

    # --- commission: wrong for D01, feeding both intent and transfer so
    # they can never drift apart from each other ---
    true_commission_bps = seller.commission_bps
    if defect_id == "D01":
        commission_bps_used = d01_wrong_commission_bps(
            rng, true_commission_bps, gross_paise, int(assignment.params["target_delta_paise"])
        )
    else:
        commission_bps_used = true_commission_bps
    commission_paise = apply_bps(gross_paise, commission_bps_used)
    true_commission_paise = apply_bps(gross_paise, true_commission_bps)

    true_tds_paise = apply_bps(gross_paise, TDS_BPS)  # always GROSS basis, PRD §5.1
    true_tcs_paise = apply_bps(net_of_returns_paise, TCS_BPS)  # PRD §5.2, accounts for any forced refund

    if defect_id == "D04":
        tcs_paise_used = apply_bps(gross_paise, TCS_BPS)  # wrong: gross basis, ignoring the forced refund
        d04_amount_at_risk = abs(tcs_paise_used - true_tcs_paise)
    else:
        tcs_paise_used = true_tcs_paise
        d04_amount_at_risk = 0

    if defect_id == "D08":
        # UPI has zero MDR (fixtures.py), which would make GST-on-MDR zero
        # regardless of rate -- a "wrong rate" applied to zero is still
        # zero, so a D08 instance on a UPI order would inject nothing.
        # Found by inspecting a real generated batch, not by inspection of
        # the code alone.
        non_zero_mdr_methods = [m for m in METHODS if MDR_BPS_BY_METHOD[m] > 0]
        method = non_zero_mdr_methods[rng.randrange(len(non_zero_mdr_methods))]
    else:
        method = METHODS[rng.randrange(len(METHODS))]
    mdr_paise = apply_bps(gross_paise, MDR_BPS_BY_METHOD[method])
    true_gst_on_mdr_paise = apply_bps(mdr_paise, GST_ON_FEES_BPS)

    if defect_id == "D05":
        # wrong basis: TDS computed on the net/transfer amount instead of gross
        transfer_amount_paise_true = gross_paise - commission_paise - mdr_paise
        tds_paise_used, d05_amount_at_risk = d05_wrong_tds_paise(true_tds_paise, transfer_amount_paise_true, TDS_BPS)
    else:
        tds_paise_used = true_tds_paise
        d05_amount_at_risk = 0

    if defect_id == "D08":
        tax_paise_used, d08_amount_at_risk = d08_wrong_tax_paise(true_gst_on_mdr_paise, mdr_paise, D08_WRONG_GST_BPS)
    else:
        tax_paise_used = true_gst_on_mdr_paise
        d08_amount_at_risk = 0

    # Matches PRD §5.1's own worked example exactly: gross - commission - MDR.
    # TDS/TCS are tracked as a separate withholding obligation on intent,
    # not subtracted here -- PRD's own ₹83 figure is reached without one.
    transfer_amount_paise = gross_paise - commission_paise - mdr_paise

    intent_id = ids.next("int")
    world.intents.append(
        Intent(
            intent_id=intent_id,
            order_id=order_id,
            seller_id=seller.seller_id,
            expected_seller_amount_paise=transfer_amount_paise,
            expected_commission_paise=commission_paise,
            commission_rate_applied_bps=commission_bps_used,
            expected_tcs_paise=tcs_paise_used,
            expected_tds_paise=tds_paise_used,
            rate_card_version="v1",
        )
    )

    captured_at = placed_at + timedelta(seconds=rng.randint(5, 120))
    payment_id = ids.next("pay")
    world.payments.append(
        Payment(
            payment_id=payment_id,
            order_id=order_id,
            amount_paise=gross_paise,
            method=method,
            status="captured",
            captured_at_utc=_iso_datetime(captured_at),
            fee_paise=mdr_paise,
            tax_paise=tax_paise_used,
        )
    )

    # --- transfer state: SETTLED / IN_FLIGHT / ON_HOLD, mutually exclusive ---
    batch_end = _batch_end(config)
    transfer_id = ids.next("txfr")

    settled_at: datetime | None
    on_hold_until: datetime | None
    if defect_id == "D06":
        on_hold = True
        on_hold_until = None  # the defect itself -- see D06 avoidance note above
        settled_at = None
    elif defect_id is not None:
        # every other defect needs a settled transfer
        on_hold = False
        on_hold_until = None
        settled_at = captured_at + timedelta(days=config.settlement_days)
    else:
        is_hold_eligible = days_ago <= config.hold_release_days
        make_hold = is_hold_eligible and _roll(rng, config.hold_rate_bps)
        if make_hold:
            on_hold = True
            on_hold_until = batch_end + timedelta(days=rng.randint(1, config.hold_release_days))
            settled_at = None
        else:
            on_hold = False
            on_hold_until = None
            settlement_date = captured_at + timedelta(days=config.settlement_days)
            settled_at = settlement_date if settlement_date <= batch_end else None

    world.transfers.append(
        Transfer(
            transfer_id=transfer_id,
            payment_id=payment_id,
            linked_account_id=f"acc_{seller.seller_id.upper()}",
            amount_paise=transfer_amount_paise,
            on_hold=on_hold,
            on_hold_until_utc=_iso_datetime(on_hold_until) if on_hold_until else None,
            settled_at_utc=_iso_datetime(settled_at) if settled_at else None,
        )
    )

    # --- refund / reversal ---
    is_full_refund = False
    refund_created_at: datetime | None = None
    refund_amount_paise = 0
    if force_refund:
        refund_amount_paise = forced_refund_paise
        refund_created_at = captured_at + timedelta(days=rng.randint(1, 3))
        world.refunds.append(
            Refund(
                refund_id=ids.next("rfnd"),
                payment_id=payment_id,
                amount_paise=refund_amount_paise,
                created_at_utc=_iso_datetime(refund_created_at),
            )
        )
    elif defect_id is None and not on_hold and days_ago >= 5 and _roll(rng, config.refund_rate_bps):
        is_full_refund = _roll(rng, config.full_refund_share_bps)
        if is_full_refund:
            refund_amount_paise = gross_paise
        else:
            refund_amount_paise = apply_bps(gross_paise, rng.randint(2_000, 9_000))
        refund_created_at = captured_at + timedelta(days=rng.randint(1, 3))
        world.refunds.append(
            Refund(
                refund_id=ids.next("rfnd"),
                payment_id=payment_id,
                amount_paise=refund_amount_paise,
                created_at_utc=_iso_datetime(refund_created_at),
            )
        )

    reversal_amount_paise = 0
    if defect_id == "D07":
        # The defect itself: a reversal with no preceding refund.
        reversal_created_at = captured_at + timedelta(days=config.settlement_days + rng.randint(1, 2))
        reversal_amount_paise = transfer_amount_paise
        world.reversals.append(
            Reversal(
                reversal_id=ids.next("rvsl"),
                transfer_id=transfer_id,
                amount_paise=reversal_amount_paise,
                created_at_utc=_iso_datetime(reversal_created_at),
            )
        )
    elif (
        defect_id is None
        and is_full_refund
        and settled_at is not None
        and refund_created_at is not None
    ):
        # Clean data: a reversal only ever exists on an order with a
        # preceding FULL refund, and always claws back the full transfer
        # amount -- clean data never produces a reversal without a
        # refund, which is what D07's defect inverts.
        reversal_created_at = refund_created_at + timedelta(days=rng.randint(1, 2))
        if reversal_created_at <= batch_end and _roll(rng, config.reversal_rate_of_full_refunds_bps):
            world.reversals.append(
                Reversal(
                    reversal_id=ids.next("rvsl"),
                    transfer_id=transfer_id,
                    amount_paise=transfer_amount_paise,
                    created_at_utc=_iso_datetime(reversal_created_at),
                )
            )

    # --- dispute: only on settled transfers, never on defect-assigned
    # orders (keeps each injected defect isolated to one field) ---
    dispute_key: str | None = None
    dispute_debit_paise = 0
    if defect_id is None and settled_at is not None and _roll(rng, config.dispute_rate_bps):
        deduction_bps = rng.randint(3_000, 10_000)
        # Clamped to the transfer amount -- an earlier version of this
        # generator let a large dispute deduction on a small transfer push
        # bank_credit.amount_paise negative. Found by scanning 200 seeds
        # for it, not by a spec citation; a settlement amount can't be
        # negative regardless.
        deducted_amount_paise = min(apply_bps(gross_paise, deduction_bps), transfer_amount_paise)
        dispute_id = ids.next("disp")
        world.disputes.append(
            Dispute(
                dispute_id=dispute_id,
                payment_id=payment_id,
                amount_paise=gross_paise,
                status="resolved",
                deducted_amount_paise=deducted_amount_paise,
            )
        )
        dispute_key = dispute_id
        dispute_debit_paise = deducted_amount_paise

    # --- refund netting onto the settlement: a partial refund is netted
    # from this settlement's debit, same mechanism as a dispute deduction.
    # D03's defect is that this step is skipped for its own refund, even
    # though the refund record itself still exists -- "refund not netted
    # from seller obligation" (PRD §6), made meaningful by clean data
    # actually netting it everywhere else.
    refund_debit_paise = 0
    if refund_amount_paise and defect_id != "D03":
        refund_debit_paise = min(refund_amount_paise, transfer_amount_paise - dispute_debit_paise)
        refund_debit_paise = max(0, refund_debit_paise)

    debit_paise = dispute_debit_paise + refund_debit_paise

    # --- settlement_recon + bank_credit: only when settled ---
    if settled_at is not None:
        true_utr, narration, bank_utr = generate_settlement_reference(rng, config.unparseable_narration_rate_bps)
        credit_paise = transfer_amount_paise

        d02_shortfall = 0
        if defect_id == "D02":
            d02_shortfall = d02_shortfall_paise(rng, transfer_amount_paise, DEFAULT_V1)
            credit_paise -= d02_shortfall

        net_paise = max(0, credit_paise - debit_paise)
        world.settlement_recons.append(
            SettlementRecon(
                settlement_recon_id=ids.next("setl"),
                entity_key=transfer_id,
                entity_type="transfer",
                settlement_id=f"stlbatch_{_iso_date(settled_at)}",
                utr=true_utr,
                amount_paise=transfer_amount_paise,
                fee_paise=0,
                tax_paise=0,
                debit_paise=debit_paise,
                credit_paise=credit_paise,
                settled_at_utc=_iso_datetime(settled_at),
                dispute_key=dispute_key,
            )
        )
        bank_credit_id = ids.next("bank")
        world.bank_credits.append(
            BankCredit(
                bank_credit_id=bank_credit_id,
                bank_ref=f"RAZP{bank_credit_id.split('_')[1]}",  # external reference; not our record_key format
                utr=bank_utr,
                amount_paise=net_paise,
                credited_on=_iso_date(settled_at),
                narration=narration,
            )
        )
    else:
        d02_shortfall = 0

    # --- truth ---
    true_counterparts = [payment_id, transfer_id]
    if settled_at is not None:
        true_counterparts.append(world.settlement_recons[-1].settlement_recon_id)
        true_counterparts.append(world.bank_credits[-1].bank_credit_id)

    world.truth_records.append(
        TruthRecord(
            record_key=order_id,
            true_counterparts=true_counterparts,
            true_obligation={
                "commission_paise": true_commission_paise,
                "tcs_paise": true_tcs_paise,
                "tds_paise": true_tds_paise,
            },
            resolvable_from_available_data=True,
        )
    )

    if defect_id is not None:
        amount_at_risk = {
            "D01": abs(commission_paise - true_commission_paise),
            "D02": d02_shortfall,
            "D03": refund_amount_paise,
            "D04": d04_amount_at_risk,
            "D05": d05_amount_at_risk,
            "D06": transfer_amount_paise,
            "D07": reversal_amount_paise,
            "D08": d08_amount_at_risk,
        }[defect_id]

        # within_tolerance: whether the discrepancy this defect introduces
        # would itself still fall inside the live tolerance band around
        # the relevant base amount -- read from DEFAULT_V1 at truth-build
        # time, never a hardcoded True/False. D06 is a state defect, not
        # an amount comparison, so it's never "within tolerance" of
        # anything -- special-cased False.
        if defect_id == "D06":
            within_tolerance = False
        else:
            within_tolerance = DEFAULT_V1.within(transfer_amount_paise, transfer_amount_paise - amount_at_risk)

        world.injected_defects.append(
            InjectedDefect(
                instance_id=ids.next("inst"),
                record_key=order_id,
                defect_class=defect_id,
                amount_at_risk_paise=amount_at_risk,
                within_tolerance=within_tolerance,
                params=dict(assignment.params) if assignment else {},
            )
        )


def _replace_bank_counterpart(world: World, old_id: str, new_ids: list[str]) -> None:
    """A truth_record's true_counterparts holds record-key strings only
    -- swapping one bank_credit_id for one-or-two replacements needs no
    other change. Looked up by scanning rather than a prebuilt index:
    called at most once per affected order, from a post-loop pass that
    already knows exactly which order it's touching.
    """
    for i, record in enumerate(world.truth_records):
        if old_id in record.true_counterparts:
            updated = [c for x in record.true_counterparts for c in ([x] if x != old_id else new_ids)]
            world.truth_records[i] = replace(record, true_counterparts=updated)
            return


def _mark_unresolvable(world: World, bank_credit_id: str) -> None:
    """PRD §7.7's abstention metrics need a real population of
    resolvable_from_available_data=False to mean anything --
    true_counterparts is left alone (the partial bank credit is a real
    record that genuinely belongs to this order); what's false is
    whether the order is fully resolvable *from this batch*, which is
    exactly what this field means and exactly what's true here.
    """
    for i, record in enumerate(world.truth_records):
        if bank_credit_id in record.true_counterparts:
            world.truth_records[i] = replace(record, resolvable_from_available_data=False)
            return


def _apply_settlement_messiness(config: GeneratorConfig, rng: Random, ids: IdSequence, world: World) -> None:
    """PRD §8.2 T2 -- many:1 batching, 1:many splitting, and genuine
    partial settlement. A post-loop pass, run only after every per-order
    value from the main loop is already fixed: any rng consumption here
    can never shift an existing order's own output, which is what keeps
    this safe for every config that doesn't set these rates (all three
    default to 0, so this returns immediately and consumes no rng at
    all -- config_a.yaml/config_b.yaml and every existing test are
    untouched).

    settlement_recons are never touched by batching/splitting: only the
    manufactured bank_credit(s) get utr=None, forcing P0 to fall through
    to P1/P2 exactly like the existing single-order unparseable-narration
    path already does -- this guarantees the feature actually exercises
    the matcher's fallback passes rather than leaving it to the
    narration rate's own independent roll. In-flight settlements force
    utr=None for a sharper reason: P0 joins on identifier equality alone
    and never checks amounts, so a genuinely parseable UTR on a partial
    credit would let P0 silently commit a full match on partial money --
    a real false negative in the test corpus, not a matching puzzle.
    """
    if (
        config.settlement_batch_rate_bps == 0
        and config.settlement_split_rate_bps == 0
        and config.settlement_in_flight_rate_bps == 0
    ):
        return

    # (recon, bank_credit) pairs, in creation order -- both lists grow
    # in lockstep, one pair per settled order, so zip is safe here, and
    # only here: nothing else has touched either list yet.
    pairs = list(zip(world.settlement_recons, world.bank_credits, strict=True))
    by_settlement_id: dict[str, list[tuple[SettlementRecon, BankCredit]]] = {}
    for recon, bank_credit in pairs:
        by_settlement_id.setdefault(recon.settlement_id, []).append((recon, bank_credit))

    consumed: set[str] = set()
    new_bank_credits: list[BankCredit] = []

    for group in by_settlement_id.values():
        if len(group) >= 2 and _roll(rng, config.settlement_batch_rate_bps):
            total = sum(bc.amount_paise for _, bc in group)
            merged_id = ids.next("bank")
            _, narration, _ = generate_settlement_reference(rng, 10_000)  # 10_000 = always the unparseable branch
            new_bank_credits.append(
                BankCredit(
                    bank_credit_id=merged_id,
                    bank_ref=f"RAZP{merged_id.split('_')[1]}",
                    utr=None,
                    amount_paise=total,
                    credited_on=group[0][1].credited_on,
                    narration=narration,
                )
            )
            for _, bc in group:
                consumed.add(bc.bank_credit_id)
                _replace_bank_counterpart(world, bc.bank_credit_id, [merged_id])
            continue

        for _, bc in group:
            if _roll(rng, config.settlement_split_rate_bps):
                first_amount = bc.amount_paise // 2
                second_amount = bc.amount_paise - first_amount
                first_id = ids.next("bank")
                second_id = ids.next("bank")
                second_date = min(
                    datetime.strptime(bc.credited_on, "%Y-%m-%d").replace(tzinfo=UTC)
                    + timedelta(days=rng.randint(0, DEFAULT_V1.date_window_days)),
                    _batch_end(config),
                )
                _, first_narration, _ = generate_settlement_reference(rng, 10_000)
                _, second_narration, _ = generate_settlement_reference(rng, 10_000)
                new_bank_credits.append(
                    BankCredit(
                        bank_credit_id=first_id, bank_ref=f"RAZP{first_id.split('_')[1]}", utr=None,
                        amount_paise=first_amount, credited_on=bc.credited_on,
                        narration=first_narration,
                    )
                )
                new_bank_credits.append(
                    BankCredit(
                        bank_credit_id=second_id, bank_ref=f"RAZP{second_id.split('_')[1]}", utr=None,
                        amount_paise=second_amount, credited_on=_iso_date(second_date),
                        narration=second_narration,
                    )
                )
                consumed.add(bc.bank_credit_id)
                _replace_bank_counterpart(world, bc.bank_credit_id, [first_id, second_id])
                continue

            # amount_paise==0 means the settlement was already fully
            # consumed by dispute/refund netting -- there is no "30-70%
            # of zero" that means anything, so it's not eligible here.
            if bc.amount_paise > 0 and _roll(rng, config.settlement_in_flight_rate_bps):
                # 30-70% arrived; a smaller gap would just be a rounding-
                # level near-miss, which is P3's job, not this one's.
                arrived_bps = rng.randint(3000, 7000)
                arrived_amount = apply_bps(bc.amount_paise, arrived_bps)
                _, narration, _ = generate_settlement_reference(rng, 10_000)
                new_bank_credits.append(
                    bc.model_copy(update={"amount_paise": arrived_amount, "utr": None, "narration": narration})
                )
                consumed.add(bc.bank_credit_id)
                _mark_unresolvable(world, bc.bank_credit_id)

    final_list = [bc for bc in world.bank_credits if bc.bank_credit_id not in consumed] + new_bank_credits

    # Renumber by final list position and remap every truth reference.
    # bank_credit_id is the one entity id ingest derives from CSV row
    # position (plumb/ingest/adapters/bank.py's derive_canonical_id),
    # not from any value carried in the row itself -- unlike
    # settlement_recon_id, which razorpay.json states explicitly per
    # row (BACKEND_SCHEMA.md's own "every entity here already carries
    # its own id" framing). Removing consumed entries and appending new
    # ones changes every *surviving* record's row position too, not
    # just the manufactured ones -- so this has to renumber the whole
    # list, every time, not only the touched entries. Caught by
    # comparing truth's true_counterparts against what the matcher
    # actually ingested for the same order: they referred to two
    # different bank credits entirely.
    id_remap: dict[str, str] = {}
    renumbered: list[BankCredit] = []
    for i, bc in enumerate(final_list, start=1):
        new_id = f"bank_{i:05d}"
        id_remap[bc.bank_credit_id] = new_id
        renumbered.append(bc.model_copy(update={"bank_credit_id": new_id, "bank_ref": f"RAZP{i:05d}"}))
    world.bank_credits[:] = renumbered

    for i, record in enumerate(world.truth_records):
        remapped = [id_remap.get(c, c) for c in record.true_counterparts]
        if remapped != record.true_counterparts:
            world.truth_records[i] = replace(record, true_counterparts=remapped)


def _construct_adversarial_pairs(config: GeneratorConfig, rng: Random, ids: IdSequence, world: World) -> None:
    """PRD §8.2 T3, case 1 -- LLD §4.2's ambiguity trap, built from real
    generated data: two orders forced to share one settlement's exact
    (amount, date), both bank credits made unparseable, so P0 cannot
    resolve either via UTR and P1/P2 must recognise -- not guess --
    that either order could be the true owner of either bank credit's
    money. Runs after the main loop, same safety reasoning as
    _apply_settlement_messiness; must run before that function if both
    are ever combined, since it relies on settlement_recons/bank_credits
    still being index-aligned one pair per settled order.

    Record keys never change -- only field values do -- so
    TruthRecord.true_counterparts needs no patching: each order's own
    counterpart chain is still, genuinely, its own.
    """
    if config.adversarial_pair_count == 0:
        return

    needed = 2 * config.adversarial_pair_count
    if len(world.bank_credits) < needed:
        raise ValueError(
            f"adversarial_pair_count={config.adversarial_pair_count} needs {needed} settled orders, "
            f"batch only produced {len(world.bank_credits)}"
        )

    indices = list(range(len(world.bank_credits)))
    rng.shuffle(indices)
    chosen = indices[:needed]

    for k in range(config.adversarial_pair_count):
        i, j = chosen[2 * k], chosen[2 * k + 1]
        canonical_bank_credit = world.bank_credits[i]
        canonical_recon = world.settlement_recons[i]

        # BankCredit/SettlementRecon are frozen pydantic models, not
        # dataclasses (only TruthRecord is) -- model_copy(update=...) is
        # their equivalent of dataclasses.replace(). narration must be
        # regenerated too, not just utr=None: ingest re-derives utr from
        # the narration *text* independently (LLD §3.2) -- leaving the
        # original narration in place would still say "UTR:XXXX..." and
        # ingest would silently re-resolve it, discarding this override.
        _, i_narration, _ = generate_settlement_reference(rng, 10_000)
        _, j_narration, _ = generate_settlement_reference(rng, 10_000)
        world.bank_credits[i] = canonical_bank_credit.model_copy(update={"utr": None, "narration": i_narration})
        world.bank_credits[j] = world.bank_credits[j].model_copy(
            update={
                "amount_paise": canonical_bank_credit.amount_paise,
                "credited_on": canonical_bank_credit.credited_on,
                "utr": None,
                "narration": j_narration,
            }
        )
        # debit_paise reset to 0 on the follower: its own net target must
        # equal the leader's amount_paise exactly, and the leader's own
        # debit_paise is already baked into that amount. A minor,
        # accepted simplification -- this constructs a matching trap,
        # not a verify-level netting scenario.
        world.settlement_recons[j] = world.settlement_recons[j].model_copy(
            update={
                "credit_paise": canonical_bank_credit.amount_paise,
                "debit_paise": 0,
                "settlement_id": canonical_recon.settlement_id,
                "settled_at_utc": canonical_recon.settled_at_utc,
            }
        )


def build_world(config: GeneratorConfig) -> World:
    rng = Random(config.seed)
    ids = IdSequence()
    world = World()

    sellers = _build_sellers(config, rng, ids, world)
    assignments = assign_defects(rng, config.batch_size, config.defects)

    for i in range(config.batch_size):
        seller = sellers[rng.randrange(len(sellers))]
        _build_order(config, rng, ids, world, seller, assignments.get(i))

    _construct_adversarial_pairs(config, rng, ids, world)
    _apply_settlement_messiness(config, rng, ids, world)

    return world
