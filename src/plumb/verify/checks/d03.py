"""LLD §5.1/PRD §6 -- D03 refund netting error (under-netting only).

world.py has no dedicated d03_* injector -- D03 is a single skipped
conditional in the per-order build: `if refund_amount_paise and
defect_id != "D03":` (world.py:436). Clean data nets a refund into
settlement_recon.debit_paise via `refund_debit_paise =
min(refund_amount_paise, transfer_amount_paise - dispute_debit_paise)`,
clamped >= 0, folded into debit_paise alongside any dispute deduction
(world.py:435-440). For a D03-assigned order this netting step never
runs -- refund_debit_paise stays 0 even though the Refund record itself,
credit_paise, and every other field are generated normally. Disputes
never co-occur with any injected defect (dispute-rolling is gated
`defect_id is None`, world.py:408), so dispute_total is always 0 on a
D03 unit -- simplifies the recompute below, doesn't complicate it.

PRD §6 describes three D03 submodes: "not netted", "netted twice", or
"netted in the wrong period." Only the first is generator-verifiable --
there is no injector for the other two, so there is no ground truth to
validate a detector against (same restraint D01/D05 apply to their own
multi-submode PRD entries). This check fires only on delta > 0
(under-netting); the "netted twice" shape (delta < 0) is deliberately
left undetected and returns None.

D02/D03 non-cross-fire, worked with real numbers (gross=200,000,
commission 1500bps=30,000, mdr=0, forced refund=50,000, no dispute, on a
D03 order): expected_transfer_paise = 170,000. D02's compute_expected_net
independently re-derives the refund netting from unit.refunds (not from
recon_rows.debit_paise), so its expected = 170,000 - min(50,000,170,000)
= 120,000. Observed on the D03 order: credit_paise=170,000 (no D02
shortfall injected), debit_paise=0 (the D03 defect) -> D02's actual =
170,000. D02's delta = 120,000 - 170,000 = -50,000 -- NEGATIVE, so D02's
own `if delta <= 0: return None` guard discards it. D02 never fires on a
D03 order: its independently-recomputed `expected` is already correctly
netted while `actual` (built from the observed, wrongly-un-netted
debit_paise) looks like an overpayment, not a shortfall -- a direct
consequence of D02 already recomputing netting from unit.refunds rather
than trusting debit_paise. No new guard needed in either check.
"""

from plumb.domain.money import sum_paise
from plumb.verify.checks.d02 import expected_transfer_paise
from plumb.verify.registry import CheckContext
from plumb.verify.trace import EvidenceRef, Finding, TraceBuilder, classify_severity
from plumb.verify.unit import Completeness, SettlementUnit


class D03RefundNettingError:
    defect_id = "D03"
    requires = frozenset({Completeness.FULL, Completeness.MISSING_BANK})

    def applies_to(self, unit: SettlementUnit) -> bool:
        return bool(unit.recon_rows) and bool(unit.refunds)

    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None:
        trace_builder = TraceBuilder()
        pre_debit_transfer = expected_transfer_paise(unit, trace_builder)
        refund_total = sum_paise(r.amount_paise for r in unit.refunds)
        dispute_total = sum_paise(d.deducted_amount_paise for d in unit.disputes)

        # Mirrors world.py's own clamp order exactly: dispute nets first,
        # refund is clamped against what's left.
        expected_dispute_debit = min(dispute_total, pre_debit_transfer)
        trace_builder.step(
            "expected_dispute_debit",
            "min(dispute_total, pre_debit_transfer)",
            {"dispute_total": dispute_total, "pre_debit_transfer": pre_debit_transfer},
            expected_dispute_debit,
        )

        expected_refund_debit = max(0, min(refund_total, pre_debit_transfer - expected_dispute_debit))
        trace_builder.step(
            "expected_refund_debit",
            "max(0, min(refund_total, pre_debit_transfer - expected_dispute_debit))",
            {
                "refund_total": refund_total,
                "pre_debit_transfer": pre_debit_transfer,
                "expected_dispute_debit": expected_dispute_debit,
            },
            expected_refund_debit,
        )

        expected_debit = expected_dispute_debit + expected_refund_debit
        trace_builder.step(
            "expected_debit",
            "expected_dispute_debit + expected_refund_debit",
            {"expected_dispute_debit": expected_dispute_debit, "expected_refund_debit": expected_refund_debit},
            expected_debit,
        )

        actual_debit = sum_paise(r.debit_paise for r in unit.recon_rows)
        delta = expected_debit - actual_debit

        if delta <= 0:
            return None  # correctly netted, or the unimplemented "netted twice" shape

        trace = (
            trace_builder.step("actual_debit", "actual_debit", {"actual_debit": actual_debit}, actual_debit)
            .step("delta", "expected_debit - actual_debit", {"expected_debit": expected_debit, "actual_debit": actual_debit}, delta)
            .conclude(
                f"order {unit.order.order_id}: refund/dispute netting expected {expected_debit} paise debit, "
                f"settlement_recon reflects only {actual_debit} paise -- under-netted by {delta} paise"
            )
        )
        return Finding(
            defect_id="D03",
            unit_id=unit.unit_id,
            severity=classify_severity(delta, ctx.config),
            amount_at_risk_paise=delta,
            on_matched_record=unit.match_id is not None,
            conclusion=trace.conclusion,
            trace=trace,
            evidence=(
                (EvidenceRef(unit.order.order_id, "order"), EvidenceRef(unit.intent.intent_id, "intent"))
                + tuple(EvidenceRef(r.refund_id, "refund") for r in unit.refunds)
                + tuple(EvidenceRef(r.settlement_recon_id, "recon_row") for r in unit.recon_rows)
            ),
        )
