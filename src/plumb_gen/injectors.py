"""PRD §6 -- D01-D08, one small pure function per defect.

Each function computes the WRONG value plus the amount_at_risk_paise
judgment call documented here (also in the P0.8 plan). world.py calls
these at the point in _build_order where each defect needs to override a
value, and uses that wrong value everywhere else in the same construction
pass -- that's what keeps everything downstream consistent (a wrong
commission feeding both intent and transfer, not one patched after the
fact).

Defect-to-precondition map, enforced by world.py, not here:
  D01, D02, D05, D08  no forced precondition -- plain settled orders
  D03, D04             force a partial refund (net-of-returns needs one)
  D06                   force an aged hold, on_hold_until left null
  D07                   force a reversal with no preceding refund
"""

from dataclasses import dataclass, field
from random import Random

from plumb.domain.money import apply_bps
from plumb.domain.tolerance import ToleranceProfile
from plumb_gen.injection_config import InjectionConfig


@dataclass(frozen=True)
class DefectAssignment:
    defect_id: str
    params: dict[str, object] = field(default_factory=dict)


D01_DEFAULT_SEVERITY_RANGE_PAISE = (500, 50_000)


def assign_defects(rng: Random, batch_size: int, config: InjectionConfig) -> dict[int, DefectAssignment]:
    total = config.total_count()
    if total > batch_size:
        raise ValueError(f"requested {total} injected defects but batch_size is {batch_size}")

    indices = list(range(batch_size))
    rng.shuffle(indices)

    assignment: dict[int, DefectAssignment] = {}
    cursor = 0
    for defect_id in sorted(config.defects):  # sorted -- not dict iteration order, CLAUDE.md rule 7
        spec = config.defects[defect_id]
        for _ in range(spec.count):
            params: dict[str, object] = {}
            if defect_id == "D01":
                lo, hi = spec.severity_range_paise or D01_DEFAULT_SEVERITY_RANGE_PAISE
                params["target_delta_paise"] = rng.randint(lo, hi)
            assignment[indices[cursor]] = DefectAssignment(defect_id, params)
            cursor += 1
    return assignment


def d01_wrong_commission_bps(rng: Random, true_bps: int, gross_paise: int, target_delta_paise: int) -> int:
    """D01 COMMISSION_RATE_DRIFT. amount_at_risk = |wrong_commission -
    true_commission| -- the delta is the leakage itself: what was over-
    or under-deducted relative to the seller's contracted rate.
    """
    delta_bps = max(1, (target_delta_paise * 10_000) // max(gross_paise, 1))
    if true_bps - delta_bps > 0 and rng.randint(0, 1):
        return true_bps - delta_bps
    return true_bps + delta_bps


def d02_shortfall_paise(rng: Random, transfer_amount_paise: int, tolerance: ToleranceProfile) -> int:
    """D02 SHORT_SETTLEMENT_IN_TOLERANCE, the flagship. amount_at_risk =
    the shortfall itself, by construction.

    Strictly inside (0, band) -- LLD §5.3: D02 only fires when the
    shortfall is inside the tolerance band. Outside the band it's an
    ordinary break the matcher already catches, not the silent one this
    defect exists to model. band comes from the LIVE profile passed in,
    never a duplicated constant, so it can't drift from what the engine
    will actually check against.
    """
    band = tolerance.band_paise(transfer_amount_paise)
    high = max(1, band - 1)
    return rng.randint(1, high)


def d05_wrong_tds_paise(true_tds_paise: int, wrong_basis_paise: int, tds_bps: int) -> tuple[int, int]:
    """D05 TDS_RATE_OR_BASIS_ERROR (basis variant: net instead of gross).
    Returns (wrong_tds_paise, amount_at_risk_paise). amount_at_risk =
    |true - wrong|, same shape as D01/D04.
    """
    wrong_tds_paise = apply_bps(wrong_basis_paise, tds_bps)
    return wrong_tds_paise, abs(true_tds_paise - wrong_tds_paise)


def d08_wrong_tax_paise(true_tax_paise: int, mdr_paise: int, wrong_gst_bps: int) -> tuple[int, int]:
    """D08 GST_ON_MDR_INVOICE_MISMATCH, modeled per-order (see plan notes
    -- PRD frames this as a period-level sum-vs-invoice mismatch; nothing
    in this schema models a separate tax-invoice artifact or period
    aggregation, so a per-order GST-on-MDR delta stands in for it).
    amount_at_risk = |wrong_tax - true_tax|, standing in for the ITC
    exposure -- flagged as the more genuinely ambiguous of the eight.
    """

    wrong_tax_paise = apply_bps(mdr_paise, wrong_gst_bps)
    return wrong_tax_paise, abs(wrong_tax_paise - true_tax_paise)
