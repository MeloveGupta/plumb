"""BACKEND_SCHEMA.md §8, item 2.

Text-parse of schema/run.sql, paren-balanced per table block — same
technique as tests/test_schema_strict.py's find_non_strict_tables, applied
to a different property (json_valid CHECK presence instead of STRICT).
"""

import re

from plumb.store.ddl import SCHEMA_SQL

CREATE_TABLE_RE = re.compile(r'CREATE TABLE\s+"?(\w+)"?\s*\(', re.IGNORECASE)


def _table_blocks(sql_text: str) -> dict[str, str]:
    blocks = {}
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
        blocks[table_name] = sql_text[match.start() : i]
    return blocks


def find_json_columns_missing_check(sql_text: str) -> list[str]:
    violations = []
    for table, block in _table_blocks(sql_text).items():
        for col_match in re.finditer(r"(\w+_json)\s+TEXT", block):
            column = col_match.group(1)
            if f"json_valid({column})" not in block:
                violations.append(f"{table}.{column}")
    return violations


def test_every_json_column_in_the_real_schema_has_a_json_valid_check():
    assert find_json_columns_missing_check(SCHEMA_SQL) == []


def test_detector_catches_a_missing_check_in_a_fixture():
    fixture = """
    CREATE TABLE demo (
      value_json TEXT NOT NULL
    ) STRICT;
    """
    assert find_json_columns_missing_check(fixture) == ["demo.value_json"]
