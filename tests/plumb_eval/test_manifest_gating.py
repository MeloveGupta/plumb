"""TRD §8.3: refuses to score a run with a missing manifest, or with
git_dirty true, unless --allow-provisional is passed. Missing manifest
is always fatal (plan design decision #8) -- sample_label has no legal
fallback value if there's no manifest to read it from.
"""

import json

import pytest

from plumb_eval.manifest import DirtyTreeError, ManifestMissingError, gate, load_manifest


def _write_manifest(run_dir, **overrides):
    manifest = {"sample_label": "HELD_OUT", "git_dirty": False, **overrides}
    (run_dir / "manifest.json").write_text(json.dumps(manifest))


def test_load_manifest_returns_none_when_missing(tmp_path):
    assert load_manifest(tmp_path) is None


def test_load_manifest_reads_a_present_file(tmp_path):
    _write_manifest(tmp_path, sample_label="IN_SAMPLE")
    manifest = load_manifest(tmp_path)
    assert manifest["sample_label"] == "IN_SAMPLE"
    assert manifest["git_dirty"] is False


def test_load_manifest_rejects_an_illegal_sample_label(tmp_path):
    _write_manifest(tmp_path, sample_label="MOSTLY_HELD_OUT")
    with pytest.raises(ValueError, match="IN_SAMPLE or HELD_OUT"):
        load_manifest(tmp_path)


def test_gate_refuses_a_missing_manifest_even_with_allow_provisional(tmp_path):
    with pytest.raises(ManifestMissingError):
        gate(tmp_path, allow_provisional=True)
    with pytest.raises(ManifestMissingError):
        gate(tmp_path, allow_provisional=False)


def test_gate_refuses_a_dirty_tree_without_the_flag(tmp_path):
    _write_manifest(tmp_path, git_dirty=True)
    with pytest.raises(DirtyTreeError):
        gate(tmp_path, allow_provisional=False)


def test_gate_accepts_a_dirty_tree_with_the_flag_and_stamps_provisional(tmp_path):
    _write_manifest(tmp_path, git_dirty=True)
    manifest, is_provisional = gate(tmp_path, allow_provisional=True)
    assert is_provisional is True
    assert manifest["git_dirty"] is True


def test_gate_accepts_a_clean_tree_without_the_flag_and_is_not_provisional(tmp_path):
    _write_manifest(tmp_path, git_dirty=False)
    manifest, is_provisional = gate(tmp_path, allow_provisional=False)
    assert is_provisional is False


def test_gate_a_clean_tree_with_the_flag_is_still_not_provisional(tmp_path):
    # --allow-provisional only matters when the tree was actually dirty --
    # passing it on a clean run shouldn't retroactively mark the output.
    _write_manifest(tmp_path, git_dirty=False)
    _, is_provisional = gate(tmp_path, allow_provisional=True)
    assert is_provisional is False
