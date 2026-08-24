"""P0.12 -- GATE P0's own criterion: "scorer produces a full metrics
table against a stub engine returning zero matches." Lives under
plumb/, not plumb_eval/, because it needs plumb.store.ddl.open_run_db,
which plumb_eval isn't allowed to import (TRD §3.1). Real, committed,
tested -- the shape P3's rules_only ablation arm reuses, not a test
double defined inline in a scorer test.

Writes a schema-valid run.sqlite with one `run` row and zero rows in
every other table -- literally "returns zero matches," nothing more.
No ingest, no matching, no verification: those are P1/P2's real jobs.

Also writes manifest.json alongside it (TRD §4's shape), since the
scorer can't proceed without one and no run-orchestration layer exists
yet to write one for real. This is a stand-in for that future writer,
not a permanent home for manifest-writing -- when a real orchestration
layer exists, its manifest writer belongs there, not here.

started_at_utc/finished_at_utc default to the real wall clock when the
caller doesn't supply them -- this is not the generator's "never read
the clock" rule (that's specifically about plumb_gen's seeded,
byte-identical dataset/truth output). A run's start time is genuinely
real-world data, exactly like TRD §4's own run_id example is
timestamp-derived. Tests that need a reproducible value pass one in.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from plumb.store.ddl import open_run_db


def write_stub_run(
    out_dir: Path,
    *,
    run_id: str,
    batch_id: str,
    generator_seed: int,
    generator_config_sha256: str,
    sample_label: str,
    git_dirty: bool = False,
    git_sha: str = "0" * 40,
    started_at_utc: str | None = None,
    finished_at_utc: str | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    if started_at_utc is None:
        started_at_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if finished_at_utc is None:
        finished_at_utc = started_at_utc

    conn = open_run_db(out_dir / "run.sqlite")
    conn.execute(
        """INSERT INTO run (run_id, plumb_version, git_sha, git_dirty, batch_id, generator_seed,
             generator_config_sha256, engine_config_sha256, schema_sha256, tolerance_profile,
             rules_module_version, ablation_config, sample_label, llm_model, llm_temperature,
             started_at_utc, finished_at_utc)
           VALUES (?, '0.1.0', ?, ?, ?, ?, ?, 'not_applicable', 'not_applicable', 'default_v1',
                   'not_applicable', 'rules_only', ?, NULL, NULL, ?, ?)""",
        (
            run_id, git_sha, int(git_dirty), batch_id, generator_seed,
            generator_config_sha256, sample_label, started_at_utc, finished_at_utc,
        ),
    )
    conn.commit()
    conn.close()

    manifest = {
        "run_id": run_id,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "generator_seed": generator_seed,
        "generator_config": None,
        "generator_config_sha256": generator_config_sha256,
        "engine_config_sha256": "not_applicable",
        "tolerance_profile": "default_v1",
        "rules_module_version": "not_applicable",
        "llm_model": None,
        "llm_temperature": None,
        "ablation_config": "rules_only",
        "sample_label": sample_label,
        "python_version": "3.12",
        "uv_lock_sha256": "not_applicable",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
