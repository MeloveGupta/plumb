"""TRD §4 / §8.3 -- manifest gating.

Plan design decision #8: a missing manifest.json is always a hard
abort, regardless of --allow-provisional. sample_label is mandatory on
every metric row and must come from the manifest, not be passed by
hand -- if the manifest doesn't exist there's no third legal value to
fall back to. --allow-provisional only overrides the git_dirty=true
case, where a manifest *does* exist and is fully readable.
"""

import json
from pathlib import Path

REQUIRED_KEYS = ("sample_label", "git_dirty")


class ManifestMissingError(Exception):
    """No manifest.json in the run directory -- always fatal."""


class DirtyTreeError(Exception):
    """manifest.json says git_dirty=true and --allow-provisional wasn't passed."""


def load_manifest(run_dir: Path) -> dict | None:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text())
    missing = [k for k in REQUIRED_KEYS if k not in manifest]
    if missing:
        raise ValueError(f"{manifest_path}: missing required key(s) {missing}")
    if manifest["sample_label"] not in ("IN_SAMPLE", "HELD_OUT"):
        raise ValueError(
            f"{manifest_path}: sample_label must be IN_SAMPLE or HELD_OUT, got {manifest['sample_label']!r}"
        )
    return manifest


def gate(run_dir: Path, *, allow_provisional: bool) -> tuple[dict, bool]:
    """Returns (manifest, is_provisional)."""
    manifest = load_manifest(run_dir)
    if manifest is None:
        raise ManifestMissingError(
            f"no manifest.json in {run_dir} -- every run must write one before scoring (TRD §4); "
            "this cannot be worked around with --allow-provisional"
        )
    if manifest["git_dirty"] and not allow_provisional:
        raise DirtyTreeError(
            f"{run_dir / 'manifest.json'} says git_dirty=true -- pass --allow-provisional to score "
            "anyway (the output will be stamped PROVISIONAL)"
        )
    is_provisional = bool(manifest["git_dirty"]) and allow_provisional
    return manifest, is_provisional
