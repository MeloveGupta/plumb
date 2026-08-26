"""PRD §8.2 -- T1-T4 messiness tiers, orthogonal to defect-mix config
(config_a.yaml/config_b.yaml). Tier controls how hard a batch is to
*match* (L1); config controls defect mix and general business-event
volume (L2 concerns). A T2 batch under config_b is a valid, meaningful
combination -- this module is what keeps that true.

Only `unparseable_narration_rate_bps` is shared between the two axes,
and tier always wins there when a tier is requested: it's the one
existing knob that actually determines matching difficulty (LLD
§3.2's narration-parse failure is what forces a record past P0 into
P1/P2/P3 at all), and P0.7 already established T4 zeroing it
regardless of config. Every other tier-controlled field
(settlement_batch_rate_bps, settlement_split_rate_bps,
settlement_in_flight_rate_bps, format_drift_rate_bps,
adversarial_pair_count) is new and tier-only -- never set via YAML, so
there is nothing for config to conflict with.

settlement_split_rate_bps and settlement_in_flight_rate_bps look
similar but are PRD §8.2's two distinct T2 failure modes, not one
feature at two settings: splitting always emits both halves of the
money within the batch (fully resolvable -- P2's job); in-flight
genuinely withholds a fraction of the money past batch_as_of (not
resolvable from this batch at all -- resolvable_from_available_data
=False, first real population for §7.7's abstention metrics). A
settlement gets at most one of {batched, split, in-flight}, never more
than one, per world.py's own per-settlement branching.

`defects` is untouched by every tier except T4: T1/T2/T3 paired with
any config keep that config's own defect mix (defects don't corrupt
identifiers, so a defect-bearing T1/T2/T3 batch is coherent, not a
contradiction). T4 forces `defects` empty regardless of config, since a
defect-bearing "null set" batch is a contradiction in terms, not a
combination to support.
"""

from dataclasses import replace

from plumb_gen.config import GeneratorConfig
from plumb_gen.injection_config import InjectionConfig

TIER_IDS = ("T1", "T2", "T3", "T4")

TIER_OVERRIDES: dict[str, dict[str, object]] = {
    "T1": {
        "unparseable_narration_rate_bps": 0,
        "settlement_batch_rate_bps": 0,
        "settlement_split_rate_bps": 0,
        "settlement_in_flight_rate_bps": 0,
        "format_drift_rate_bps": 0,
        "adversarial_pair_count": 0,
    },
    "T2": {
        "unparseable_narration_rate_bps": 2000,
        "settlement_batch_rate_bps": 2000,
        "settlement_split_rate_bps": 1000,
        # 15% of settled orders -- a starting estimate from the
        # order-level auto-match math (any one unresolved leg fails the
        # whole order), not tuned after seeing a result. See the honest
        # re-measurement in DEVLOG/HANDOFF for what this actually
        # produced.
        "settlement_in_flight_rate_bps": 1500,
        "format_drift_rate_bps": 2000,
        "adversarial_pair_count": 0,
    },
    "T3": {
        "unparseable_narration_rate_bps": 0,
        "settlement_batch_rate_bps": 0,
        "settlement_split_rate_bps": 0,
        "settlement_in_flight_rate_bps": 0,
        "format_drift_rate_bps": 0,
        "adversarial_pair_count": 5,
    },
    "T4": {
        "unparseable_narration_rate_bps": 0,
        "settlement_batch_rate_bps": 0,
        "settlement_split_rate_bps": 0,
        "settlement_in_flight_rate_bps": 0,
        "format_drift_rate_bps": 0,
        "adversarial_pair_count": 0,
        "defects": InjectionConfig(),
    },
}


def apply_tier(config: GeneratorConfig, tier: str | None) -> GeneratorConfig:
    """tier=None is a true no-op -- returns config unchanged, byte-identical
    to calling build_world(config) directly. This is what keeps every
    existing config/test untouched by this module's existence."""
    if tier is None:
        return config
    if tier not in TIER_OVERRIDES:
        raise ValueError(f"unknown tier {tier!r}, expected one of {TIER_IDS}")
    return replace(config, **TIER_OVERRIDES[tier])
