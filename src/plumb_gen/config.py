"""Every knob the generator needs is here, explicit -- no clock reads
anywhere in this package. batch_as_of is what "current date" means to the
generator; it never calls date.today() or datetime.now().

Rates are basis points as int (TRD §2 rule 3), not float -- caught by the
no-float lint on the first attempt at this file, which is exactly what
that lint exists to catch.
"""

from dataclasses import dataclass, field
from datetime import date

from plumb_gen.injection_config import InjectionConfig


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
    # PRD §8.2 tiers (T1-T4) -- messiness knobs, orthogonal to defect mix.
    # All default to 0/off so every existing config and test is untouched
    # until plumb_gen/tiers.py::apply_tier() explicitly sets one; never
    # written into config_a.yaml/config_b.yaml (see tiers.py's own
    # docstring for why tier and config stay separate axes).
    settlement_batch_rate_bps: int = 0  # T2 -- same-day settlements merge into one shared bank credit (many:1)
    settlement_split_rate_bps: int = 0  # T2 -- one settlement splits across two bank credits (1:many)
    # T2 -- genuine partial settlement: only a 30-70% fraction of the
    # money arrives in this batch at all; the rest is still in flight,
    # not just harder to see (that's settlement_split_rate_bps's job).
    # Distinct from splitting: PRD §8.2 lists them as separate failure
    # modes, and the truth record for an affected order is marked
    # resolvable_from_available_data=False, since the data genuinely
    # isn't all there yet -- not a matching puzzle to solve.
    settlement_in_flight_rate_bps: int = 0
    format_drift_rate_bps: int = 0  # T2 -- surface-format variation in the rendered source files
    adversarial_pair_count: int = 0  # T3 -- identical-amount/same-day order pairs, LLD §4.2's ambiguity trap
    # Empty by default -- every batch built so far (P0.6/P0.7) stays clean
    # with no config change. TRD §8.1's declarative defect injection.
    defects: InjectionConfig = field(default_factory=InjectionConfig)
