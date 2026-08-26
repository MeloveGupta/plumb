"""PRD §8.2 -- apply_tier's overrides, hand-computed against
GeneratorConfig's own defaults, plus the no-op guarantee that keeps
every existing config/test untouched by this module's existence.
"""

from datetime import date

import pytest

from plumb_gen.config import GeneratorConfig
from plumb_gen.config_loader import load_generator_config
from plumb_gen.injection_config import DefectSpec, InjectionConfig
from plumb_gen.tiers import TIER_IDS, apply_tier

_BASE = GeneratorConfig(
    seed=42, batch_id="batch_test", refund_rate_bps=900, hold_rate_bps=1800,
    unparseable_narration_rate_bps=500, defects=InjectionConfig(defects={"D02": DefectSpec(count=10)}),
)


def test_tier_none_is_a_true_no_op():
    assert apply_tier(_BASE, None) == _BASE


def test_unknown_tier_raises():
    with pytest.raises(ValueError, match="T9"):
        apply_tier(_BASE, "T9")


def test_t1_zeroes_every_matching_difficulty_knob_but_leaves_config_owned_fields():
    result = apply_tier(_BASE, "T1")
    assert result.unparseable_narration_rate_bps == 0
    assert result.settlement_batch_rate_bps == 0
    assert result.settlement_split_rate_bps == 0
    assert result.format_drift_rate_bps == 0
    assert result.adversarial_pair_count == 0
    # config-owned fields untouched -- T1 is the matching ceiling, not a defect-free tier
    assert result.refund_rate_bps == 900
    assert result.hold_rate_bps == 1800
    assert result.defects.count_for("D02") == 10


def test_t2_raises_narration_and_enables_batching_split_and_drift():
    result = apply_tier(_BASE, "T2")
    assert result.unparseable_narration_rate_bps == 2000
    assert result.settlement_batch_rate_bps > 0
    assert result.settlement_split_rate_bps > 0
    assert result.format_drift_rate_bps > 0
    assert result.adversarial_pair_count == 0
    # config-owned fields untouched
    assert result.refund_rate_bps == 900
    assert result.defects.count_for("D02") == 10


def test_t3_enables_only_adversarial_pairs():
    result = apply_tier(_BASE, "T3")
    assert result.adversarial_pair_count == 5
    assert result.unparseable_narration_rate_bps == 0
    assert result.settlement_batch_rate_bps == 0
    assert result.settlement_split_rate_bps == 0
    assert result.format_drift_rate_bps == 0
    assert result.defects.count_for("D02") == 10  # config-owned, untouched


def test_t4_forces_narration_and_defects_to_zero_regardless_of_config():
    result = apply_tier(_BASE, "T4")
    assert result.unparseable_narration_rate_bps == 0
    assert result.defects.total_count() == 0  # overridden even though _BASE has D02: 10
    # non-defect business noise stays realistic -- T4 tests false-alarm
    # behaviour amid ordinary noise, not a sterile batch
    assert result.refund_rate_bps == 900
    assert result.hold_rate_bps == 1800


def test_every_tier_id_has_an_override_entry():
    from plumb_gen.tiers import TIER_OVERRIDES

    assert set(TIER_OVERRIDES) == set(TIER_IDS)


def test_tier_none_is_a_no_op_against_the_real_committed_configs(tmp_path):
    import shutil
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    for name in ("config_a.yaml", "config_b.yaml"):
        src = repo_root / "configs" / name
        dst = tmp_path / name
        shutil.copy(src, dst)

        untiered = load_generator_config(dst, seed=42, batch_id="b", batch_as_of=date(2026, 8, 20))
        explicit_none = load_generator_config(
            dst, seed=42, batch_id="b", batch_as_of=date(2026, 8, 20), tier=None
        )
        assert untiered == explicit_none
