"""LLD §5.1/PRD §6 -- D01 commission rate drift.

No pseudocode exists for D01 in any spec; PRD gives only "applied
commission != seller's contracted rate for that category at the order's
timestamp." The contracted rate is `SettlementUnit.rate_card` (resolved
by the builder's own as-of lookup against SellerRateCard, see
verify/unit.py::_resolve_rate_card) -- D01 itself only compares it
against `Intent.commission_rate_applied_bps`. This is a different rate
family from rules/ratebook.py's RateBook (TDS/TCS/GST_ON_FEES);
SellerRateCard has its own effective-dating and is not looked up through
RateBook at all.

LLD §5.1: "a unit at INTENT_ONLY still supports D01" -- so `requires`
is every Completeness value; `applies_to` gates only on whether a rate
card actually resolved.

Firing rule (flagged as a design choice, since PRD gives no tolerance
for D01 the way it does for D02): exact bps-equality -- a deliberate
mid-period rate change is exactly what this defect exists to catch, so
no band is applied to the *rate*. The one allowance is on the *money*
consequence: if the bps mismatch still rounds to the same paise figure
on this order's actual gross, there is nothing to report.
"""

from plumb.domain.money import apply_bps
from plumb.verify.registry import CheckContext
from plumb.verify.trace import EvidenceRef, Finding, TraceBuilder, classify_severity
from plumb.verify.unit import Completeness, SettlementUnit

_ALL_COMPLETENESS = frozenset(
    {Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT, Completeness.INTENT_ONLY}
)


class D01CommissionRateDrift:
    defect_id = "D01"
    requires = _ALL_COMPLETENESS

    def applies_to(self, unit: SettlementUnit) -> bool:
        return unit.rate_card is not None

    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None:
        assert unit.rate_card is not None  # applies_to() already guarantees this
        contracted_bps = unit.rate_card.commission_bps
        applied_bps = unit.intent.commission_rate_applied_bps
        if contracted_bps == applied_bps:
            return None

        gross = unit.order.gross_paise
        contracted_commission = apply_bps(gross, contracted_bps)
        applied_commission = apply_bps(gross, applied_bps)
        delta = abs(applied_commission - contracted_commission)
        if delta == 0:
            return None  # bps differ but round to the same paise figure -- no money at stake

        trace = (
            TraceBuilder()
            .step(
                "contracted_commission",
                "(gross_paise * contracted_bps + 5000) // 10000",
                {"gross_paise": gross, "contracted_bps": contracted_bps},
                contracted_commission,
            )
            .step(
                "applied_commission",
                "(gross_paise * applied_bps + 5000) // 10000",
                {"gross_paise": gross, "applied_bps": applied_bps},
                applied_commission,
            )
            .step(
                "delta",
                "abs(applied_commission - contracted_commission)",
                {"applied_commission": applied_commission, "contracted_commission": contracted_commission},
                delta,
            )
            .conclude(
                f"order {unit.order.order_id}: commission applied at {applied_bps}bps vs contracted "
                f"{contracted_bps}bps (rate_card {unit.rate_card.rate_card_id}, category "
                f"{unit.order.category}) as of {unit.order.placed_at_utc}; delta {delta} paise"
            )
        )
        return Finding(
            defect_id="D01",
            unit_id=unit.unit_id,
            severity=classify_severity(delta, ctx.config),
            amount_at_risk_paise=delta,
            on_matched_record=unit.match_id is not None,
            conclusion=trace.conclusion,
            trace=trace,
            evidence=(
                EvidenceRef(unit.order.order_id, "order"),
                EvidenceRef(unit.intent.intent_id, "intent"),
                EvidenceRef(unit.rate_card.rate_card_id, "rate_card"),
            ),
        )
