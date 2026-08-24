"""BACKEND_SCHEMA.md §8, item 9: "truth.sqlite is never opened by any
module under src/plumb/ -- assert on file handles in an integration
test, not just imports." The AST import-boundary test already covers
imports; this is the physical companion BACKEND_SCHEMA itself calls
for -- run real plumb code and watch what sqlite3.connect actually
touches.

Was an xfail stub since P0.1: no code under src/plumb/ opened any file
at all, so there was nothing to assert against. P0.12's stub_engine.py
is the first real file-opening code under plumb/ (via
plumb.store.ddl.open_run_db), so this is no longer vacuous.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from plumb.stub_engine import write_stub_run


@contextmanager
def _track_sqlite_connections(monkeypatch):
    opened: list[str] = []
    real_connect = sqlite3.connect

    def _tracking_connect(database, *args, **kwargs):
        opened.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _tracking_connect)
    yield opened


def _opened_truth_sqlite(paths: list[str]) -> list[str]:
    return [p for p in paths if Path(p).name == "truth.sqlite"]


def test_detector_catches_a_direct_truth_sqlite_open(tmp_path, monkeypatch):
    # Proves the tracking mechanism itself actually catches a violation,
    # before trusting it to prove the real guard below passes for a real
    # reason and not because the detector is inert.
    with _track_sqlite_connections(monkeypatch) as opened:
        conn = sqlite3.connect(tmp_path / "truth.sqlite")
        conn.close()
    assert _opened_truth_sqlite(opened) == [str(tmp_path / "truth.sqlite")]


def test_truth_sqlite_never_opened_by_plumb_modules(tmp_path, monkeypatch):
    with _track_sqlite_connections(monkeypatch) as opened:
        write_stub_run(
            tmp_path,
            run_id="run_test",
            batch_id="batch_test",
            generator_seed=1,
            generator_config_sha256="deadbeef",
            sample_label="HELD_OUT",
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
        )
    assert opened  # not vacuously passing because nothing opened anything
    assert _opened_truth_sqlite(opened) == []
