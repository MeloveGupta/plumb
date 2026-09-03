# Handoff — everything built except the keyed hybrid run

Written for a fresh session (or the user) that has the seven specs and
the committed code, not the conversation that produced them.

---

## 1. Where things stand

**GATE P0/P1/P2 met. P3.1–P3.7 complete. Persistence bridge, cassettes,
P4 close pack all built and committed.** The only open item is the
`hybrid` ablation run, which needs a live `ANTHROPIC_API_KEY` — see §3.

| piece | where |
|---|---|
| L0→L4 chain | `plumb/pipeline.py::execute_run`; CLI `plumb run` (`plumb/cli.py`) |
| run.sqlite writers (all tables) | `store/writer.py` + orchestrated by `plumb/run_writer.py::write_full_run` |
| manifest | `plumb/manifest_writer.py` (`prompt_sha256` is the new field) |
| L3 cassettes | `agent/model.py` — `CassetteClient` (replay), `RecordingClient` (record), `_request_key`; `CassetteMiss` in `errors.py`; `fixtures/llm/` committed empty |
| L3 determinism | `plumb run --repeat N` → `pipeline.run_repeated` → `determinism.json` |
| scorer fix | `plumb_eval` — see §2, justified in `docs/SCORING.md` |
| ablation metrics | `plumb_eval/metrics.py` — `residual_resolution_rate`, `escalated_unresolved_rate`, outcome counts |
| close pack | `report/reader.py` + `report/markdown.py` (`close.md`, `exceptions.md`) + `report/jsonl.py` + `report/pack.py`, wired into `execute_run` |

**Committed rules_only HELD_OUT baseline:**
`reports/2026-09-03T05:26:40Z-8abdcbb/` (config_b, seed 42, T2). Not
provisional. `over_abstention_rate 0.341` is the GATE P3 number.

Full suite: 499 passed, 1 xfailed (a long-standing unrelated xfail). CI
green with no API key.

---

## 2. The L1↔scorer contract fix — read `docs/SCORING.md` before touching scoring

`plumb_eval.score_all_matches` / `validate_no_fabrication` had never run
against real matcher output. The matcher's P0 groups the whole
`payment_id` chain (identity legs + order key + refund/dispute/reversal
satellites); truth closures were leg-only. Fixed on the scorer/truth
side: `world.py` adds the intent leg to `true_counterparts`;
`scoring.py::_is_settlement_identity` strips order + satellite keys
before the closure compare; evidence keys are validated against
`record_index` (TRD §8.3 verbatim) not truth closures;
`score_abstentions` dedupes per order. `docs/SCORING.md` is the
panel-facing justification with the substituted-leg demonstration. Do
**not** revert to "closures are leg-only".

---

## 3. The one open item — the `hybrid` run (needs a key)

`docs/RUN_HYBRID.md` has the three commands. In short:

1. `plumb run --ablation hybrid --model-mode record …` (keyed) — records
   `fixtures/llm/*`, runs the arm.
2. `plumb run --ablation hybrid --repeat 5 …` — L3 determinism (replays
   step-1 cassettes, no key). Expect `determinism_score` < 1.000.
3. `plumb-eval --run reports/<hybrid> --truth data/batch_main_200/truth`.

Then: commit `fixtures/llm/` + the hybrid run dir; fill `ABLATION.md`
§4's `hybrid` row and §5 the verdict.

**PASS** iff `over_abstention_rate(hybrid) < 0.341` **and**
`correct_abstention_rate == 1.000` **and** `silent_error_rate ≤ 0.194`
**and** `false_alarm_inr == 0`. Read `ABLATION.md` §6 first — the
`over_abstention_rate` gate is soft (rules_only escalates everything, so
the direction is near-foreordained); the guardrails holding and the
*magnitude* are the substantive result. If it doesn't pass, ship the
honest negative (`IMPLEMENTATION_PLAN.md` §5) — do not tune, config_b is
held out.

CI is already wired to replay whatever cassettes get committed.

---

## 4. Deviations (all carry `# *-DEVIATION:` comments)

| # | Spec | What we did | Where |
|---|---|---|---|
| 1 | PRD §9 3-arm ablation | 2-arm; `llm_only` cut (descope rung 5) | `ABLATION.md` §1 |
| 2 | TRD §7.4 prompt-hash, no field named | `prompt_sha256` manifest key | `manifest_writer.py` |
| 3 | GATE P3 "residual resolution", no metric | `over_abstention_rate` gates + guardrails + `residual_resolution_rate` reported | `ABLATION.md` §2, `metrics.py` |
| 4 | `settlement_unit.period` no source | derived `order.placed_at_utc[:7]` | `run_writer.py` |
| 5 | truth closures leg-only assumption | scorer fix — `docs/SCORING.md` | `scoring.py`, `truth_store.py`, `world.py` |
| 6 | `run.llm_temperature` REAL | `write_run_row` param unannotated (no-float lint) | `store/writer.py` |
| 7 | `report/markdown.py` — UIUX §4.2 ochre held line | no ANSI in a committed `.md`; held line gets weight from position + the `← N transfers, oldest N days` annotation | `report/markdown.py` |

Carried, still live: the "recorded data may be wrong" prompt
commitment, ambiguous-seller stays a scored abstention, D08 narrow,
trace re-eval is test-time only, T2 auto-match honestly under 85%.

---

## 5. Known rough edges (P4.5+ / not blocking)

- `wall_clock_seconds_total` reads 0.0 for a sub-second run → the
  50/200/500 scaling curve (TRD §11) is not built (cut by the user).
- No `history.jsonl`, no CI expansion beyond `uv run pytest`, no
  `Makefile`, no `ARCHITECTURE.md`. `docs/SCORING.md` can seed the
  latter.
- The close.md waterfall is legible text but not pixel-aligned on the
  decimal — a rendering nicety, not a correctness issue.

---

## 6. Session ritual

Push, confirm CI, then done. `DEVLOG.md` is the user's own — the thing
to flag this build: the scorer fix (§2), made under blocker pressure,
now justified in `docs/SCORING.md`.
