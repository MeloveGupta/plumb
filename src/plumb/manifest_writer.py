"""TRD §4 -- the reproducibility manifest, written before anything else
in a run executes ("No number may appear in any report without a
manifest alongside it").

`stub_engine.py` has the only other manifest writer and its docstring
says so: it's a GATE P0 stand-in "for that future writer". This is the
future writer. `plumb_eval/manifest.py` is the reader/gate on the other
end -- it requires `sample_label` and `git_dirty` and refuses to score
without them.

# TRD-DEVIATION: TRD §7.4 / IMPLEMENTATION_PLAN P3.2 say the prompt
# hash goes "into the manifest" but name no field. Written here as
# `prompt_sha256` (from agent.prompts.load_prompts().sha256).
"""

import hashlib
import json
import platform
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(
    run_dir: Path,
    *,
    run_id: str,
    git_sha: str,
    git_dirty: bool,
    generator_seed: int,
    generator_config: str,
    generator_config_sha256: str,
    engine_config_sha256: str,
    schema_sha256: str,
    prompt_sha256: str,
    tolerance_profile: str,
    rules_module_version: str,
    ablation_config: str,
    sample_label: str,
    llm_model: str | None,
    llm_temperature,
) -> None:
    uv_lock = _REPO_ROOT / "uv.lock"
    manifest = {
        "run_id": run_id,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "generator_seed": generator_seed,
        "generator_config": generator_config,
        "generator_config_sha256": generator_config_sha256,
        "engine_config_sha256": engine_config_sha256,
        "schema_sha256": schema_sha256,
        "prompt_sha256": prompt_sha256,
        "tolerance_profile": tolerance_profile,
        "rules_module_version": rules_module_version,
        "ablation_config": ablation_config,
        "sample_label": sample_label,
        "llm_model": llm_model,
        "llm_temperature": llm_temperature,
        "python_version": platform.python_version(),
        "uv_lock_sha256": _sha256_file(uv_lock) if uv_lock.exists() else "not_found",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
