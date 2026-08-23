"""TRD §8.1 -- the seeded world. Dependency order: sellers -> orders ->
order_lines -> intents -> payments -> transfers -> refunds -> reversals ->
disputes -> settlement_recons -> bank_credits. Every downstream amount is
computed from the upstream one, never independently re-rolled.

All randomness comes from the one Random instance created in build_world;
nothing here reads the system clock. Probability decisions use rng.randint
against a bps threshold (never rng.random()/rng.uniform() touching a paise
value) -- money stays int, full stop.

D06 avoidance: on_hold=1 always comes with a real, non-null
on_hold_until_utc here. NULL + on_hold=1 is created later, exclusively, by
the D06 injector (P0.8) -- clean data never produces that combination.
"""

from dataclasses import dataclass, field
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

from plumb_gen.config import GeneratorConfig
from plumb_gen.fixtures import (
    CATEGORIES,
    COMMISSION_BPS_BY_CATEGORY,
    GOODS_GST_BPS,
    MDR_BPS_BY_METHOD,
    SELLER_COUNT,
)
from plumb_gen.ids import IdSequence
from plumb_gen.rates import GST_ON_FEES_BPS, TCS_BPS, TDS_BPS

METHODS = sorted(MDR_BPS_BY_METHOD)  # stable order for rng.choice -- never dict iteration order


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


class _UtrCounter:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"{300_000_000_000 + self._n:012d}"


def _build_order(
    config: GeneratorConfig,
    rng: Random,
    ids: IdSequence,
    world: World,
    seller: Seller,
    utrs: _UtrCounter,
) -> None:
    gross_paise: Paise = rng.randint(50_000, 500_000)  # Rs 500 - Rs 5000
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
    # two always sum to gross_paise exactly.
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

    commission_paise = apply_bps(gross_paise, seller.commission_bps)
    tds_paise = apply_bps(gross_paise, TDS_BPS)  # GROSS basis, PRD §5.1
    tcs_paise = apply_bps(gross_paise, TCS_BPS)  # clean order, no returns -> net_of_returns == gross

    method = METHODS[rng.randrange(len(METHODS))]
    mdr_paise = apply_bps(gross_paise, MDR_BPS_BY_METHOD[method])
    gst_on_mdr_paise = apply_bps(mdr_paise, GST_ON_FEES_BPS)

    # Matches PRD §5.1's own worked example exactly: gross - commission - MDR.
    # TDS/TCS are tracked as a separate withholding obligation on intent,
    # not subtracted here -- PRD's own ₹83 figure is reached without one.
    transfer_amount_paise = gross_paise - commission_paise - mdr_paise

    world.intents.append(
        Intent(
            intent_id=ids.next("int"),
            order_id=order_id,
            seller_id=seller.seller_id,
            expected_seller_amount_paise=transfer_amount_paise,
            expected_commission_paise=commission_paise,
            commission_rate_applied_bps=seller.commission_bps,
            expected_tcs_paise=tcs_paise,
            expected_tds_paise=tds_paise,
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
            tax_paise=gst_on_mdr_paise,
        )
    )

    # --- transfer state: SETTLED / IN_FLIGHT / ON_HOLD, mutually exclusive ---
    batch_end = _batch_end(config)
    is_hold_eligible = days_ago <= config.hold_release_days
    make_hold = is_hold_eligible and _roll(rng, config.hold_rate_bps)

    transfer_id = ids.next("txfr")

    settled_at: datetime | None
    on_hold_until: datetime | None
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

    # --- refund / reversal: only for non-held orders old enough to have room ---
    is_full_refund = False
    refund_created_at: datetime | None = None
    if not on_hold and days_ago >= 5 and _roll(rng, config.refund_rate_bps):
        is_full_refund = _roll(rng, config.full_refund_share_bps)
        if is_full_refund:
            refund_amount_paise = gross_paise
        else:
            refund_fraction_bps = rng.randint(2_000, 9_000)
            refund_amount_paise = apply_bps(gross_paise, refund_fraction_bps)
        refund_created_at = captured_at + timedelta(days=rng.randint(1, 3))
        world.refunds.append(
            Refund(
                refund_id=ids.next("rfnd"),
                payment_id=payment_id,
                amount_paise=refund_amount_paise,
                created_at_utc=_iso_datetime(refund_created_at),
            )
        )

    # A reversal only ever exists on an order with a preceding FULL refund,
    # and always claws back the full transfer amount -- clean data never
    # produces a reversal without a refund, which is what D07 needs later.
    if is_full_refund and settled_at is not None and refund_created_at is not None:
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

    # --- dispute: only on settled transfers ---
    dispute_key: str | None = None
    debit_paise = 0
    if settled_at is not None and _roll(rng, config.dispute_rate_bps):
        deduction_bps = rng.randint(3_000, 10_000)
        deducted_amount_paise = apply_bps(gross_paise, deduction_bps)
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
        debit_paise = deducted_amount_paise

    # --- settlement_recon + bank_credit: only when settled ---
    if settled_at is not None:
        utr = utrs.next()
        credit_paise = transfer_amount_paise
        net_paise = credit_paise - debit_paise
        world.settlement_recons.append(
            SettlementRecon(
                settlement_recon_id=ids.next("setl"),
                entity_key=transfer_id,
                entity_type="transfer",
                settlement_id=f"stlbatch_{_iso_date(settled_at)}",
                utr=utr,
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
                utr=utr,
                amount_paise=net_paise,
                credited_on=_iso_date(settled_at),
                narration=f"NEFT/UTR:{utr}/PLATFORM SETTLEMENT",
            )
        )


def build_world(config: GeneratorConfig) -> World:
    rng = Random(config.seed)
    ids = IdSequence()
    world = World()
    utrs = _UtrCounter()

    sellers = _build_sellers(config, rng, ids, world)

    for _ in range(config.batch_size):
        seller = sellers[rng.randrange(len(sellers))]
        _build_order(config, rng, ids, world, seller, utrs)

    return world
