"""P0.9 -- config_loader.py is the only place a YAML file becomes a
GeneratorConfig. These tests hand-write the YAML and hand-compute the
expected dataclass, rather than round-tripping through the writer.
"""

from datetime import date

from plumb_gen.config_loader import load_generator_config
from plumb_gen.injection_config import DefectSpec


def test_loads_generator_fields_and_defects(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
        batch_size: 50
        refund_rate_bps: 900
        defects:
          D01: {count: 3, severity_range_paise: [1000, 20000]}
          D06: {count: 2}
        """
    )

    config = load_generator_config(
        config_path, seed=7, batch_id="batch_test", batch_as_of=date(2026, 1, 1)
    )

    assert config.seed == 7
    assert config.batch_id == "batch_test"
    assert config.batch_as_of == date(2026, 1, 1)
    assert config.batch_size == 50
    assert config.refund_rate_bps == 900
    # Untouched keys keep GeneratorConfig's own defaults.
    assert config.hold_rate_bps == 1500

    assert config.defects.defects == {
        "D01": DefectSpec(count=3, severity_range_paise=(1000, 20000)),
        "D06": DefectSpec(count=2, severity_range_paise=None),
    }


def test_tier_applies_after_yaml_loading(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("unparseable_narration_rate_bps: 800\n")

    config = load_generator_config(
        config_path, seed=7, batch_id="batch_test", batch_as_of=date(2026, 1, 1), tier="T4"
    )

    # T4 overrides narration regardless of what the YAML set it to.
    assert config.unparseable_narration_rate_bps == 0
    assert config.defects.total_count() == 0


def test_unknown_defect_id_raises(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
        defects:
          D09: {count: 1}
        """
    )

    try:
        load_generator_config(
            config_path, seed=1, batch_id="batch_test", batch_as_of=date(2026, 1, 1)
        )
    except ValueError as exc:
        assert "D09" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown defect id")
