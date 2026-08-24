"""TRD §8.1 -- YAML config loading, one file per generator run.

seed, batch_id, batch_as_of stay CLI-supplied (see cli.py) rather than
living in the YAML file, so one config (config_a.yaml / config_b.yaml)
is reusable across seeds. Everything else GeneratorConfig needs --
including the defect mix -- comes from the file, so config A and config
B differ by committed YAML content, not by a flag someone forgot to
pass.

# TRD-DEVIATION: TRD §8.1's inline example uses long descriptive defect
# keys (D01_COMMISSION_RATE_DRIFT), a `severity_range` field, and a
# `within_band` flag. None of that matches what P0.8 already shipped in
# injection_config.py: DEFECT_IDS are the short D01..D08 codes,
# DefectSpec's field is severity_range_paise, and there's no
# within_band knob -- D02's within-tolerance behaviour already reads
# the live tolerance profile unconditionally, it isn't a toggle. TRD
# gives no schema beyond that one illustrative snippet, so this loader
# matches the shipped dataclasses instead of the snippet, to avoid a
# YAML dialect that doesn't correspond to any real field.
"""

from datetime import date
from pathlib import Path

import yaml

from plumb_gen.config import GeneratorConfig
from plumb_gen.injection_config import DEFECT_IDS, DefectSpec, InjectionConfig


def load_generator_config(
    config_path: Path,
    *,
    seed: int,
    batch_id: str,
    batch_as_of: date,
) -> GeneratorConfig:
    raw = yaml.safe_load(config_path.read_text())
    defects_raw = raw.pop("defects", {})

    defects: dict[str, DefectSpec] = {}
    for defect_id, spec in defects_raw.items():
        if defect_id not in DEFECT_IDS:
            raise ValueError(
                f"{config_path}: unknown defect id {defect_id!r}, expected one of {DEFECT_IDS}"
            )
        severity_range = spec.get("severity_range_paise")
        defects[defect_id] = DefectSpec(
            count=spec["count"],
            severity_range_paise=tuple(severity_range) if severity_range else None,
        )

    return GeneratorConfig(
        seed=seed,
        batch_id=batch_id,
        batch_as_of=batch_as_of,
        defects=InjectionConfig(defects=defects),
        **raw,
    )
