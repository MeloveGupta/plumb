"""BACKEND_SCHEMA.md §8, item 10."""

import pytest

from plumb.store.ddl import open_run_db


def test_ddl_applies_clean_to_empty_file():
    conn = open_run_db(":memory:")
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert len(tables) > 0
    conn.close()


@pytest.mark.xfail(strict=True, reason="no manifest.json writer exists yet — run-orchestration layer, P3/P4")
def test_schema_sha256_matches_manifest():
    pytest.fail("no manifest.json writer exists yet to compare schema_sha256 against")
