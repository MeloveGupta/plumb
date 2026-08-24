"""TRD §8.1 -- byte-identical is the gate, tested the hard way: two full
runs to different output directories, file hashes compared. Not two
in-memory World objects compared with ==.

Hashes dataset/'s real three heterogeneous source files (P0.7) -- P0.6's
canonical JSON dump this test originally hashed has been retired now that
dataset/ holds the actual engine input.
"""

import hashlib
from pathlib import Path

from plumb_gen.config import GeneratorConfig
from plumb_gen.io import write_sources
from plumb_gen.world import build_world


def _generate_and_hash(seed: int, out_root: Path) -> dict[str, str]:
    out_dir = out_root / "dataset"
    world = build_world(GeneratorConfig(seed=seed, batch_id="batch_test"))
    write_sources(world, out_dir)
    hashes = {}
    for path in sorted(out_dir.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(out_dir))
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def test_same_seed_produces_byte_identical_output(tmp_path):
    hashes_a = _generate_and_hash(42, tmp_path / "run_a")
    hashes_b = _generate_and_hash(42, tmp_path / "run_b")
    assert hashes_a  # not vacuously comparing two empty dicts
    assert sorted(hashes_a.items()) == sorted(hashes_b.items())


def test_different_seed_produces_different_output(tmp_path):
    # Proves the determinism test above isn't trivially passing because
    # the generator ignores its seed entirely.
    hashes_a = _generate_and_hash(42, tmp_path / "run_a")
    hashes_c = _generate_and_hash(43, tmp_path / "run_c")
    assert hashes_a != hashes_c
