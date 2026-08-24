"""TRD §8.1 -- the seeded world's own invariants: exactly 200 clean
records, every downstream amount actually derived from its upstream
record (recomputed independently here, not re-derived from the
generator's own apply_bps call), and D06 never producible in clean data.
"""

import ast
from pathlib import Path

import pytest

from plumb_gen.config import GeneratorConfig
from plumb_gen.world import build_world

SEEDS = [1, 2, 3, 7, 42]


def _world(seed=42, **overrides):
    config = GeneratorConfig(seed=seed, batch_id="batch_test", **overrides)
    return build_world(config)


def test_batch_size_and_one_to_one_entities():
    world = _world()
    assert len(world.orders) == 200
    order_ids = {o.order_id for o in world.orders}
    assert {ol.order_id for ol in world.order_lines} == order_ids
    assert {i.order_id for i in world.intents} == order_ids
    assert {p.order_id for p in world.payments} == order_ids
    assert len(world.order_lines) == 200
    assert len(world.intents) == 200
    assert len(world.payments) == 200
    assert len(world.transfers) == 200


@pytest.mark.parametrize("seed", SEEDS)
def test_transfer_amount_derives_from_gross_commission_mdr(seed):
    world = _world(seed=seed)
    payments_by_id = {p.payment_id: p for p in world.payments}
    intents_by_order = {i.order_id: i for i in world.intents}
    for transfer in world.transfers:
        payment = payments_by_id[transfer.payment_id]
        intent = intents_by_order[payment.order_id]
        recomputed = payment.amount_paise - intent.expected_commission_paise - payment.fee_paise
        assert transfer.amount_paise == recomputed


@pytest.mark.parametrize("seed", SEEDS)
def test_order_line_sums_to_gross(seed):
    world = _world(seed=seed)
    orders_by_id = {o.order_id: o for o in world.orders}
    for line in world.order_lines:
        order = orders_by_id[line.order_id]
        assert line.taxable_paise + line.gst_paise == order.gross_paise


@pytest.mark.parametrize("seed", SEEDS)
def test_no_transfer_has_null_on_hold_until_while_on_hold(seed):
    world = _world(seed=seed)
    violations = [t.transfer_id for t in world.transfers if t.on_hold and t.on_hold_until_utc is None]
    assert not violations, violations


@pytest.mark.parametrize("seed", SEEDS)
def test_every_reversal_has_a_preceding_full_refund(seed):
    world = _world(seed=seed)
    payments_by_id = {p.payment_id: p for p in world.payments}
    transfers_by_id = {t.transfer_id: t for t in world.transfers}
    refunds_by_payment: dict[str, list] = {}
    for r in world.refunds:
        refunds_by_payment.setdefault(r.payment_id, []).append(r)

    for reversal in world.reversals:
        transfer = transfers_by_id[reversal.transfer_id]
        payment = payments_by_id[transfer.payment_id]
        refunds = refunds_by_payment.get(payment.payment_id, [])
        assert any(r.amount_paise == payment.amount_paise for r in refunds), (
            f"reversal {reversal.reversal_id} has no preceding full refund"
        )
        assert reversal.amount_paise == transfer.amount_paise


@pytest.mark.parametrize("seed", SEEDS)
def test_settlement_credit_minus_debit_equals_bank_credit(seed):
    # Paired by construction order, not by utr: bank_credit.utr is null
    # for unparseable narrations (P0.7), so it can't be used as a join key
    # here -- world.py appends one settlement_recon and one bank_credit
    # per settled order, in lockstep, so position is the reliable pairing.
    world = _world(seed=seed)
    assert len(world.settlement_recons) == len(world.bank_credits)
    for sr, bank_credit in zip(world.settlement_recons, world.bank_credits, strict=True):
        assert sr.credit_paise - sr.debit_paise == bank_credit.amount_paise


# --- no clock reads, AST-based so it doesn't false-positive on this
# module's own docstrings explaining the rule (a naive text grep would).

_CLOCK_OR_UUID_ATTRS = ("now", "today", "uuid4")
GENERATOR_ROOT = Path(__file__).resolve().parents[2] / "src" / "plumb_gen"


def _clock_or_uuid_calls(tree: ast.Module) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _CLOCK_OR_UUID_ATTRS:
            hits.append(func.attr)
        elif isinstance(func, ast.Attribute) and func.attr == "time" and isinstance(func.value, ast.Name):
            if func.value.id == "time":
                hits.append("time.time")
        elif isinstance(func, ast.Name) and func.id == "uuid4":
            hits.append("uuid4")
    return hits


def test_generator_package_never_reads_the_clock():
    violations: list[str] = []
    for path in sorted(GENERATOR_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for hit in _clock_or_uuid_calls(tree):
            violations.append(f"{path}: {hit}")
    assert not violations, violations
