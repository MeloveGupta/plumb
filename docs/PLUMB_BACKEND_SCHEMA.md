# Plumb — Backend Schema

Fifth document. Implements `PLUMB_TRD.md` §2, §3, §10.

Three separate stores, mirroring the import boundary in code:

| Store | Written by | Contains truth? | Path |
|---|---|---|---|
| `dataset/` | `plumb_gen` | No | `data/{batch_id}/dataset/` |
| `truth.sqlite` | `plumb_gen` | **Yes** | `data/{batch_id}/truth/` |
| `run.sqlite` | `plumb` (engine) | No | `reports/{run_id}/` |
| `eval.sqlite` | `plumb_eval` | Reads truth | `reports/{run_id}/` |

**The engine reads `dataset/` and writes `run.sqlite`. It never opens `truth.sqlite`.** The store separation is the physical form of the AST import test — two independent guarantees for the same property.

---

## 1. Naming laws

These are not conventions. They are enforced by a schema-inspection test in CI.

| Law | Rule |
|---|---|
| **Money** | Any column holding money **must** end `_paise` and be `INTEGER`. No exceptions, no `_amount`, no `_inr`. |
| **Rates** | Must end `_bps` and be `INTEGER`. 0.1% → `10`. |
| **Time** | Must end `_utc`, stored as `TEXT` ISO-8601 with `Z`. SQLite has no datetime type; do not invent one. |
| **JSON** | Must end `_json`, `TEXT`, with a `CHECK(json_valid(...))`. |
| **Boolean** | `INTEGER` with `CHECK(x IN (0,1))`. |
| **Keys** | Every domain row's PK is `record_key`. |

### 1.1 Why the money law matters

`PRAGMA table_info` on any table proves the no-float rule holds. A panelist can verify our arithmetic discipline in one command without reading a line of Python:

```sql
SELECT name, type FROM pragma_table_info('finding')
WHERE name LIKE '%_paise' AND type != 'INTEGER';
-- must return zero rows, across every table
```

The CI test runs exactly that query against every table. **A `REAL` column anywhere in the schema fails the build.**

### 1.2 Record key format

Deterministic, seed-derived, zero-padded to 5. Prefix carries entity type, so a key is self-describing in a log line.

```
ord_00042   order            pay_00042   payment
oln_00042   order_line       rfnd_00042  refund
txfr_00042  transfer         rvsl_00042  reversal
disp_00042  dispute          setl_00042  settlement_recon
bank_00042  bank_credit      rate_00042  seller_rate_card
sel_00042   seller
```

Analysis IDs use the same shape: `mtch_`, `fnd_`, `exc_`, `hyp_`, `call_`, `unit_`.

**No `uuid4()`, no timestamps in IDs.** Byte-identical output for identical seeds (TRD §8.1) is impossible otherwise.

---

## 2. Source formats — deliberately heterogeneous

The three transactional sources arrive in **different formats with different vocabularies**, because that is the real problem. Normalising them is L0's actual job, not a formality.

| Source | Format | Character |
|---|---|---|
| Intent ledger | **CSV** | Platform DB export. `snake_case`, rupees as decimal strings, IST timestamps, seller names not IDs. |
| Razorpay | **JSON** | API response shape. Amounts in **paise already**, Unix epoch timestamps, `id` fields with `pay_`/`txfr_` prefixes. |
| Bank statement | **CSV** | Free-text `narration` column with the UTR embedded in a string. Date only, no time. Credits and debits in separate columns. |
| Seller master | **CSV** | Platform DB export, reference data, not per-order. `seller_id`, display name, category, current commission tier. The only place seller identity and rate-card data actually resolve — none of the three transactional sources carry either. Deliberately includes a display-name collision: two sellers, same name, different ids. |

Three units, three time formats, three identifier schemes, one of which is buried in prose. That is a faithful reproduction of the job. `sellers.csv` sits alongside as a fourth file, but not a fourth *transactional* source in that same sense — no timestamp to normalise, no per-order vocabulary drift. It's what makes the other three's seller identity resolvable at all, and, where two sellers share a name, honestly not always resolvable from a single record alone.

---

## 3. `run.sqlite` — engine output

Fresh database per run. **No migrations framework** (TRD §14). One DDL file, `schema/run.sql`, hashed into the manifest.

### 3.1 Provenance

```sql
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
```

`STRICT` on every table. It turns SQLite's type affinity into real type enforcement, which is what makes the money law a guarantee rather than a hope.

### 3.2 Ingest & provenance chain

```sql
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
```

**`raw_payload_json` preserves the source verbatim.** When the agent later investigates, "what did the file actually say before we touched it" is answerable. `transform_log` makes every normalisation inspectable evidence (App Flow §7) rather than an invisible mutation.

### 3.3 Canonical domain

Typed tables, not a polymorphic blob — a panelist will open this in a SQLite browser and it should read like a schema someone designed.

```sql
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

CREATE TABLE transfer (
  record_key        TEXT PRIMARY KEY REFERENCES record_index,
  payment_key       TEXT NOT NULL REFERENCES payment,
  linked_account_id TEXT NOT NULL,
  amount_paise      INTEGER NOT NULL,
  on_hold           INTEGER NOT NULL CHECK(on_hold IN (0,1)),
  on_hold_until_utc TEXT,            -- NULL + on_hold=1  ⇒  D06 candidate
  settled_at_utc    TEXT
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
```

`refund`, `reversal`, `dispute` follow the same shape.

Two schema details doing real work:

- **`transfer.on_hold_until_utc` nullable while `on_hold = 1`** is defect D06 expressed structurally. The orphaned hold is not a special case bolted on — it is a state the schema can represent, which is why it can occur naturally in generated data.
- **`bank_credit.utr` is nullable.** The bank does not give you a UTR column; it gives you a narration string. L0 must extract it, and sometimes fail. That nullable column is where a whole class of real matching pain lives.

### 3.4 Matching

```sql
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
```

**`ix_member_claimed_once` enforces "a record may be claimed exactly once" (TRD §5.2) at the database level.** A double-claim becomes an insert failure, not a subtle metric error discovered on day 12.

### 3.5 Verification

```sql
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
```

**`finding.on_matched_record` is the product's thesis as a column.** The CLI line *"of 31 findings: 24 on MATCHED records"* (App Flow §4) is `SELECT on_matched_record, COUNT(*) FROM finding GROUP BY 1`. Store it, don't derive it at render time.

### 3.6 Exceptions & agent

```sql
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
```

Three constraints worth calling out — each turns a policy from the PRD into something the database refuses to violate:

- **`model_claimed_outcome` + `was_downgraded` + `downgrade_reason`** record every firing of the downgrade gate (App Flow §3). `SELECT COUNT(*) FROM resolution WHERE was_downgraded=1` is a question a panelist will ask, and it should have a stored answer. It is also the cleanest possible evidence that code, not the model, decides the model's autonomy.
- **The final `CHECK`** makes an escalation without `what_would_resolve_it` an *insert failure*. PRD §10.4 called it mandatory; here it is enforced.
- **`resolution_evidence.record_key` is a foreign key into `record_index`.** A fabricated reference cannot be written. TRD §7.3's fabrication gate exists in application code; this is the same guarantee at the storage layer.

### 3.7 Terminal states & conservation

```sql
CREATE TABLE record_terminal_state (
  record_key    TEXT PRIMARY KEY REFERENCES record_index,
  terminal_state TEXT NOT NULL CHECK(terminal_state IN
    ('VERIFIED_CLEAN','AUTO_RESOLVED','PROPOSED',
     'ESCALATED_UNRESOLVED','QUARANTINED'))
) STRICT;

CREATE VIEW v_conservation AS
SELECT (SELECT COUNT(*) FROM record_index)          AS records_in,
       (SELECT COUNT(*) FROM record_terminal_state) AS accounted_for;
```

The conservation check printed every run (App Flow §3.1) is `SELECT * FROM v_conservation`. **If the two numbers differ, the run exits non-zero.** A record that reached no terminal state is a record we silently lost, which is the one failure a reconciliation product cannot survive.

### 3.8 Immutability

`run.sqlite` is an audit artifact. It is written once and never modified.

```sql
CREATE TRIGGER no_update_finding BEFORE UPDATE ON finding
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;

CREATE TRIGGER no_delete_finding BEFORE DELETE ON finding
BEGIN SELECT RAISE(ABORT, 'run.sqlite is append-only'); END;
```

Same pair on `resolution`, `agent_call`, `match_group`, `match_member`, `record_terminal_state`.

Backed by a CI test that greps `src/plumb/` for `UPDATE ` and `DELETE ` in SQL strings and fails on any hit. Two mechanisms, one property.

---

## 4. `truth.sqlite` — generator output, scorer only

```sql
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
```

`within_tolerance` is written by the generator **after reading the active tolerance profile** (TRD §8.1). Generator and engine cannot drift apart on what "within band" means, because there is one source for it.

---

## 5. `eval.sqlite` — scorer output

Separate file, written only by `plumb_eval`. It is the only store that joins engine output to truth.

```sql
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
```

**`scored_match.silent` is the headline metric's storage.** Silent-error rate (PRD §7.4) is `SELECT AVG(silent) FROM scored_match`. The number the entire product exists to drive down is one column and one query — make it that easy for a panelist to check.

`metric.unit` is mandatory because a bare `0.91` is ambiguous and every ambiguous number in a finance product is a question waiting to be asked.

---

## 6. JSONL artifacts

`run.sqlite` is the queryable store; the JSONL files are the readable ones. They are **projections of the database**, generated at report time — never a second source of truth.

```
findings.jsonl      one finding + full recompute_steps + evidence
resolutions.jsonl   one resolution + hypotheses + evidence chain
agent_calls.jsonl   one tool call
metrics.json        every metric with unit and sample_label
manifest.json       TRD §4
```

Contract: **every field in every JSONL line traces to a column.** A CI test round-trips a sample of lines back against the database and fails on any divergence. Report generators are where invented numbers get introduced; this closes that door.

Money appears in JSONL as `*_paise` integers. Rupee formatting happens only in Markdown, at the last moment (UI/UX §2.4).

---

## 7. Indexes

Small data, so index for the queries a *panelist* will run, not for speed:

```sql
CREATE INDEX ix_exception_rank      ON exception(queue_rank);
CREATE INDEX ix_exception_amount    ON exception(amount_at_risk_paise DESC);
CREATE INDEX ix_finding_defect      ON finding(defect_id);
CREATE INDEX ix_finding_on_matched  ON finding(on_matched_record);
CREATE INDEX ix_agent_call_exc      ON agent_call(exception_id, iteration);
CREATE INDEX ix_resolution_outcome  ON resolution(outcome);
CREATE INDEX ix_resolution_downgrade ON resolution(was_downgraded);
```

---

## 8. Schema tests — ship-blocking

1. Every `_paise` column is `INTEGER`; **no `REAL` column exists in any table** except `run.llm_temperature`, `match_group.confidence`, `resolution.confidence`
2. Every `_json` column has a `json_valid` CHECK
3. Every table declares `STRICT`
4. `UPDATE`/`DELETE` triggers present on all append-only tables
5. `ix_member_claimed_once` exists and is `UNIQUE`
6. Insert of an escalation without `what_would_resolve_it` raises
7. Insert of `resolution_evidence` with an unknown `record_key` raises
8. `v_conservation` returns equal counts after any successful run
9. `truth.sqlite` is never opened by any module under `src/plumb/` — assert on file handles in an integration test, not just imports
10. Full DDL applies to an empty file with zero warnings; `schema_sha256` matches the manifest

---

## 9. What is deliberately absent

| Absent | Why |
|---|---|
| Migrations framework | Fresh DB per run. Versioned by DDL hash. |
| ORM | Schema *is* the model. Pydantic validates at boundaries; hand-written SQL in between. |
| `updated_at` columns | Nothing is ever updated. |
| Soft deletes | Nothing is ever deleted. |
| Users, auth, tenancy | Single-operator tool. |
| Multi-currency | INR only. `currency` columns would be a lie about our scope. |
| Any `REAL` money column | The one that would quietly destroy the determinism guarantee. |

**The last row is the load-bearing one.** If a single money value becomes a float, `determinism_score` for L1/L2 stops being 1.000, the ablation's central contrast collapses, and the failure will look like a matcher bug for two days before anyone suspects the type.
