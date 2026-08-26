"""LLD §5.3/PRD §6 -- D02 short settlement in tolerance. THE FLAGSHIP.

The two guards are transcribed exactly from LLD §5.3:
  - delta <= 0 -> None (not short)
  - NOT within the tolerance band -> None (an ordinary break the matcher
    already caught, not a silent one). D02 fires ONLY inside the band --
    that narrow window between "zero" and "the band" is the whole
    product thesis.

`ctx.tolerance` must be the exact plumb.domain.tolerance.ToleranceProfile
instance MatchEngine/PassP3 were constructed with (LLD §4.3/§12): two
independent implementations of band_paise() would make this defect
undetectable in exactly the cases that matter. Wire one ToleranceProfile
through MatchEngine, PassP3, and CheckContext from a single config
object at the top of a run -- never reconstruct it here.

`compute_expected_net`'s composition is read directly off
plumb_gen/world.py's own truth arithmetic, not designed from scratch:
  - transfer_amount_paise = gross - commission - mdr (world.py:264-267,
    "matches PRD §5.1's own worked example exactly ... TDS/TCS are
    tracked as a separate withholding obligation on intent, not
    subtracted here") -- so TDS/TCS must NOT be subtracted here, or every
    clean order would show a phantom shortfall.
  - debit_paise = dispute_debit_paise + refund_debit_paise (world.py:440)
    -- reversals are never netted into debit_paise (that's D07's signal,
    not D02's), so a reversal must not be subtracted here either.
  - MDR is trusted as Payment.fee_paise (observed), not independently
    recomputed -- no MDR rate-card model exists in this codebase (a
    separate gap from GST_ON_FEES, out of scope here).
The `min(refund_total + dispute_total, expected_transfer)` clamp is
algebraically identical to world.py's own two-step clamp (dispute first,
then refund clamped against what's left), since dispute_debit_paise is
itself always <= transfer_amount_paise by construction there.

This is also why MISSING_BANK units cannot produce a false finding for
a genuinely in-flight (T2) settlement: settlement_recon.credit_paise is
never reduced by the in-flight mechanism (only bank_credit is replaced
with a partial figure), so `actual` here -- computed from
unit.recon_rows, never from unit.bank_credit -- still reflects the full
target. expected ~= actual => delta <= 0 => this returns None.
"""

from plumb.domain.money import apply_bps, sum_paise
from plumb.verify.registry import CheckContext
from plumb.verify.trace import EvidenceRef, Finding, TraceBuilder, classify_severity
from plumb.verify.unit import Completeness, SettlementUnit


def compute_expected_net(unit: SettlementUnit, ctx: CheckContext) -> int:
    gross = unit.order.gross_paise
    commission_bps = unit.rate_card.commission_bps if unit.rate_card is not None else unit.intent.commission_rate_applied_bps
    commission = apply_bps(gross, commission_bps)
    mdr = sum_paise(p.fee_paise for p in unit.payments)
    expected_transfer = gross - commission - mdr

    refund_total = sum_paise(r.amount_paise for r in unit.refunds)
    dispute_total = sum_paise(d.deducted_amount_paise for d in unit.disputes)
    debit = min(refund_total + dispute_total, expected_transfer)
    return expected_transfer - debit


class D02ShortSettlementInTolerance:
    defect_id = "D02"
    requires = frozenset({Completeness.FULL, Completeness.MISSING_BANK})

    def applies_to(self, unit: SettlementUnit) -> bool:
        return bool(unit.recon_rows)

    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None:
        expected = compute_expected_net(unit, ctx)
        actual = sum_paise(r.credit_paise - r.debit_paise for r in unit.recon_rows)
        delta = expected - actual

        if delta <= 0:
            return None  # not short
        if not ctx.tolerance.within(expected, actual):
            return None  # outside the band -- already caught by the matcher, not a silent break

        trace = (
            TraceBuilder()
            .step(
                "expected_net",
                "gross_paise - commission - mdr - min(refund+dispute, expected_transfer)",
                {"gross_paise": unit.order.gross_paise},
                expected,
            )
            .step(
                "actual_net",
                "sum(recon.credit_paise - recon.debit_paise)",
                {"recon_rows": len(unit.recon_rows)},
                actual,
            )
            .step("delta", "expected_net - actual_net", {"expected": expected, "actual": actual}, delta)
            .conclude(
                f"order {unit.order.order_id}: expected net {expected} paise vs actual {actual} paise, "
                f"short by {delta} paise, inside tolerance band {ctx.tolerance.band_paise(expected)} paise"
            )
        )
        return Finding(
            defect_id="D02",
            unit_id=unit.unit_id,
            severity=classify_severity(delta, ctx.config),
            amount_at_risk_paise=delta,
            on_matched_record=unit.match_id is not None,
            conclusion=trace.conclusion,
            trace=trace,
            evidence=(
                (EvidenceRef(unit.order.order_id, "order"), EvidenceRef(unit.intent.intent_id, "intent"))
                + tuple(EvidenceRef(r.settlement_recon_id, "recon_row") for r in unit.recon_rows)
            ),
        )
