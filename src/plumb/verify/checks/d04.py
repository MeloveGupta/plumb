"""LLD §5.1/PRD §6 -- D04 TCS basis error (gross vs net-of-returns only).

world.py's only D04 submode: TCS computed on gross_paise instead of
net_of_returns_paise (world.py:230-235). Clean path: true_tcs_paise =
apply_bps(net_of_returns_paise, TCS_BPS), computed at world.py:228,
before any refund logic runs. PRD §6 also describes "not an ECO" and
"wrong intra/inter-state split" submodes -- no is_eco/entity-type field
exists anywhere in domain/models.py, and Order.is_interstate (set at
world.py:175) is never read again anywhere in plumb_gen or plumb
(confirmed by grep). Both out of scope this session, same restraint
D03/D05 apply to their own PRD gaps.

*** KNOWN, ACCEPTED FALSE-POSITIVE SHAPE, confirmed against world.py, not
hypothetical -- ship-and-document was the repo owner's explicit decision
(session plan review): *** a given order's refunds list has at most one
entry -- world.py's refund logic is `if force_refund: ... elif defect_id
is None and ...: ...` (world.py:343-368), mutually exclusive. TCS is
computed at world.py:227-235, BEFORE the organic-refund branch at
:354-368 -- so for every non-D04 order, forced_refund_paise is 0 and
intent.expected_tcs_paise == apply_bps(gross_paise, TCS_BPS) REGARDLESS
of any organic refund that order later rolls. A net-of-all-refunds
recompute (below) therefore disagrees with world.py's own clean-path
truth specifically on a clean order with an organic refund. Worked
example: gross=200,000, organic refund=40,000 -> world truth
expected_tcs_paise=1,000; this check's recompute=800; delta=200 -- a
false D04 finding on data the generator's own labels call clean.

This is a gap in world.py's own truth model (TCS is computed before the
organic-refund roll, so "clean" data with an organic refund is not, by
strict TCS-law standard, actually net-of-returns-correct either), not a
flaw in this check's logic: real TCS law (PRD §5.2, Section 52 CGST Act)
nets ALL returns in the period, and no field distinguishes a forced
(D03/D04) refund from an organic one after the fact -- guessing a
heuristic to tell them apart would be exactly the kind of pattern-
guessing CLAUDE.md rule 4 forbids. Decided to ship the tax-law-correct
check as-is rather than change world.py's TCS sequencing (bigger blast
radius than this session's scope -- could shift previously-measured
metrics documented in HANDOFF.md). See
tests/plumb/verify/test_d04.py::test_clean_order_with_an_organic_refund_is_a_known_false_positive
for the fixture that demonstrates this explicitly, and the real-batch
measurement in this session's verification notes for the actual rate.

NoApplicableRate: Check.applies_to(self, unit) has no ctx (already
shipped, tested last session), so it structurally cannot pre-check rate
availability before run() runs. Caught here and converted to a decline
(return None) -- the only implementable option under the current
protocol. This loses the distinction between "checked, found nothing"
and "couldn't check, no rate for this date"; accepted as a known
limitation (session plan review) rather than revising the Check
protocol. Unreachable with any as_of this session's tests use -- TDS/TCS/
GST_ON_FEES all have effective_from years in the past and
effective_to=None.
"""

from plumb.domain.money import apply_bps, sum_paise
from plumb.errors import NoApplicableRate
from plumb.rules.ratebook import RateKind
from plumb.verify.registry import CheckContext
from plumb.verify.trace import EvidenceRef, Finding, TraceBuilder, classify_severity
from plumb.verify.unit import Completeness, SettlementUnit

_ALL_COMPLETENESS = frozenset(
    {Completeness.FULL, Completeness.MISSING_BANK, Completeness.MISSING_SETTLEMENT, Completeness.INTENT_ONLY}
)


class D04TcsBasisError:
    defect_id = "D04"
    requires = _ALL_COMPLETENESS

    def applies_to(self, unit: SettlementUnit) -> bool:
        return True

    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None:
        try:
            rate = ctx.ratebook.rate_for(RateKind.TCS, ctx.as_of)
        except NoApplicableRate:
            return None  # accepted limitation -- see module docstring

        gross = unit.order.gross_paise
        refund_total = sum_paise(r.amount_paise for r in unit.refunds)
        net_of_returns = gross - refund_total
        expected_tcs = apply_bps(net_of_returns, rate.rate_bps)
        applied_tcs = unit.intent.expected_tcs_paise
        delta = abs(applied_tcs - expected_tcs)
        if delta == 0:
            return None

        trace = (
            TraceBuilder()
            .step(
                "net_of_returns",
                "gross_paise - sum(refunds)",
                {"gross_paise": gross, "refund_total": refund_total},
                net_of_returns,
            )
            .step(
                "expected_tcs",
                f"net_of_returns * {rate.rate_bps}bps / 10000 (round-half-up)",
                {"net_of_returns": net_of_returns},
                expected_tcs,
            )
            .step("delta", "abs(applied_tcs - expected_tcs)", {"applied_tcs": applied_tcs, "expected_tcs": expected_tcs}, delta)
            .conclude(
                f"order {unit.order.order_id}: TCS applied {applied_tcs} paise vs expected {expected_tcs} paise "
                f"on net-of-returns basis ({rate.rule_id}, {rate.rate_bps}bps); delta {delta} paise"
            )
        )
        return Finding(
            defect_id="D04",
            unit_id=unit.unit_id,
            severity=classify_severity(delta, ctx.config),
            amount_at_risk_paise=delta,
            on_matched_record=unit.match_id is not None,
            conclusion=trace.conclusion,
            trace=trace,
            evidence=(
                (EvidenceRef(unit.order.order_id, "order"), EvidenceRef(unit.intent.intent_id, "intent"))
                + tuple(EvidenceRef(r.refund_id, "refund") for r in unit.refunds)
            ),
        )
