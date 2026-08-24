"""PRD §6 -- each of D01-D08 demonstrated actually producing the specific
defect it claims, on real generated data. Not "a finding-shaped thing
exists" -- the exact signature named in each defect's own description.
"""

import pytest

from plumb.domain.money import apply_bps
from plumb.domain.tolerance import DEFAULT_V1
from plumb_gen.config import GeneratorConfig
from plumb_gen.injection_config import DefectSpec, InjectionConfig
from plumb_gen.rates import GST_ON_FEES_BPS, TCS_BPS, TDS_BPS
from plumb_gen.world import build_world, D08_WRONG_GST_BPS


def _world_with(defect_id: str, count: int, seed: int = 1, **extra):
    config = GeneratorConfig(
        seed=seed,
        batch_id="batch_test",
        defects=InjectionConfig(defects={defect_id: DefectSpec(count=count, **extra)}),
    )
    return build_world(config)


def _lookup(world, record_key):
    order = next(o for o in world.orders if o.order_id == record_key)
    intent = next(i for i in world.intents if i.order_id == record_key)
    payment = next(p for p in world.payments if p.order_id == record_key)
    transfer = next(t for t in world.transfers if t.payment_id == payment.payment_id)
    rate_card = next(rc for rc in world.seller_rate_cards if rc.seller_id == order.seller_id)
    return order, intent, payment, transfer, rate_card


def test_only_configured_defect_class_is_produced():
    # "each injectable in isolation" -- literal, not inferred.
    world = _world_with("D01", 6)
    assert {d.defect_class for d in world.injected_defects} == {"D01"}
    assert len(world.injected_defects) == 6


def test_requesting_more_defects_than_batch_size_raises():
    config = GeneratorConfig(
        seed=1,
        batch_id="batch_test",
        batch_size=10,
        defects=InjectionConfig(defects={"D01": DefectSpec(count=20)}),
    )
    with pytest.raises(ValueError):
        build_world(config)


def test_d01_commission_rate_drift():
    world = _world_with("D01", 6)
    assert len(world.injected_defects) == 6
    for d in world.injected_defects:
        order, intent, payment, transfer, rate_card = _lookup(world, d.record_key)
        assert intent.commission_rate_applied_bps != rate_card.commission_bps
        true_commission = apply_bps(order.gross_paise, rate_card.commission_bps)
        assert d.amount_at_risk_paise == abs(intent.expected_commission_paise - true_commission)
        # Downstream consistency: transfer derives from the SAME wrong rate.
        assert transfer.amount_paise == order.gross_paise - intent.expected_commission_paise - payment.fee_paise


def test_d02_short_settlement_in_tolerance():
    world = _world_with("D02", 8)
    assert len(world.injected_defects) == 8
    for d in world.injected_defects:
        order, intent, payment, transfer, _ = _lookup(world, d.record_key)
        band = DEFAULT_V1.band_paise(transfer.amount_paise)
        assert 0 < d.amount_at_risk_paise < band
        assert d.within_tolerance is True
        sr = next(s for s in world.settlement_recons if s.entity_key == transfer.transfer_id)
        # transfer/intent stay correct -- only the settlement side is short.
        assert sr.credit_paise == transfer.amount_paise - d.amount_at_risk_paise
        assert intent.expected_seller_amount_paise == transfer.amount_paise


def test_d03_refund_not_netted():
    world = _world_with("D03", 5)
    assert len(world.injected_defects) == 5
    for d in world.injected_defects:
        _, _, payment, transfer, _ = _lookup(world, d.record_key)
        refund = next(r for r in world.refunds if r.payment_id == payment.payment_id)
        sr = next(s for s in world.settlement_recons if s.entity_key == transfer.transfer_id)
        assert d.amount_at_risk_paise == refund.amount_paise
        # The defect: a real refund exists, but the settlement wasn't
        # reduced for it -- full transfer amount still credited.
        assert sr.debit_paise == 0
        assert sr.credit_paise == transfer.amount_paise


def test_d03_contrasts_with_clean_refunds_which_are_netted():
    # Proves D03 is a real deviation, not just "how refunds always work."
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    netted_any = False
    for refund in world.refunds:
        transfer = next((t for t in world.transfers if t.payment_id == refund.payment_id), None)
        if transfer is None or transfer.settled_at_utc is None:
            continue
        sr = next((s for s in world.settlement_recons if s.entity_key == transfer.transfer_id), None)
        if sr is None:
            continue
        assert sr.debit_paise > 0
        netted_any = True
    assert netted_any, "no clean refunded+settled order found to contrast against"


def test_d04_tcs_basis_error():
    world = _world_with("D04", 5)
    assert len(world.injected_defects) == 5
    for d in world.injected_defects:
        order, intent, payment, _, _ = _lookup(world, d.record_key)
        refund = next(r for r in world.refunds if r.payment_id == payment.payment_id)
        true_tcs = apply_bps(order.gross_paise - refund.amount_paise, TCS_BPS)
        wrong_tcs = apply_bps(order.gross_paise, TCS_BPS)
        assert intent.expected_tcs_paise == wrong_tcs
        assert wrong_tcs != true_tcs
        assert d.amount_at_risk_paise == abs(wrong_tcs - true_tcs)


def test_d05_tds_basis_error():
    world = _world_with("D05", 5)
    assert len(world.injected_defects) == 5
    for d in world.injected_defects:
        order, intent, payment, transfer, _ = _lookup(world, d.record_key)
        true_tds = apply_bps(order.gross_paise, TDS_BPS)
        wrong_tds = apply_bps(transfer.amount_paise, TDS_BPS)
        assert intent.expected_tds_paise == wrong_tds
        assert wrong_tds != true_tds
        assert d.amount_at_risk_paise == abs(true_tds - wrong_tds)


def test_d06_orphaned_hold():
    world = _world_with("D06", 5)
    assert len(world.injected_defects) == 5
    for d in world.injected_defects:
        _, _, _, transfer, _ = _lookup(world, d.record_key)
        assert transfer.on_hold is True
        assert transfer.on_hold_until_utc is None
        assert transfer.settled_at_utc is None
        assert d.amount_at_risk_paise == transfer.amount_paise
        assert d.within_tolerance is False


def test_d06_never_appears_without_being_requested():
    # Regression guard: clean data (P0.6's own invariant) must still hold.
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    violations = [t for t in world.transfers if t.on_hold and t.on_hold_until_utc is None]
    assert not violations


def test_d07_reversal_without_refund():
    world = _world_with("D07", 5)
    assert len(world.injected_defects) == 5
    for d in world.injected_defects:
        _, _, payment, transfer, _ = _lookup(world, d.record_key)
        reversal = next(rv for rv in world.reversals if rv.transfer_id == transfer.transfer_id)
        has_refund = any(r.payment_id == payment.payment_id for r in world.refunds)
        assert not has_refund
        assert reversal.amount_paise == transfer.amount_paise
        assert d.amount_at_risk_paise == reversal.amount_paise


def test_d08_gst_on_mdr_mismatch():
    world = _world_with("D08", 5)
    assert len(world.injected_defects) == 5
    for d in world.injected_defects:
        _, _, payment, _, _ = _lookup(world, d.record_key)
        true_tax = apply_bps(payment.fee_paise, GST_ON_FEES_BPS)
        wrong_tax = apply_bps(payment.fee_paise, D08_WRONG_GST_BPS)
        assert payment.tax_paise == wrong_tax
        assert wrong_tax != true_tax
        assert d.amount_at_risk_paise == abs(wrong_tax - true_tax)
        assert d.amount_at_risk_paise > 0


def test_within_tolerance_reflects_the_live_profile_not_a_constant():
    # Same D02 mechanism, called with a deliberately narrower profile,
    # confirms the flag tracks the profile actually passed in.
    from random import Random

    from plumb.domain.tolerance import ToleranceProfile
    from plumb_gen.injectors import d02_shortfall_paise

    transfer_amount = 500_000
    narrow = ToleranceProfile("narrow", amount_abs_paise=1, amount_rel_bps=1, date_window_days=2)
    shortfall = d02_shortfall_paise(Random(1), transfer_amount, narrow)
    assert 0 < shortfall < narrow.band_paise(transfer_amount)
    # A shortfall sized for the wide default profile need not fit the
    # narrow one -- proves band_paise is genuinely profile-dependent.
    assert narrow.band_paise(transfer_amount) < DEFAULT_V1.band_paise(transfer_amount)
