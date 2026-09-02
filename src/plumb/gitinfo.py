"""git provenance for the run manifest (TRD §4: `git_sha`, `git_dirty`).

`stub_engine.py` hard-codes zeros; a real run records the real commit
and whether the tree was dirty when it ran. A dirty tree stamps the
report PROVISIONAL downstream (plumb_eval/manifest.py) -- headline
numbers must come from a clean checkout.

Shells out to `git` rather than adding a dependency. If git isn't
available or this isn't a repo, `head_sha()` returns the all-zero sha
and `is_dirty()` returns True (fail safe -- an unknowable tree is not a
clean one).
"""

import subprocess
from pathlib import Path

_ZERO_SHA = "0" * 40


def _git(args: list[str], cwd: Path | None) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def head_sha(cwd: Path | None = None) -> str:
    result = _git(["rev-parse", "HEAD"], cwd)
    return result.strip() if result else _ZERO_SHA


def is_dirty(cwd: Path | None = None) -> bool:
    result = _git(["status", "--porcelain"], cwd)
    if result is None:
        return True
    return result.strip() != ""
