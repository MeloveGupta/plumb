"""TRD §8.1 -- byte-identical is the gate, tested the hard way: two full
runs to different output directories, file hashes compared. Not two
in-memory World objects compared with ==.

Hashes both dataset/'s three heterogeneous source files (P0.7) and
truth/truth.sqlite (P0.9). Checked by hand before writing this test:
two independent sqlite3 files built from the identical write sequence
(fresh file, same INSERTs in the same order, no VACUUM, no incidental
timestamp anywhere in the write path) hash byte-identical -- so a raw
file hash is the real test here, not a weaker stand-in. If that ever
stops holding, this needs to become a row-content comparison (fetch
ordered by primary key, compare tuples) instead of silently degrading.
"""

import hashlib
from pathlib import Path

from plumb_gen.config import GeneratorConfig
from plumb_gen.injection_config import DefectSpec, InjectionConfig
from plumb_gen.io import write_sources
from plumb_gen.truth_db import write_truth
from plumb_gen.world import build_world

_DEFECTS = InjectionConfig(
    defects={
        "D01": DefectSpec(count=8, severity_range_paise=(1000, 40000)),
        "D02": DefectSpec(count=10),
        "D06": DefectSpec(count=4),
    }
)


def _generate_and_hash(seed: int, out_root: Path) -> dict[str, str]:
    config = GeneratorConfig(seed=seed, batch_id="batch_test", defects=_DEFECTS)
    world = build_world(config)
    write_sources(world, out_root / "dataset")
    truth_path = out_root / "truth" / "truth.sqlite"
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    write_truth(world, truth_path)

    hashes = {}
    for path in sorted(out_root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(out_root))
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def test_same_seed_produces_byte_identical_output(tmp_path):
    hashes_a = _generate_and_hash(42, tmp_path / "run_a")
    hashes_b = _generate_and_hash(42, tmp_path / "run_b")
    assert hashes_a  # not vacuously comparing two empty dicts
    assert "truth/truth.sqlite" in hashes_a
    assert sorted(hashes_a.items()) == sorted(hashes_b.items())


def test_different_seed_produces_different_output(tmp_path):
    # Proves the determinism test above isn't trivially passing because
    # the generator ignores its seed entirely.
    hashes_a = _generate_and_hash(42, tmp_path / "run_a")
    hashes_c = _generate_and_hash(43, tmp_path / "run_c")
    assert hashes_a != hashes_c
