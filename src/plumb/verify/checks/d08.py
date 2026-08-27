"""LLD §5.1/PRD §6 -- D08 GST-on-fee rate error.

PRD-DEVIATION: PRD §6 describes D08 as settlement-file-vs-tax-invoice
reconciliation -- a batch-wide sum of GST-on-fee compared against a
separately-issued period tax invoice, two independently-sourced
documents that could disagree with each other. This implements
rate-correctness only: each payment's GST-on-MDR is recomputed from
the registered GST_ON_FEES rate and compared against what was actually
applied, the same shape as D01/D04/D05.

What this does NOT catch: an invoice that is itself wrong, independent
of the settlement file -- every per-payment figure could be internally
consistent with the registered rate while the aggregate invoice
Razorpay issues still disagrees with it. Building that check needs a
genuinely separate ingested artifact (a new source, a new adapter, a
schema change to source_file's CHECK constraint) -- and today's
generator has no mechanism to make an invoice wrong independent of the
settlement file, so that infrastructure would detect nothing currently
producible. Decided against building it for that reason, not as a time
shortcut -- see the session that made this call for the full cost
comparison (~7-9h for the literal version vs ~1.5-2h for this one, with
identical detection power against everything the generator injects).

Ground truth (plumb_gen/world.py): `true_gst_on_mdr_paise =
apply_bps(mdr_paise, GST_ON_FEES_BPS)`; D08's injector corrupts
`tax_paise_used` to a plausible wrong slab (`D08_WRONG_GST_BPS=1200`
vs. the correct `1800`) on `Payment.tax_paise`. This check recomputes
the same formula independently via `ctx.ratebook.rate_for(RateKind.
GST_ON_FEES, ...)` rather than trusting the applied figure.

NoApplicableRate: same accepted limitation as D04/D05 -- caught here
and converted to a decline (see d04.py's module docstring for the full
reasoning).
"""

from plumb.domain.money import apply_bps, sum_paise
from plumb.errors import NoApplicableRate
from plumb.rules.ratebook import RateKind
from plumb.verify.registry import CheckContext
from plumb.verify.trace import EvidenceRef, Finding, TraceBuilder, classify_severity
from plumb.verify.unit import Completeness, SettlementUnit

_APPLICABLE_COMPLETENESS = frozenset(
    {Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT}
)


class D08GstOnFeeRateError:
    defect_id = "D08"
    requires = _APPLICABLE_COMPLETENESS

    def applies_to(self, unit: SettlementUnit) -> bool:
        return bool(unit.payments)

    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None:
        try:
            rate = ctx.ratebook.rate_for(RateKind.GST_ON_FEES, ctx.as_of)
        except NoApplicableRate:
            return None  # accepted limitation -- see d04.py's module docstring

        expected_total = sum_paise(apply_bps(p.fee_paise, rate.rate_bps) for p in unit.payments)
        applied_total = sum_paise(p.tax_paise for p in unit.payments)
        delta = abs(applied_total - expected_total)
        if delta == 0:
            return None

        # Every order in this generator carries exactly one Payment, so
        # fee_total_paise's single-shot bps application equals the
        # per-payment sum above -- true today, not assumed; a future
        # multi-payment order would need this step re-derived per
        # payment instead of once over the total.
        fee_total_paise = sum_paise(p.fee_paise for p in unit.payments)
        trace = (
            TraceBuilder()
            .step(
                "expected_gst_on_fee",
                "(fee_total_paise * rate_bps + 5000) // 10000",
                {"fee_total_paise": fee_total_paise, "rate_bps": rate.rate_bps},
                expected_total,
            )
            .step("delta", "abs(applied_total - expected_total)", {"applied_total": applied_total, "expected_total": expected_total}, delta)
            .conclude(
                f"order {unit.order.order_id}: GST-on-fee applied {applied_total} paise vs expected "
                f"{expected_total} paise ({rate.rule_id}, {rate.rate_bps}bps); delta {delta} paise"
            )
        )
        return Finding(
            defect_id="D08",
            unit_id=unit.unit_id,
            severity=classify_severity(delta, ctx.config),
            amount_at_risk_paise=delta,
            on_matched_record=unit.match_id is not None,
            conclusion=trace.conclusion,
            trace=trace,
            evidence=(
                (EvidenceRef(unit.order.order_id, "order"), EvidenceRef(unit.intent.intent_id, "intent"))
                + tuple(EvidenceRef(p.payment_id, "payment") for p in unit.payments)
            ),
        )
