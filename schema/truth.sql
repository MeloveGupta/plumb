-- truth.sqlite DDL — BACKEND_SCHEMA.md §4. Written by plumb_gen, read only by
-- plumb_eval. The engine (src/plumb/) never opens this file — see TRD §3.1
-- and the ground-truth AST test.
PRAGMA foreign_keys = ON;

CREATE TABLE truth_record (
  record_key                     TEXT PRIMARY KEY,
  true_counterparts_json         TEXT NOT NULL CHECK(json_valid(true_counterparts_json)),
  true_obligation_json           TEXT NOT NULL CHECK(json_valid(true_obligation_json)),
  resolvable_from_available_data INTEGER NOT NULL CHECK(resolvable_from_available_data IN (0,1))
) STRICT;

CREATE TABLE injected_defect (
  instance_id          TEXT PRIMARY KEY,
  record_key           TEXT NOT NULL REFERENCES truth_record,
  defect_class         TEXT NOT NULL,
  amount_at_risk_paise INTEGER NOT NULL,
  within_tolerance     INTEGER NOT NULL CHECK(within_tolerance IN (0,1)),
  params_json          TEXT NOT NULL CHECK(json_valid(params_json))
) STRICT;
