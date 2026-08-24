# Plumb — Technical Requirements Document

Companion to `PLUMB_PRD.md`. The PRD defines *what* and *why*. This defines *how*, but only where the choice is load-bearing.

**Where this document is silent, use your judgment.** Where it is specific, it is specific for a reason — implement as written and leave a `# TRD-DEVIATION:` comment if you disagree.

---

## 1. Stack

| Concern | Choice | Why this and not the obvious alternative |
|---|---|---|
| Language | **Python 3.12** | Data-shaped problem; the scorer and metrics work is native here |
| Deps | **uv** + `pyproject.toml` + committed `uv.lock` | Reproducibility is a graded criterion; a lockfile is part of the argument |
| Models/validation | **Pydantic v2** | Schema violations must fail loudly at boundaries, not silently downstream |
| Money | **`int` paise. Never `float`. Never `Decimal` in storage.** | See §2 — this is non-negotiable |
| Store | **SQLite**, one file per run, committed for headline runs | Gives the panel a queryable evidence artifact, not just logs |
| Reports | **JSONL + Markdown**, generated | Machine-checkable and human-readable |
| CLI | **Typer** | |
| Tests | **pytest** + **hypothesis** | Property-based tests on the matcher are a strong signal and cheap |
| Aggregation | Plain Python for domain logic; **Polars** only in the report layer | Domain logic stays trivially auditable |
| CI | **GitHub Actions** | Must run **without any API key** — see §9 |
| LLM | Anthropic Messages API, **hand-rolled tool loop** | See §7.1 |

**Do not add a dependency without recording the reason in `ARCHITECTURE.md`.** A short dependency list is itself an argument for auditability.

---

## 2. Money representation — read this before writing any code

**All monetary values are `int`, in paise, everywhere in the system.**

This mirrors Razorpay's own API, which returns amounts in currency subunits. It is also the only representation under which the determinism guarantee in PRD §7.9 is achievable — floating-point arithmetic will silently break L1/L2's required `determinism_score = 1.000`.

Rules:

1. Ingest converts to `int` paise at the boundary. Nothing downstream sees rupees.
2. Rate application uses integer arithmetic with an **explicit, declared rounding policy**:
   ```python
   # ROUND_HALF_UP on the paise, applied once, at the point of computation.
   # Never round twice. Never round an intermediate.
   fee_paise = (amount_paise * rate_bps + 5000) // 10000
   ```
3. **Rates are expressed in basis points as `int`.** 0.1% → `10` bps. 0.5% → `50` bps. 18% → `1800` bps.
4. Rupee formatting happens only in the report layer, at the last moment.
5. A lint test asserts no `float` appears in any type annotation under `src/` except in `report/` and `plumb_eval/` — the scorer's PRD §7 ratio metrics are read-only and downstream of L1/L2, so they can't threaten the determinism guarantee this rule protects.

Every rounding decision is a defect the system is supposed to *catch*. If our own arithmetic is sloppy, we cannot tell our rounding from theirs.

---

## 3. Package layout & the ground-truth boundary

```
src/
  plumb/                 # THE ENGINE — must never see ground truth
    ingest/
    match/
    verify/
    agent/
    report/
    rules/               # tax module, PRD §5
    domain/              # pydantic models, PRD §4
  plumb_gen/             # generator — WRITES ground truth
  plumb_eval/            # scorer — READS ground truth
```

### 3.1 The boundary is enforced in CI, not by convention

```
plumb        →  may import: nothing from plumb_gen, plumb_eval
plumb_gen    →  may import: plumb.domain only
plumb_eval   →  may import: plumb.domain, plumb_gen
```

Implement as a test that walks the AST of every module under `src/plumb/` and fails on any import of `plumb_gen` or `plumb_eval`. This test runs in CI and must be present from commit one.

**This is the mechanism that makes "the model peeked at the answers" an unaskable question.** Say so in `ARCHITECTURE.md`.

### 3.2 Ground truth on disk

The generator writes two artifacts to separate paths:
```
/data/{batch_id}/dataset/        # engine input
/data/{batch_id}/truth/          # scorer only — gitignored from engine test fixtures
```
`truth/` is never passed to any engine entrypoint. The engine CLI takes `dataset/` as its only data argument.

---

## 4. Run manifest — reproducibility contract

Every run writes `reports/{run_id}/manifest.json` **before** anything else executes:

```json
{
  "run_id": "2026-08-28T14:22:03Z-a3f9c1",
  "git_sha": "…",
  "git_dirty": false,
  "generator_seed": 42,
  "generator_config": "config_b.yaml",
  "generator_config_sha256": "…",
  "engine_config_sha256": "…",
  "tolerance_profile": "default_v1",
  "rules_module_version": "2026-08-28",
  "llm_model": "claude-sonnet-5",
  "llm_temperature": 0.0,
  "ablation_config": "hybrid",
  "sample_label": "HELD_OUT",
  "python_version": "3.12.x",
  "uv_lock_sha256": "…"
}
```

**No number may appear in any report without a manifest alongside it.** If `git_dirty` is true, the report is stamped `PROVISIONAL` in its header. Headline submission numbers must come from a clean tree.

---

## 5. L0/L1 — ingest and matching

### 5.1 Ingest

Three adapters, one interface. Each declares its source vocabulary explicitly:

```python
class SourceAdapter(Protocol):
    source_id: str
    def load(self, path: Path) -> Iterable[RawRecord]: ...
    def normalise(self, raw: RawRecord) -> CanonicalRecord: ...
```

Normalisation handles, at minimum: date/timezone (everything to UTC, source tz declared per adapter), identifier casing and prefixes, amount units, counterparty name variants, and null/sentinel conventions.

**Every normalisation is logged as a transform record** with before/after. When the agent later investigates a break, "the normaliser did this to your data" must be inspectable evidence.

Unparseable rows go to a quarantine table with a reason — never dropped silently. Quarantine count appears in the report.

### 5.2 Matching passes

Ordered. Each record exits at the first pass that claims it.

| Pass | Rule ID prefix | Logic | Confidence |
|---|---|---|---|
| **P0** | `ID_` | Exact identifier join: `order_id`, `payment_id`, `transfer_id`, `utr` | 1.00 |
| **P1** | `EXACT_` | Exact composite: (amount, date, counterparty) all equal | 0.95 |
| **P2** | `GROUP_` | n:1 / 1:n grouped by `settlement_id`/`utr`, sum equality exact | 0.90 |
| **P3** | `TOL_` | Amount within tolerance band **and** date within window | 0.70 |
| **P4** | — | Residual → `UNMATCHED` | — |

Constraints:
- Confidence is a **deterministic function of pass and evidence count.** Never LLM-derived at this layer.
- Every match emits `rule_id`, `pass`, `confidence`, `evidence[]` (record keys used).
- A record may be claimed exactly once. Assert this.
- P2's group discovery must be deterministic — sort candidates by a stable key before subset search, and cap subset size (suggest 5) to bound the search.

### 5.3 Tolerance model

Declared in config, printed in every report header, versioned as a named profile:

```yaml
tolerance_profiles:
  default_v1:
    amount_abs_paise: 100        # ₹1
    amount_rel_bps: 10           # 0.1%
    # effective band = max(abs, rel * amount)
    date_window_days: 2
```

**This is load-bearing.** Defect D02 (`SHORT_SETTLEMENT_IN_TOLERANCE`) is *defined relative to this band*. If the band is undeclared or mutable at runtime, D02 is meaningless. The profile name goes in the manifest.

---

## 6. L2 — obligation verifier

### 6.1 Structure

```python
class Check(Protocol):
    defect_id: str            # D01…D08
    def applies_to(self, unit: SettlementUnit) -> bool: ...
    def run(self, unit: SettlementUnit) -> Finding | None: ...
```

Checks are independent, order-free, and individually unit-tested against hand-computed fixtures. `SettlementUnit` is the joined view of one order's full lifecycle across all three sources.

**L2 runs on matched records too.** This is the whole point — do not gate it behind `if unmatched`.

### 6.2 `recompute_trace` — mandatory on every finding

Structured, not prose. A human must be able to verify the arithmetic by hand:

```json
{
  "steps": [
    {"step": 1, "label": "gross order value",
     "formula": "sum(order_lines.taxable_value) + sum(order_lines.gst_amount)",
     "inputs": {"taxable": 100000, "gst": 18000}, "output": 118000},
    {"step": 2, "label": "contracted commission",
     "formula": "taxable * rate_bps / 10000",
     "inputs": {"taxable": 100000, "rate_bps": 1500,
                "rate_card_version": "v3", "effective_from": "2026-07-01"},
     "output": 15000},
    {"step": 3, "label": "expected vs actual",
     "formula": "expected - actual",
     "inputs": {"expected": 15000, "actual": 18000}, "output": -3000}
  ],
  "conclusion": "commission over-applied by 3000 paise",
  "amount_at_risk_inr": 30.00
}
```

Units in traces are **paise**; `amount_at_risk_inr` is the only rupee field.

### 6.3 Rules module (`plumb/rules/`)

Per PRD §5. Additional technical requirements:

- Every rate is a **time-bounded record**, not a constant:
  ```python
  RateRule(rate_bps=10, basis=Basis.GROSS,
           effective_from=date(2024,10,1), effective_to=None,
           provision="IT Act 2025 s.393(1) Sl.8(v), payment code 1035",
           legacy_provision="IT Act 1961 s.194-O",
           source_url="…", verified_on=date(2026,8,28))
  ```
- Lookups are **as-of the transaction date**, never "current". A June order uses June's rules.
- `Basis` is an enum: `GROSS` | `NET_OF_RETURNS` | `TAXABLE_VALUE`. Getting basis wrong is defects D04 and D05 — the code must make basis an explicit, unmissable parameter.
- Module header carries a `VERIFIED_ON` date. A test fails if it is more than 30 days before the run date, forcing a re-verification before submission.

---

## 7. L3 — the agent

### 7.1 Hand-rolled tool loop, not a framework

Use the Anthropic Messages API directly with an explicit tool-use loop.

**Reasoning, to be stated in `ARCHITECTURE.md`:** the evidence chain, the abstention decision, and the per-call audit log *are the product*. A framework's control flow would sit between us and the thing we are measuring. This is a control decision, consistent with the read-only posture.

Configuration:
- `temperature = 0.0`
- Model pinned via env var, default `claude-sonnet-5`, **exact string recorded in the manifest**
- Max tool-call iterations per exception: **8**, hard stop → forced `ESCALATED_UNRESOLVED`
- Token budget per exception, enforced; exceeding it is a forced escalation, logged as such

**Expect `determinism_score < 1.000` for L3 even at temperature 0.** Report it honestly. That gap, contrasted against L1/L2's 1.000, *is* the argument for the hybrid architecture — do not hide it or apologise for it.

### 7.2 Tool contract

All tools read-only, per PRD §10.3. Each returns a Pydantic model; no raw dicts to the model.

Every call logs:
```json
{"exception_id":"…","iteration":2,"tool":"fetch_refunds_for_payment",
 "args":{"payment_id":"pay_…"},"result_sha256":"…",
 "result_row_count":3,"latency_ms":42,"ts":"…"}
```

Tools **must not** accept free-form SQL or arbitrary paths. Fixed signatures only.

### 7.3 Required structured output

The agent's final answer is a tool call to `submit_resolution` with a validated schema — **not free text to be parsed**.

```python
class Resolution(BaseModel):
    exception_id: str
    outcome: Literal["AUTO_RESOLVED","PROPOSED","ESCALATED_UNRESOLVED"]
    confidence: float                      # 0..1
    hypotheses: list[Hypothesis]           # min 2 unless trivially determined
    chosen_hypothesis_index: int | None
    evidence_chain: list[EvidenceRef]      # must be non-empty
    amount_at_risk_paise: int
    what_was_tried: str
    what_would_resolve_it: str | None      # required if ESCALATED_UNRESOLVED
```

Validation rules, enforced in code and not left to the model:
- `AUTO_RESOLVED` requires `amount_at_risk_paise < auto_resolve_threshold` **and** `confidence >= confidence_threshold`. Both thresholds live in config and appear in the report. If either fails, the engine **downgrades** the outcome to `PROPOSED`. The model does not get the final say on its own autonomy.
- Every `EvidenceRef` must resolve to a real record key. Unresolvable references fail the run — this is the anti-fabrication gate.
- `ESCALATED_UNRESOLVED` without `what_would_resolve_it` is a validation error.

### 7.4 Prompt construction

- Ground the model **only** in retrieved evidence. No batch-wide context dumps.
- The system prompt states plainly that abstention is a valid, scored outcome and that fabricated resolutions are worse than escalations.
- Prompts live in versioned files under `src/plumb/agent/prompts/`, hashed into the manifest. A prompt change is a spec change.

### 7.5 `rules_only` ablation arm

L3 is bypassed entirely. All residual and all L2 findings emit `ESCALATED_UNRESOLVED` with `what_was_tried = "rules-only configuration"`. This must be a real code path exercised in CI, not a hand-edited report.

---

## 8. Generator & scorer

### 8.1 Generator

```
plumb-gen --seed 42 --config configs/config_b.yaml --out data/batch_main_200
```

- Seeded via `random.Random(seed)` instances passed explicitly. **No global `random` calls, no `time`-derived values, no `uuid4()`.** IDs are derived deterministically from the seed.
- Byte-identical output for identical (seed, config). Test this: generate twice, compare file hashes.
- Defect injection is declarative in config:
  ```yaml
  defects:
    D01_COMMISSION_RATE_DRIFT: {count: 6, severity_range: [500, 50000]}
    D02_SHORT_SETTLEMENT_IN_TOLERANCE: {count: 8, within_band: true}
  ```
- `within_band: true` for D02 means the injected shortfall is **generated relative to the active tolerance profile** — the generator imports the profile so the two cannot drift apart.
- Every emitted record carries `record_key`, stable across dataset and truth.

### 8.2 Truth schema

```json
{"record_key":"ord_00042",
 "true_counterparts":["pay_00042","txn_00042"],
 "true_obligation":{"commission_paise":15000,"tcs_paise":500,"tds_paise":118},
 "injected_defect":{"defect_id":"D01","amount_at_risk_paise":3000},
 "resolvable_from_available_data":true}
```

`resolvable_from_available_data` is set by the generator at injection time and drives the abstention metrics (PRD §7.7). Some defects must be deliberately injected as **unresolvable** — otherwise correct abstention cannot be measured.

### 8.3 Scorer

```
plumb-eval --run reports/{run_id} --truth data/{batch_id}/truth
```

- Joins on `record_key`. A key in engine output that is absent from the dataset **fails the run** — that is fabrication.
- Computes every metric in PRD §7 exactly as written.
- Emits `metrics.json` and a Markdown table.
- **Every metric row carries `IN_SAMPLE` or `HELD_OUT`**, read from the manifest. Not optional.
- Refuses to score a run whose manifest is missing or whose `git_dirty` is true unless `--allow-provisional` is passed, which stamps the output.

---

## 9. CI

`.github/workflows/eval.yml`, on every push:

1. `uv sync --locked`
2. Import-boundary AST test (§3.1)
3. No-float lint (§2.5)
4. Unit tests + hypothesis property tests
5. Generate T1–T4 from committed seeds
6. Run engine in `rules_only` **and** `hybrid`
7. Score both; append to `reports/history.jsonl`
8. **Fail the build** if: determinism of L1/L2 < 1.000; T4 false alarms > 0; match precision drops >2pp from the last committed run

### 9.1 CI must run without an API key

Non-negotiable — a panelist forking the repo must get a green build.

Record LLM interactions as **cassettes** (request hash → response JSON) under `fixtures/llm/`. CI runs in replay mode. A cassette miss in CI fails with a clear message telling the maintainer to re-record locally.

Live mode runs only locally, gated on `ANTHROPIC_API_KEY` being present.

### 9.2 Razorpay fixtures

Same pattern under `fixtures/razorpay/`. Recorded from test mode on day 1. **Nothing in the test or CI path may make a live Razorpay call.** Sanitise every recorded response — no key IDs, no account identifiers, no emails.

---

## 10. Reports

```
reports/{run_id}/
  manifest.json
  metrics.json
  findings.jsonl          # every L2 finding with recompute_trace
  resolutions.jsonl       # every L3 resolution with evidence chain
  agent_calls.jsonl       # every tool call
  exceptions.md           # the honest exception list
  close.md                # cash position waterfall
  run.sqlite              # queryable store
```

### 10.1 Exception list format

Sorted by `amount_at_risk` descending. Per entry: exception ID, defect class (or `UNMATCHED`), ₹ at risk, what was tried, what would resolve it, evidence chain, and outcome.

Header states totals: count escalated, ₹ escalated, and — importantly — **₹ escalated as a percentage of ₹ processed.** Do not bury the denominator.

### 10.2 Cash position

Waterfall, in this order, all reconciling to a stated closing figure:
```
gross collected
  − Razorpay fees        − GST on fees
  − platform commission  − TCS withheld      − TDS withheld
  − refunds  − reversals  − dispute debits
  = expected settleable
      of which: settled / in-flight (T+n) / ON HOLD
```

**Label it "cash position." Never "forecast."** The held bucket is a headline number — it is money the platform collected and cannot see.

---

## 11. Performance

At 500 records: L0+L1+L2 wall clock **under 10 seconds**, single-threaded. If it isn't, the algorithm is wrong — do not reach for concurrency.

L3 cost is dominated by the LLM. Report `llm_tokens_per_1000_records` and `inr_cost_per_1000_records` from actual usage figures returned by the API, never estimated.

Scaling curve at 50 / 200 / 500, plotted in the report.

---

## 12. Error handling

- **Fail loudly at boundaries.** Schema violations, unresolvable evidence references, and truth-join failures abort the run with a clear message.
- **Degrade gracefully inside L3.** A tool error, timeout, or budget exhaustion becomes `ESCALATED_UNRESOLVED` with the failure recorded in `what_was_tried`. One flaky call must never abort a batch.
- Structured JSON logs throughout, with `run_id` and `exception_id` on every line.
- The track asks what broke and how you recovered. **Keep `DEVLOG.md` from commit one** — dated entries, real failures, real fixes. Write it as you go; it cannot be reconstructed convincingly at the end.

---

## 13. Build order

Mirrors PRD §12. Additional technical gates:

| Phase | Technical gate |
|---|---|
| **P0** | Generator produces byte-identical output across two runs; scorer produces a full metrics table against a stub engine returning zero matches |
| **P1** | `determinism_score = 1.000` on L1 across 5 runs; hypothesis tests pass on the matcher; every match carries a resolvable evidence chain |
| **P2** | Every check has a hand-computed fixture test; rules module `VERIFIED_ON` set; zero false alarms on T4 |
| **P3** | Cassettes recorded; CI green with no API key; `rules_only` is a real exercised code path |
| **P4** | Fresh-clone reproduction on a clean container reproduces every headline number with one command |

### 13.1 Day 1, before any engine code

1. Razorpay test-mode account; Route linked accounts + stakeholder + product configuration started (approval latency is unknown — this is the longest-lead item)
2. Repo, CI skeleton, import-boundary test, no-float lint
3. `DEVLOG.md` first entry

---

## 14. Out of scope

Explicitly do not build: async/concurrency, a web UI, a database migration framework, multi-currency, auth, containerisation beyond a plain Dockerfile, plugin architectures, or any abstraction with exactly one implementation.

At this scale, **simple and legible beats scalable.** The panel reads code.
