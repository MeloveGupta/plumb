"""BACKEND_SCHEMA.md §8, item 3 — every table declares STRICT.

STRICT turns SQLite's type affinity into real type enforcement — the
mechanism that makes the money law (int paise, no REAL) a guarantee on disk,
not just a Python-side hope.

Paren-balance walk, not a regex: CHECK(json_valid(value_json)) nests parens,
so a non-greedy regex up to the first ")" would truncate mid-statement.

Simplification: no string-literal awareness. A DEFAULT value containing an
unbalanced paren inside quotes would throw off depth counting. Acceptable
for DDL we author ourselves; flagged rather than assumed safe.
"""

import re
from pathlib import Path

import pytest

SCHEMA_DIR = Path(__file__).parent.parent / "schema"

CREATE_TABLE_RE = re.compile(r"CREATE TABLE\s+(\w+)\s*\(", re.IGNORECASE)


def find_non_strict_tables(sql_text: str) -> list[str]:
    violations: list[str] = []
    for match in CREATE_TABLE_RE.finditer(sql_text):
        table_name = match.group(1)
        depth = 1
        i = match.end()
        while depth > 0:
            if sql_text[i] == "(":
                depth += 1
            elif sql_text[i] == ")":
                depth -= 1
            i += 1
        remainder = sql_text[i:]
        semicolon = remainder.find(";")
        tail = remainder if semicolon == -1 else remainder[:semicolon]
        if "STRICT" not in tail.upper():
            violations.append(table_name)
    return violations


COMPLIANT_FIXTURE = """
CREATE TABLE run (
  run_id TEXT PRIMARY KEY,
  git_dirty INTEGER NOT NULL CHECK(git_dirty IN (0,1)),
  config_json TEXT NOT NULL CHECK(json_valid(config_json))
) STRICT;
"""

NON_COMPLIANT_FIXTURE = """
CREATE TABLE run (
  run_id TEXT PRIMARY KEY,
  git_dirty INTEGER NOT NULL CHECK(git_dirty IN (0,1))
);
"""


def test_strict_detector_passes_compliant_fixture():
    assert find_non_strict_tables(COMPLIANT_FIXTURE) == []


def test_strict_detector_catches_non_compliant_fixture():
    assert find_non_strict_tables(NON_COMPLIANT_FIXTURE) == ["run"]


@pytest.mark.xfail(strict=True, reason="schema/run.sql not committed yet — P0.3")
def test_all_committed_schema_files_declare_strict_on_every_table():
    sql_files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not sql_files:
        pytest.fail("no schema/*.sql files found — expected once P0.3 lands schema/run.sql")
    violations: list[str] = []
    for path in sql_files:
        for table in find_non_strict_tables(path.read_text()):
            violations.append(f"{path}: {table}")
    assert not violations, "\n".join(violations)
