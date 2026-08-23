-- run.sqlite DDL — BACKEND_SCHEMA.md §3. Fresh database per run, no migrations (TRD §14).
--
-- PRAGMA foreign_keys is per-connection, not persisted in the file — setting it
-- here only covers the connection that executes this script. Every connection
-- that opens run.sqlite, including reopens, must set it again; that is
-- src/plumb/store/ddl.py's job (open_run_db / open_existing_run_db), not this
-- file's. It's stated here too so the intent is visible to anyone reading the
-- DDL in isolation.
PRAGMA foreign_keys = ON;

-- §3.1 Provenance

CREATE TABLE run (
  run_id                 TEXT PRIMARY KEY,
  plumb_version          TEXT NOT NULL,
  git_sha                TEXT NOT NULL,
  git_dirty              INTEGER NOT NULL CHECK(git_dirty IN (0,1)),
  batch_id               TEXT NOT NULL,
  generator_seed         INTEGER NOT NULL,
  generator_config_sha256 TEXT NOT NULL,
  engine_config_sha256   TEXT NOT NULL,
  schema_sha256          TEXT NOT NULL,
  tolerance_profile      TEXT NOT NULL,
  rules_module_version   TEXT NOT NULL,
  ablation_config        TEXT NOT NULL
                         CHECK(ablation_config IN ('rules_only','llm_only','hybrid')),
  sample_label           TEXT NOT NULL
                         CHECK(sample_label IN ('IN_SAMPLE','HELD_OUT')),
  llm_model              TEXT,
  llm_temperature        REAL,        -- not money; exempt from the money law
  started_at_utc         TEXT NOT NULL,
  finished_at_utc        TEXT
) STRICT;

CREATE TABLE config_snapshot (
  key         TEXT PRIMARY KEY,
  value_json  TEXT NOT NULL CHECK(json_valid(value_json))
) STRICT;

-- §3.2 Ingest & provenance chain

CREATE TABLE source_file (
  source_file_id TEXT PRIMARY KEY,
  source_id      TEXT NOT NULL CHECK(source_id IN ('intent','razorpay','bank')),
  path           TEXT NOT NULL,
  sha256         TEXT NOT NULL,
  byte_size      INTEGER NOT NULL,
  row_count      INTEGER NOT NULL,
  format         TEXT NOT NULL
) STRICT;

CREATE TABLE raw_record (
  raw_id         TEXT PRIMARY KEY,
  source_file_id TEXT NOT NULL REFERENCES source_file,
  line_no        INTEGER NOT NULL,
  raw_payload_json TEXT NOT NULL CHECK(json_valid(raw_payload_json))
) STRICT;

CREATE TABLE transform_log (
  transform_id TEXT PRIMARY KEY,
  raw_id       TEXT NOT NULL REFERENCES raw_record,
  field        TEXT NOT NULL,
  before_text  TEXT,
  after_text   TEXT,
  rule_id      TEXT NOT NULL
) STRICT;

CREATE TABLE quarantine (
  raw_id       TEXT PRIMARY KEY REFERENCES raw_record,
  reason_code  TEXT NOT NULL,
  detail       TEXT NOT NULL
) STRICT;

-- §3.3 Canonical domain

CREATE TABLE record_index (
  record_key  TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  source_id   TEXT NOT NULL,
  raw_id      TEXT REFERENCES raw_record
) STRICT;

CREATE TABLE "order" (
  record_key            TEXT PRIMARY KEY REFERENCES record_index,
  seller_id             TEXT NOT NULL,
  gross_paise           INTEGER NOT NULL,
  category              TEXT NOT NULL,
  placed_at_utc         TEXT NOT NULL,
  status                TEXT NOT NULL,
  is_interstate         INTEGER NOT NULL CHECK(is_interstate IN (0,1))
) STRICT;

CREATE TABLE order_line (
  record_key      TEXT PRIMARY KEY REFERENCES record_index,
  order_key       TEXT NOT NULL REFERENCES "order",
  sku             TEXT NOT NULL,
  taxable_paise   INTEGER NOT NULL,
  gst_bps         INTEGER NOT NULL,
  gst_paise       INTEGER NOT NULL
) STRICT;

CREATE TABLE intent (
  record_key                TEXT PRIMARY KEY REFERENCES record_index,
  order_key                 TEXT NOT NULL REFERENCES "order",
  seller_id                 TEXT NOT NULL,
  expected_seller_paise     INTEGER NOT NULL,
  expected_commission_paise INTEGER NOT NULL,
  commission_bps_applied    INTEGER NOT NULL,
  expected_tcs_paise        INTEGER NOT NULL,
  expected_tds_paise        INTEGER NOT NULL,
  rate_card_version         TEXT NOT NULL
) STRICT;

CREATE TABLE payment (
  record_key     TEXT PRIMARY KEY REFERENCES record_index,
  order_key      TEXT NOT NULL REFERENCES "order",
  amount_paise   INTEGER NOT NULL,
  method         TEXT NOT NULL CHECK(method IN ('upi','card','netbanking','wallet')),
  status         TEXT NOT NULL,
  captured_at_utc TEXT,
  fee_paise      INTEGER NOT NULL DEFAULT 0,
  tax_paise      INTEGER NOT NULL DEFAULT 0
) STRICT;

-- BACKEND_SCHEMA.md §3.3 shows transfer explicitly and says refund/reversal/
-- dispute "follow the same shape" without giving their DDL. Authored here
-- from PRD §4's field lists plus this file's own established naming laws
-- (record_key PK into record_index, <parent>_key FK, _paise money, _utc time).

CREATE TABLE refund (
  record_key      TEXT PRIMARY KEY REFERENCES record_index,
  payment_key     TEXT NOT NULL REFERENCES payment,
  amount_paise    INTEGER NOT NULL,
  created_at_utc  TEXT NOT NULL
) STRICT;

CREATE TABLE transfer (
  record_key        TEXT PRIMARY KEY REFERENCES record_index,
  payment_key       TEXT NOT NULL REFERENCES payment,
  linked_account_id TEXT NOT NULL,
  amount_paise      INTEGER NOT NULL,
  on_hold           INTEGER NOT NULL CHECK(on_hold IN (0,1)),
  on_hold_until_utc TEXT,            -- NULL + on_hold=1  ⇒  D06 candidate
  settled_at_utc    TEXT
) STRICT;

CREATE TABLE reversal (
  record_key      TEXT PRIMARY KEY REFERENCES record_index,
  transfer_key    TEXT NOT NULL REFERENCES transfer,
  amount_paise    INTEGER NOT NULL,
  created_at_utc  TEXT NOT NULL
) STRICT;

CREATE TABLE dispute (
  record_key            TEXT PRIMARY KEY REFERENCES record_index,
  payment_key           TEXT NOT NULL REFERENCES payment,
  amount_paise          INTEGER NOT NULL,
  status                TEXT NOT NULL,
  deducted_amount_paise INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE settlement_recon (
  record_key     TEXT PRIMARY KEY REFERENCES record_index,
  entity_key     TEXT,
  entity_type    TEXT NOT NULL,
  settlement_id  TEXT NOT NULL,
  utr            TEXT NOT NULL,
  amount_paise   INTEGER NOT NULL,
  fee_paise      INTEGER NOT NULL DEFAULT 0,
  tax_paise      INTEGER NOT NULL DEFAULT 0,
  debit_paise    INTEGER NOT NULL DEFAULT 0,
  credit_paise   INTEGER NOT NULL DEFAULT 0,
  settled_at_utc TEXT NOT NULL,
  dispute_key    TEXT REFERENCES dispute
) STRICT;

CREATE TABLE bank_credit (
  record_key      TEXT PRIMARY KEY REFERENCES record_index,
  bank_ref        TEXT NOT NULL,
  utr             TEXT,             -- NULL until parsed out of narration
  amount_paise    INTEGER NOT NULL,
  credited_on     TEXT NOT NULL,    -- date only; the bank gives no time
  narration       TEXT NOT NULL
) STRICT;

CREATE TABLE seller_rate_card (
  record_key       TEXT PRIMARY KEY REFERENCES record_index,
  seller_id        TEXT NOT NULL,
  category         TEXT NOT NULL,
  commission_bps   INTEGER NOT NULL,
  effective_from   TEXT NOT NULL,
  effective_to     TEXT,
  version          TEXT NOT NULL
) STRICT;

CREATE UNIQUE INDEX ix_rate_card_period
  ON seller_rate_card(seller_id, category, effective_from);

-- §3.4 Matching

CREATE TABLE match_group (
  match_id    TEXT PRIMARY KEY,
  rule_id     TEXT NOT NULL,
  pass        TEXT NOT NULL CHECK(pass IN ('P0','P1','P2','P3')),
  confidence  REAL NOT NULL CHECK(confidence > 0 AND confidence <= 1)
) STRICT;

CREATE TABLE match_member (
  match_id   TEXT NOT NULL REFERENCES match_group,
  record_key TEXT NOT NULL REFERENCES record_index,
  side       TEXT NOT NULL CHECK(side IN ('intent','razorpay','bank')),
  PRIMARY KEY (match_id, record_key)
) STRICT;

CREATE UNIQUE INDEX ix_member_claimed_once ON match_member(record_key);

-- §3.5 Verification

CREATE TABLE settlement_unit (
  unit_id    TEXT PRIMARY KEY,
  order_key  TEXT NOT NULL REFERENCES "order",
  match_id   TEXT REFERENCES match_group,   -- NULL ⇒ unit built from unmatched
  seller_id  TEXT NOT NULL,
  period     TEXT NOT NULL
) STRICT;

CREATE TABLE finding (
  finding_id           TEXT PRIMARY KEY,
  unit_id              TEXT NOT NULL REFERENCES settlement_unit,
  defect_id            TEXT NOT NULL CHECK(defect_id IN
                         ('D01','D02','D03','D04','D05','D06','D07','D08')),
  severity             TEXT NOT NULL CHECK(severity IN ('low','medium','high')),
  amount_at_risk_paise INTEGER NOT NULL,
  on_matched_record    INTEGER NOT NULL CHECK(on_matched_record IN (0,1)),
  conclusion           TEXT NOT NULL
) STRICT;

CREATE TABLE recompute_step (
  finding_id   TEXT NOT NULL REFERENCES finding,
  step_no      INTEGER NOT NULL,
  label        TEXT NOT NULL,
  formula      TEXT NOT NULL,
  inputs_json  TEXT NOT NULL CHECK(json_valid(inputs_json)),
  output_paise INTEGER NOT NULL,
  PRIMARY KEY (finding_id, step_no)
) STRICT;

CREATE TABLE finding_evidence (
  finding_id TEXT NOT NULL REFERENCES finding,
  record_key TEXT NOT NULL REFERENCES record_index,
  role       TEXT NOT NULL,
  PRIMARY KEY (finding_id, record_key, role)
) STRICT;

-- §3.6 Exceptions & agent

CREATE TABLE exception (
  exception_id         TEXT PRIMARY KEY,
  origin               TEXT NOT NULL CHECK(origin IN ('UNMATCHED','FINDING')),
  record_key           TEXT REFERENCES record_index,   -- set when UNMATCHED
  finding_id           TEXT REFERENCES finding,        -- set when FINDING
  amount_at_risk_paise INTEGER NOT NULL,
  queue_rank           INTEGER NOT NULL,
  CHECK ((origin='UNMATCHED') = (record_key IS NOT NULL)),
  CHECK ((origin='FINDING')   = (finding_id IS NOT NULL))
) STRICT;

CREATE TABLE hypothesis (
  hypothesis_id TEXT PRIMARY KEY,
  exception_id  TEXT NOT NULL REFERENCES exception,
  rank          INTEGER NOT NULL,
  statement     TEXT NOT NULL,
  supports_json TEXT NOT NULL CHECK(json_valid(supports_json))
) STRICT;

CREATE TABLE agent_call (
  call_id          TEXT PRIMARY KEY,
  exception_id     TEXT NOT NULL REFERENCES exception,
  iteration        INTEGER NOT NULL CHECK(iteration BETWEEN 1 AND 8),
  tool             TEXT NOT NULL,
  args_json        TEXT NOT NULL CHECK(json_valid(args_json)),
  result_sha256    TEXT NOT NULL,
  result_row_count INTEGER NOT NULL,
  latency_ms       INTEGER NOT NULL,
  tokens_in        INTEGER NOT NULL,
  tokens_out       INTEGER NOT NULL,
  called_at_utc    TEXT NOT NULL
) STRICT;

CREATE TABLE resolution (
  exception_id          TEXT PRIMARY KEY REFERENCES exception,
  outcome               TEXT NOT NULL CHECK(outcome IN
                          ('AUTO_RESOLVED','PROPOSED','ESCALATED_UNRESOLVED')),
  model_claimed_outcome TEXT NOT NULL,
  was_downgraded        INTEGER NOT NULL CHECK(was_downgraded IN (0,1)),
  downgrade_reason      TEXT,
  confidence            REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  chosen_hypothesis_id  TEXT REFERENCES hypothesis,
  iterations_used       INTEGER NOT NULL,
  stop_reason           TEXT NOT NULL CHECK(stop_reason IN
                          ('sufficient_evidence','iteration_cap',
                           'budget_exhausted','tool_failure','rules_only')),
  what_was_tried        TEXT NOT NULL,
  what_would_resolve_it TEXT,
  CHECK (outcome != 'ESCALATED_UNRESOLVED' OR what_would_resolve_it IS NOT NULL)
) STRICT;

CREATE TABLE resolution_evidence (
  exception_id TEXT NOT NULL REFERENCES exception,
  record_key   TEXT NOT NULL REFERENCES record_index,
  role         TEXT NOT NULL,
  PRIMARY KEY (exception_id, record_key, role)
) STRICT;

-- §3.7 Terminal states & conservation

CREATE TABLE record_terminal_state (
  record_key    TEXT PRIMARY KEY REFERENCES record_index,
  terminal_state TEXT NOT NULL CHECK(terminal_state IN
    ('VERIFIED_CLEAN','AUTO_RESOLVED','PROPOSED',
     'ESCALATED_UNRESOLVED','QUARANTINED'))
) STRICT;

CREATE VIEW v_conservation AS
SELECT (SELECT COUNT(*) FROM record_index)          AS records_in,
       (SELECT COUNT(*) FROM record_terminal_state) AS accounted_for;

-- §3.8 Immutability — run.sqlite is an audit artifact, written once, never modified.

CREATE TRIGGER no_update_finding BEFORE UPDATE ON finding
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;
CREATE TRIGGER no_delete_finding BEFORE DELETE ON finding
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;

CREATE TRIGGER no_update_resolution BEFORE UPDATE ON resolution
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;
CREATE TRIGGER no_delete_resolution BEFORE DELETE ON resolution
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;

CREATE TRIGGER no_update_agent_call BEFORE UPDATE ON agent_call
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;
CREATE TRIGGER no_delete_agent_call BEFORE DELETE ON agent_call
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;

CREATE TRIGGER no_update_match_group BEFORE UPDATE ON match_group
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;
CREATE TRIGGER no_delete_match_group BEFORE DELETE ON match_group
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;

CREATE TRIGGER no_update_match_member BEFORE UPDATE ON match_member
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;
CREATE TRIGGER no_delete_match_member BEFORE DELETE ON match_member
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;

CREATE TRIGGER no_update_record_terminal_state BEFORE UPDATE ON record_terminal_state
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;
CREATE TRIGGER no_delete_record_terminal_state BEFORE DELETE ON record_terminal_state
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;
