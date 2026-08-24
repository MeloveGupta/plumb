"""Every knob the generator needs is here, explicit -- no clock reads
anywhere in this package. batch_as_of is what "current date" means to the
generator; it never calls date.today() or datetime.now().

Rates are basis points as int (TRD §2 rule 3), not float -- caught by the
no-float lint on the first attempt at this file, which is exactly what
that lint exists to catch.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int
    batch_id: str
    batch_as_of: date = date(2026, 8, 20)
    batch_size: int = 200
    settlement_days: int = 3
    hold_release_days: int = 7
    order_lookback_days: int = 45
    interstate_rate_bps: int = 3000
    refund_rate_bps: int = 800
    full_refund_share_bps: int = 5000
    reversal_rate_of_full_refunds_bps: int = 4000
    dispute_rate_bps: int = 200
    hold_rate_bps: int = 1500
    # Rate of bank narrations that don't match any LLD §3.2 extraction
    # pattern. A parameter, not a constant, so T4 (null-set) can zero it
    # out without needing a code change -- an unparseable narration is
    # never a defect, but T4 sets this to 0 anyway rather than relying on
    # that distinction being argued later.
    unparseable_narration_rate_bps: int = 500
