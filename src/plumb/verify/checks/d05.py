"""LLD §5.1/PRD §6 -- D05 TDS rate/basis error (net-vs-gross basis only).

world.py's only D05 submode: injectors.d05_wrong_tds_paise computes TDS
on the net TRANSFER amount instead of gross (world.py:250-256). Clean
path: true_tds_paise = apply_bps(gross_paise, TDS_BPS), computed at
world.py:227, before ANY refund logic runs and untouched by
forced_refund_paise -- TDS never involves refunds in this generator, so
this check has none of D04's organic-refund false-positive risk:
recomputing on unit.order.gross_paise alone matches world.py's true
formula for every order, no ambiguity.

PRD §6 also describes "legacy 1% rate," "missing," "non-PAN 5% floor,"
and "company threshold" submodes. No has_pan/entity_type/is_company
field exists anywhere in domain/models.py -- those four submodes cannot
be checked against this generator's data, a real, documented gap, not
implementable this session. "Legacy rate" and "missing" ARE structurally
exercised by this check's general recompute-and-compare shape even with
no generator support -- see the two hand-fixture-only tests in
tests/plumb/verify/test_d05.py, explicitly flagged there as unverifiable
against a real batch.

NoApplicableRate: same accepted limitation as D04 -- caught here and
converted to a decline (return None). See d04.py's module docstring for
the full reasoning (Check.applies_to has no ctx, so it cannot pre-check
rate availability before run() runs).
"""

from plumb.domain.money import apply_bps
from plumb.errors import NoApplicableRate
from plumb.rules.ratebook import RateKind
from plumb.verify.registry import CheckContext
from plumb.verify.trace import EvidenceRef, Finding, TraceBuilder, classify_severity
from plumb.verify.unit import Completeness, SettlementUnit

_ALL_COMPLETENESS = frozenset(
    {Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT, Completeness.INTENT_ONLY}
)


class D05TdsRateOrBasisError:
    defect_id = "D05"
    requires = _ALL_COMPLETENESS

    def applies_to(self, unit: SettlementUnit) -> bool:
        return True

    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None:
        try:
            rate = ctx.ratebook.rate_for(RateKind.TDS, ctx.as_of)
        except NoApplicableRate:
            return None  # accepted limitation -- see module docstring

        gross = unit.order.gross_paise
        expected_tds = apply_bps(gross, rate.rate_bps)
        applied_tds = unit.intent.expected_tds_paise
        delta = abs(applied_tds - expected_tds)
        if delta == 0:
            return None

        trace = (
            TraceBuilder()
            .step(
                "expected_tds",
                f"gross_paise * {rate.rate_bps}bps / 10000 (round-half-up)",
                {"gross_paise": gross},
                expected_tds,
            )
            .step("delta", "abs(applied_tds - expected_tds)", {"applied_tds": applied_tds, "expected_tds": expected_tds}, delta)
            .conclude(
                f"order {unit.order.order_id}: TDS applied {applied_tds} paise vs expected {expected_tds} paise "
                f"on gross basis ({rate.rule_id}, {rate.rate_bps}bps); delta {delta} paise"
            )
        )
        return Finding(
            defect_id="D05",
            unit_id=unit.unit_id,
            severity=classify_severity(delta, ctx.config),
            amount_at_risk_paise=delta,
            on_matched_record=unit.match_id is not None,
            conclusion=trace.conclusion,
            trace=trace,
            evidence=(EvidenceRef(unit.order.order_id, "order"), EvidenceRef(unit.intent.intent_id, "intent")),
        )
