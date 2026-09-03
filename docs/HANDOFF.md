# Handoff — persistence bridge done, rules_only baseline committed, hybrid arm next

Written for a fresh session that has the seven specs and the committed
code, not the conversation that produced them.

---

## 1. Where things stand

**GATE P0/P1/P2 met. P3.1–P3.7 complete.** Unchanged.

**The L3 persistence bridge is built and committed.** `plumb run`
exists and runs L0→L4 end to end:

| piece | where |
|---|---|
| L2/L3 run.sqlite writers | `store/writer.py` (record_index, "order", settlement_unit, finding, recompute_step, finding_evidence, exception, hypothesis, agent_call, resolution, resolution_evidence, record_terminal_state, run, config_snapshot) |
| the FK-ordered write-down | `plumb/run_writer.py::write_full_run` (orchestrator, top level, not under `store/`) |
| the L0→L4 chain | `plumb/pipeline.py::execute_run` |
| the CLI | `plumb/cli.py` — `plumb run --data <batch> --ablation rules_only|hybrid --sample-label ...` |
| manifest writer | `plumb/manifest_writer.py` (new field: `prompt_sha256`) |
| git provenance | `plumb/gitinfo.py` |
| `run_investigation` that keeps state | `agent/runner.py::run_investigation_traced` (returns `[(Resolution, InvestigationState|None)]`) |

**`plumb run --ablation rules_only` scores end to end** via
`plumb-eval` — real `metrics.json`, `v_conservation` balanced, not
provisional on a clean tree.

**The rules_only HELD_OUT baseline is committed**:
`reports/2026-09-03T05:26:40Z-8abdcbb/` (config_b, seed 42, T2). See
`ABLATION.md` §4 — `over_abstention_rate 0.341` is the GATE P3 number
`hybrid` must beat.

**The ablation prediction is committed** (`ABLATION.md` §3), before any
`hybrid` run. `llm_only` is cut (2-arm ablation) — reasoning in
`ABLATION.md` §1.

---

## 2. The L1↔scorer contract fix (this session) — understand it before touching scoring

`plumb_eval.score_all_matches` / `validate_no_fabrication` had **never
run against real matcher output**. GATE P1 tested only determinism;
GATE P2's test stubs `match_groups=[]`. When the bridge produced the
first real `run.sqlite`, `score_run` aborted.

Root cause: `match/engine.py` P0 groups the whole `payment_id` chain —
the settlement identity legs (intent/payment/transfer/settlement_recon/
bank_credit), **plus the order key**, **plus any refund/dispute/reversal
on the payment**. `plumb_eval/truth_store.py`'s closures were
payment+transfer(+settlement+bank) only.

Fix, all in `plumb_eval` + one generator line:
- `world.py`: `true_counterparts` now lists the intent leg too.
- `scoring.py::_is_settlement_identity` strips the order key and the
  `rfnd_`/`disp_`/`rvsl_`/`oln_` satellites before `score_match`'s
  closure comparison and in `validate_no_fabrication`'s identity check.
- Evidence keys + satellite keys are validated against
  `record_index` (now read into `RunData.record_index_keys`) instead of
  truth closures — L2 is a pure function over ingested data and cannot
  fabricate; L3's own gate already checked its evidence in process.
- `score_abstentions` dedupes per `order_key` (`is_resolvable` is a
  per-order signal) — without this `correct_abstention_rate` exceeded 1.0.

Do **not** revert any of this to "closures are leg-only". The matcher
P1 shipped disproves that assumption.

---

## 3. Deferred to THIS session's follow-on (the hybrid session, needs a live API key)

Cassettes (P3.10) and the determinism harness (P3.5-in-spirit) were
**not started** — descoped when the L1↔scorer fix landed on the
critical path. They do not block the rules_only baseline or the
committed prediction, and the hybrid session needs to build them first
anyway.

### Hybrid-session checklist

1. **Build the cassette layer** (`agent/model.py`): a third
   `ModelClient` — `CassetteClient` (replay, request-hash → response
   JSON under `fixtures/llm/`, `CassetteMiss` with a re-record message)
   + `RecordingClient` (wraps `AnthropicClient`, writes cassettes).
   `_request_key(system, messages, tools, model)` — sha256, temperature
   is constant so not in the key. Wire `pipeline._make_client` (already
   stubbed to import `CassetteClient`/`RecordingClient`). One test:
   record→replay round-trip + `CassetteMiss`.
2. **Build the L3 determinism harness**: `plumb run --repeat 5` or a
   `plumb-eval determinism --runs ...` subcommand. For each run, hash
   each resolution (canonical sorted-key JSON of outcome/confidence/
   chosen_hypothesis/what_was_tried/what_would_resolve_it/hypotheses),
   write `determinism_observation(run_index, record_key, resolution_hash)`
   keyed by the exception subject key. `scorer.score_run` passes those
   to `compute_metrics` when a `determinism/` sibling dir with ≥2 runs
   exists. `compute_determinism_score` already exists and is correct.
3. `plumb run --data data/batch_main_200 --ablation hybrid --record
   --sample-label HELD_OUT --seed 42 --generator-config configs/config_b.yaml`
   (needs `ANTHROPIC_API_KEY`). Commit `fixtures/llm/*`.
4. `plumb run ... --ablation hybrid --repeat 5` → the real L3
   `determinism_score` (expect < 1.000 — a finding, not a defect).
5. `plumb-eval --run reports/<hybrid_run> --truth data/batch_main_200/truth`.
6. Fill `ABLATION.md` §4 `hybrid` row and §5 the verdict:
   - PASS iff `over_abstention_rate(hybrid) < 0.341` AND
     `correct_abstention_rate(hybrid) == 1.000` AND
     `silent_error_rate(hybrid) ≤ 0.194` AND `false_alarm_inr(hybrid) == 0`.
   - If it doesn't pass: ship the honest negative per
     `IMPLEMENTATION_PLAN.md` §5 (deepen if diagnosable, else write it
     up plainly). Do not tune toward a pass — `config_b` is held out.
7. Confirm CI green replaying the committed cassettes.

---

## 4. Deviations added this session (all carry `# *-DEVIATION:` comments)

| # | Spec | What we did | Where |
|---|---|---|---|
| 1 | PRD §9 3-arm ablation | 2-arm (rules_only vs hybrid); llm_only cut, descope rung 5 | `ABLATION.md` §1 |
| 2 | TRD §7.4 "prompts hashed into manifest", no field named | new `prompt_sha256` key | `manifest_writer.py` |
| 3 | GATE P3 "residual resolution" (no metric anywhere) | `over_abstention_rate` gates + `residual_resolution_rate` reported + guardrails | `ABLATION.md` §2, `metrics.py` |
| 4 | `settlement_unit.period` (no source in verify's SettlementUnit) | derived `order.placed_at_utc[:7]` | `run_writer.py` |
| 5 | canonical detail tables | only `"order"` persisted (nothing else FKs them, scorer never reads them); close-pack detail tables are P4 | `run_writer.py` |
| 6 | `run.llm_temperature` REAL | `write_run_row`'s param is unannotated (no-float lint covers `store/`); value is `model.TEMPERATURE` (0.0) or None | `store/writer.py` |

Carried, still live: everything in the previous handoff §5 (the
"recorded data may be wrong" prompt commitment, ambiguous-seller stays a
scored abstention, D08 narrow, trace re-eval is test-time only, T2
auto-match honestly under 85%).

---

## 5. Known rough edges (not blocking, worth a pass in P4)

- `wall_clock_seconds_total` reads 0.0 for a sub-second run (second
  precision on the timestamps) → `records_per_second` NOT_MEASURED.
  Fine for rules_only; matters for TRD §11's 50/200/500 scaling curve.
- `reports/` and `data/` are gitignored; headline runs are
  `git add -f`'d. The committed baseline's `run.sqlite` is 1.3 MB.
- No `history.jsonl`, no CI expansion (still just `uv run pytest`),
  no `Makefile`, no `ARCHITECTURE.md` — all P4.

---

## 6. Session ritual

Push and confirm CI before treating a session's work as done.
`DEVLOG.md` is the user's own — flag what broke, don't write it.
