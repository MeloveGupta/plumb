"""LLD §5.1/PRD §6 -- D06 orphaned hold.

world.py's D06 injection: a transfer forced `on_hold=True,
on_hold_until_utc=None, settled_at_utc=None`, on an order forced 21-45
days old (`min(hold_release_days + 14, order_lookback_days) = min(21,
45) = 21`, config.py's defaults). Since settlement_recon/bank_credit are
only ever created together when `settled_at is not None`
(verify/unit.py's own `_classify` reasoning), a D06 unit always
classifies MISSING_SETTLEMENT.

Clean data structurally cannot produce this combination at all
(world.py's own module docstring: "on_hold=1 always comes with a real,
non-null on_hold_until_utc unless a defect assignment says otherwise")
-- so this check firing on a real T4 (null-set) batch would be a false
positive by construction; see
tests/plumb/verify/test_t4_null_set.py.

No spec gives a numeric age threshold -- `ctx.config.d06_hold_age_days`
is a placeholder constant (see VerifyConfig's own docstring). `Transfer`
carries no creation timestamp of its own (only `on_hold_until_utc`/
`settled_at_utc`, both null here), so `unit.order.placed_at_utc` is the
only usable age anchor, compared against `ctx.as_of`.
"""

from datetime import date

from plumb.domain.money import sum_paise
from plumb.verify.registry import CheckContext
from plumb.verify.trace import EvidenceRef, Finding, TraceBuilder, classify_severity
from plumb.verify.unit import Completeness, SettlementUnit


class D06OrphanedHold:
    defect_id = "D06"
    requires = frozenset({Completeness.MISSING_SETTLEMENT})

    def applies_to(self, unit: SettlementUnit) -> bool:
        return any(t.on_hold and t.on_hold_until_utc is None for t in unit.transfers)

    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None:
        orphaned = [t for t in unit.transfers if t.on_hold and t.on_hold_until_utc is None]
        placed_at = date.fromisoformat(unit.order.placed_at_utc[:10])
        age_days = (ctx.as_of - placed_at).days
        if age_days < ctx.config.d06_hold_age_days:
            return None  # a hold that hasn't had time to resolve yet -- not orphaned, just pending

        amount_at_risk = sum_paise(t.amount_paise for t in orphaned)

        # age_days is a business-rule gate (date arithmetic, not money),
        # same treatment as D02's tolerance-band check -- described in
        # the conclusion, not traced as a formal (re-evaluatable) step.
        trace = (
            TraceBuilder()
            .step("amount_at_risk", "amount_at_risk", {"amount_at_risk": amount_at_risk}, amount_at_risk)
            .conclude(
                f"order {unit.order.order_id}: {len(orphaned)} transfer(s) on hold with no release date, "
                f"{age_days} days old (threshold {ctx.config.d06_hold_age_days}); {amount_at_risk} paise parked"
            )
        )
        return Finding(
            defect_id="D06",
            unit_id=unit.unit_id,
            severity=classify_severity(amount_at_risk, ctx.config),
            amount_at_risk_paise=amount_at_risk,
            on_matched_record=unit.match_id is not None,
            conclusion=trace.conclusion,
            trace=trace,
            evidence=(
                (EvidenceRef(unit.order.order_id, "order"), EvidenceRef(unit.intent.intent_id, "intent"))
                + tuple(EvidenceRef(t.transfer_id, "transfer") for t in orphaned)
            ),
        )
