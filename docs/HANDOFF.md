# Handoff — end of the P3.1–P3.7 session (L3 agent machinery complete)

Written for a fresh session that has the seven specs and the committed
code, but not the conversation that produced them.

---

## 1. Where things stand

**GATE P0 met, P1 complete, P2 complete, GATE P2 met** — unchanged.

**P3.1–P3.7 are complete.** `src/plumb/agent/` now has the whole
single-exception investigation machinery, built and tested entirely
in-memory (same posture as P2's checks — no `run.sqlite` round trip):

| module | what |
|---|---|
| `agent/config.py` | `AgentConfig` — frozen Pydantic, the four thresholds |
| `agent/schema.py` | `StopReason`, `EvidenceRef`, `Hypothesis`, `Resolution` + its code-enforced invariants; `Resolution.downgrade()` |
| `agent/evidence.py` | `EvidenceStore` (the 7 tools' read-only backing store) + `RecordIndex` (fabrication-gate source of truth), both from `run_ingest()` output |
| `agent/tools.py` | `Toolbox` — the 7 PRD §10.3 tools, `invoke()` dispatch with degrade-to-`ToolFailure`, `AgentCall` audit records |
| `agent/prompts/` | `system.md` + `load_prompts()` → text + content-sensitive `sha256` |
| `agent/model.py` | `ModelClient` protocol; `ScriptedClient` (test double); `AnthropicClient` (live, never in CI) |
| `agent/loop.py` | `InvestigationState`, `investigate()` — LLD §7.2's loop; `forced_escalation()`, `grounding_refs()`, `SUBMIT_SCHEMA` |
| `agent/gates.py` | `apply_downgrade_gate()`, `assert_evidence_resolves()` |
| `agent/queue.py` | `Exception_`, `build_exception_queue()` — ranked rupees-descending |
| `agent/runner.py` | `run_investigation()` — works the queue, applies gates in fixed order; `ablation="rules_only"` bypass; optional `batch_token_budget` |

`anthropic` is now a locked dependency (imported lazily, only by
`AnthropicClient`). Full suite green (474 passed), CI green with no API
key — every loop test uses `ScriptedClient`, nothing hits the network.

**Next: the L3 persistence bridge, then P3.8–P3.12.** See §2.

---

## 2. The persistence bridge is the next task, and it is real work (~5–6h)

Deliberately deferred this session (with the user's sign-off). Nothing
in L3 writes `run.sqlite` yet. Before P3.8 (ablation) can run — it needs
a real `run.sqlite` for `plumb_eval.scorer.score_run` — someone must
build:

- `store/writer.py`: `write_settlement_unit`, `write_finding`,
  `write_recompute_step`, `write_finding_evidence` (P2's gap, still
  open), plus `write_exception`, `write_hypothesis`, `write_agent_call`,
  `write_resolution`, `write_resolution_evidence`, `write_record_index`,
  `write_record_terminal_state`, and the `run` row + `config_snapshot`.
- **`record_index` population** — every canonical record key, so the
  `exception.record_key` / `resolution_evidence.record_key` FKs resolve.
  `RecordIndex.from_ingest` already enumerates exactly this set; the
  writer walks the same records.
- **id reconciliation**: `build_exception_queue` takes
  `(finding_id, Finding)` pairs — the bridge writes findings first,
  gets their ids, then builds the queue. `Resolution.chosen_hypothesis_index`
  (int, in-memory) → `resolution.chosen_hypothesis_id` (FK): the bridge
  writes hypotheses, then maps.
- **the manifest writer** — `stub_engine.py` is the only current one and
  says so. It owns `prompt_sha256` (from `load_prompts().sha256`),
  `engine_config_sha256` (from `AgentConfig` — LLD §10's
  `PlumbConfig.sha256()` shape), `llm_model`, `llm_temperature` (from
  `model.TEMPERATURE`).
- **the orchestration CLI** — `plumb run --data <batch> --config <cfg>`,
  the L0→L4 chain that today exists only inside
  `tests/plumb_eval/test_gate_p2_real_batch.py` and
  `tests/plumb/agent/test_runner_integration.py`. `report/cli.py` gains
  an `L3 investigate` line.
- `record_model_turn` writes one `agent_call` per model turn carrying
  that turn's full token usage; per-tool rows carry 0. So
  `SUM(tokens_in + tokens_out)` over `agent_call` == true API usage.
  The bridge must preserve that when it writes the rows.

`plumb_eval` already reads `exception`, `resolution` (as `ResolutionRow`
— only `exception_id`/`outcome`/`stop_reason`), and `agent_call`
aggregates. `score_abstentions` already consumes `run.resolutions` for
the `CORRECT_ABSTENTION`/`OVER_ABSTENTION` split.
`CORRECT_RESOLUTION`/`WRONG_RESOLUTION` are still not scored (no
proposed-correction amount in the schema — separate, unscoped).

---

## 3. Deviations added this session (all carry `# *-DEVIATION:` comments)

| # | Spec | What we did | Where |
|---|---|---|---|
| 1 | TRD §7.3 `confidence: float` 0..1 | integer basis points `confidence_bps` 0..10000, same as `MatchGroup.confidence_bps`. The no-float lint covers `agent/`. Float appears only at the `resolution.confidence` REAL write (bridge task). | `agent/config.py`, `agent/schema.py` |
| 2 | LLD §10 `AgentConfig.temperature` | `model.py::TEMPERATURE = 0.0` module constant. Never anything but 0.0 (non-negotiable 8), and a `float` field trips the lint. | `agent/model.py` |
| 3 | PRD §10.3 `search_intent_ledger(query)` | structured `(order_id, seller_id)` filter, ≥1 required — TRD §7.2 forbids free-form queries. | `agent/tools.py` |
| 4 | PRD §10.4 "confidence > threshold" | `>=` — LLD §7.3's gate code is authoritative (downgrades when `<`). | `agent/gates.py` |
| 5 | TRD §7.4 "prompts hashed into the manifest", no field named | `load_prompts().sha256` exposed; bridge task adds `prompt_sha256` to `manifest.json`. | `agent/prompts/__init__.py` |
| 6 | TRD §7.3 `chosen_hypothesis_index` vs schema `chosen_hypothesis_id` FK | index kept in memory; id mapping is the bridge's job. | `agent/loop.py` |

**`model_claimed_outcome`** is stored as the single `TEXT` column the
schema already has (no `_json` variant exists). The full pre-downgrade
`Resolution` lives in memory only. If the panel wants the entire
claimed object persisted, that is a schema addition — not done.

---

## 4. Design decisions that aren't in any spec

- **Token attribution.** One `agent_call` per *model turn* carries that
  turn's full usage (`Toolbox.record_model_turn`); per-tool `agent_call`
  rows carry 0. Without this, a multi-tool turn double-counts against
  `llm_tokens_per_1000_records`. `state.tokens_in/out` is the
  authoritative running total for the budget check.

- **`amount_at_risk_paise` is never taken from the model.**
  `submit_resolution`'s schema doesn't include it; `finalise()` injects
  it from `exception.amount_at_risk_paise` (PRD §10.5 "no unsourced
  numbers"). The downgrade gate reads that injected value.

- **Budget check is before the call, with the reserve** (LLD §7.2 /
  §12.4). A single oversized turn can still blow the budget — the
  guarantee is only that the loop makes *no further* call once
  `budget_remaining < reserve_tokens`. Test:
  `test_budget_reserve_stops_before_the_next_call` (57k spend, 60k
  budget, stops) and `test_a_single_huge_turn_also_stops...`.

- **An invalid `submit_resolution` is fed back, not fatal.** The loop
  appends the `ValidationError` as an `is_error` tool result and lets
  the model correct it within the 8-iteration cap. Only the cap and the
  budget force a stop.

- **`grounding_refs(exc, gathered)`** — an escalation's evidence chain
  is whatever tools returned, else the finding's own evidence, else the
  exception's subject record. A FINDING exception with no evidence and
  nothing gathered raises `AssertionError` (upstream bug — L2 checks
  always attach evidence).

- **`_contested_key`** (queue.py) — for an `AmbiguousMatch`, the
  exception's `record_key` is the key the candidate sets *disagree*
  about (present in some, not all). The common chain members are not
  the contested record.

---

## 5. Carried forward from earlier handoffs — still live

- **HANDOFF §2 (the P2 handoff): "the recorded data may be wrong" is a
  first-class hypothesis.** This is now written into
  `agent/prompts/system.md` as commitment 3, with the reasoning. Three
  real generator bugs this build surfaced exactly because a
  disagreement was treated as informative. Keep it in the prompt.

- **Ambiguous-seller-name (old HANDOFF §4)** stays a scored
  correct-abstention. This session routes only the matcher's own
  `AmbiguousMatch` subsets (clean `exception.origin='UNMATCHED'` fit).
  Routing the ambiguous-seller case needs an `exception.origin` value
  that doesn't exist — a schema decision, still deferred. Do **not**
  build a heuristic to resolve the seller collision.

- **D08 is narrow by design** (old HANDOFF §3). `BatchCheck` stays
  retired.

- **`recompute_trace` re-evaluation is test-time only** (old HANDOFF
  §5). Any new check's `.step()` formula must be a literal executable
  expression over its own `inputs`.

- **T2 auto-match rate is 83.5% mean, honestly under GATE P1's 85%**,
  deliberately not tuned. Don't raise `settlement_in_flight_rate_bps`
  without the user's sign-off.

- **`ToleranceProfile` lives in `plumb/domain/tolerance.py`**, one
  instance shared. `match/passes.py`'s three-pool mechanism is
  authoritative.

---

## 6. Determinism note for the next session

L3's `determinism_score` will be **below 1.000** even at temperature 0
(no API seed). That is a finding to report (non-negotiable 8), and the
contrast with L1/L2's exact 1.000 is the architecture argument. There
is **no** 1.000 assertion on L3 anywhere in the tests, deliberately.
The 5-run L3 determinism harness (hash each record's final resolution,
per PRD §7.9) is P3.10/P3.11 work — it needs the persistence bridge
first (the harness reads `determinism_observation` rows).

The user drafts `DEVLOG.md` themselves — flag what broke, don't write
it for them. Nothing broke this session that isn't captured above.

---

## 7. Session ritual

Push and confirm CI before treating a session's work as done.
