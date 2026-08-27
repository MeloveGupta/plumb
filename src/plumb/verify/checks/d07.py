"""LLD §5.1/PRD §6 -- D07 reversal without refund.

world.py's D07 injection: a Reversal is created with no preceding
Refund at all -- `force_refund = defect_id in ("D03", "D04")` excludes
D07 explicitly, and the organic-refund branch requires `defect_id is
None`, so a D07-assigned order has zero Refund records, always. Clean
data's own reversal logic only ever fires after a FULL refund
(`is_full_refund`), and both the clean and D07 reversal always claw back
exactly `transfer_amount_paise` -- amount is never a distinguishing
signal, only presence/absence of any refund at all. A D07 order always
gets a settled transfer (`elif defect_id is not None: ... settled_at =
...`), so completeness is always FULL or MISSING_BANK, never
MISSING_SETTLEMENT/INTENT_ONLY -- mirrors D03's `requires`.
"""

from plumb.domain.money import sum_paise
from plumb.verify.registry import CheckContext
from plumb.verify.trace import EvidenceRef, Finding, TraceBuilder, classify_severity
from plumb.verify.unit import Completeness, SettlementUnit


class D07ReversalWithoutRefund:
    defect_id = "D07"
    requires = frozenset({Completeness.FULL, Completeness.MISSING_BANK})

    def applies_to(self, unit: SettlementUnit) -> bool:
        return bool(unit.reversals)

    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None:
        if unit.refunds:
            return None  # a reversal with a covering refund is clean, not D07

        amount_at_risk = sum_paise(r.amount_paise for r in unit.reversals)

        trace = (
            TraceBuilder()
            .step(
                "amount_at_risk",
                "sum(reversal.amount_paise) -- no refund record exists for this order",
                {"reversal_count": len(unit.reversals), "refund_count": 0},
                amount_at_risk,
            )
            .conclude(
                f"order {unit.order.order_id}: {len(unit.reversals)} reversal(s) totalling "
                f"{amount_at_risk} paise with no corresponding refund -- seller debited for a "
                f"refund the customer never received"
            )
        )
        return Finding(
            defect_id="D07",
            unit_id=unit.unit_id,
            severity=classify_severity(amount_at_risk, ctx.config),
            amount_at_risk_paise=amount_at_risk,
            on_matched_record=unit.match_id is not None,
            conclusion=trace.conclusion,
            trace=trace,
            evidence=(
                (EvidenceRef(unit.order.order_id, "order"), EvidenceRef(unit.intent.intent_id, "intent"))
                + tuple(EvidenceRef(r.reversal_id, "reversal") for r in unit.reversals)
            ),
        )
