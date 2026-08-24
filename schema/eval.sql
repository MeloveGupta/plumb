-- eval.sqlite DDL — BACKEND_SCHEMA.md §5. Written only by plumb_eval, the
-- only store that joins engine output (run.sqlite) to truth (truth.sqlite).
-- The engine (src/plumb/) never opens this file, same boundary as truth.sqlite.
PRAGMA foreign_keys = ON;

CREATE TABLE metric (
  name         TEXT PRIMARY KEY,
  value_num    REAL,
  value_text   TEXT,
  unit         TEXT NOT NULL,           -- 'ratio' | 'paise' | 'count' | 'seconds' | 'tokens'
  sample_label TEXT NOT NULL CHECK(sample_label IN ('IN_SAMPLE','HELD_OUT'))
) STRICT;

CREATE TABLE scored_match (
  match_id TEXT PRIMARY KEY,
  verdict  TEXT NOT NULL CHECK(verdict IN ('TRUE_POSITIVE','FALSE_POSITIVE')),
  silent   INTEGER NOT NULL CHECK(silent IN (0,1))   -- wrong AND not flagged
) STRICT;

CREATE TABLE scored_defect (
  instance_id       TEXT PRIMARY KEY,
  was_detected      INTEGER NOT NULL CHECK(was_detected IN (0,1)),
  detected_finding_id TEXT,
  class_correct     INTEGER CHECK(class_correct IN (0,1))
) STRICT;

CREATE TABLE scored_abstention (
  exception_id TEXT PRIMARY KEY,
  verdict      TEXT NOT NULL CHECK(verdict IN
                 ('CORRECT_ABSTENTION','OVER_ABSTENTION',
                  'CORRECT_RESOLUTION','WRONG_RESOLUTION'))
) STRICT;

CREATE TABLE determinism_observation (
  run_index       INTEGER NOT NULL,
  record_key      TEXT NOT NULL,
  resolution_hash TEXT NOT NULL,
  PRIMARY KEY (run_index, record_key)
) STRICT;
