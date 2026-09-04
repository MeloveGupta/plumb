# CLAUDE.md

**Plumb** — a settlement assurance engine for Razorpay Route platforms.
Submission: Razorpay AI Buildathon, Track 04. **Target 4 Sep 2026, deadline 5 Sep.**

> Reconciliation proves the numbers tie. Plumb proves they're right.
> A settlement can reconcile perfectly and still be short.

---

## The twelve non-negotiables

Violating any of these silently invalidates the submission. If a task seems to require breaking one, stop and say so.

1. **Money is `int` paise. Never `float`, anywhere.** A single float breaks the L1/L2 determinism guarantee, and it will look like a matcher bug for two days before anyone suspects the type. The no-float lint covers all of `src/` except `report/` and `plumb_eval/` — the scorer's own ratio metrics (PRD §7) are the one legitimate exception, computed from already-integer inputs, never touching the money path itself.
2. **L1 (match) and L2 (verify) never call an LLM.** They are pure functions. `determinism_score` must be exactly `1.000`. The LLM lives only in L3.
3. **The engine never imports or opens `plumb_gen`, `plumb_eval`, or `truth.sqlite`.** Enforced by an AST test and by store separation. Do not work around either.
4. **Never fabricate a number.** No placeholders, no illustrative values, no "approximately". If a value isn't from a real run, print `NOT_MEASURED`.
5. **Exactly eight defect classes: D01–D08.** Depth, not breadth. Adding a ninth is descoping something else.
6. **It is a "cash position", never a "forecast".** We compute settled / in-flight / held. We do not predict.
7. **Deterministic paths use ordered structures, not `set`.** Python set iteration varies with hash randomisation. Use `list` + index, or `dict.fromkeys()`.
8. **L3's determinism below 1.000 is a finding, not a bug.** The hosted LLM (build.nvidia.com — see the deviation in `docs/PLUMB_TRD.md` §7) gives no bit-reproducibility guarantee at temperature 0, and no `seed` is passed even though the endpoint accepts one. Report the score. The contrast with L1/L2's 1.000 *is* the architecture argument. Do not engineer around it.
9. **Read-and-recommend only.** No write-back, no ledger mutation, no posting. `run.sqlite` is append-only.
10. **Tax constants live only in `rules/ratebook.py`**, each with statute, effective date, and source. Never inline a rate. Never "correct" a rate from a web search without checking §5.5 of the PRD first — several current-looking sources are stale.
11. **Every metric carries `HELD_OUT` or `IN_SAMPLE`. Every match rate is printed with its tolerance profile.** A match rate without its band is not a number.
12. **Disagree in a comment, not in the code.** If a spec seems wrong, implement it and leave `# PRD-DEVIATION:` or `# TRD-DEVIATION:` explaining why. Never diverge silently.

---

## Documents

This file lives at the repo root, not in `docs/` — Claude Code loads it automatically every session. Seven specs live in `docs/`. **Load one or two of those per session, never all of them** — context bloat causes exactly the drift this file prevents.

| Working on | Load |
|---|---|
| Anything | `CLAUDE.md` (this file, repo root, always loaded) |
| Product intent, metrics, defect list, test tiers | `PRD.md` |
| Stack, money rules, package layout, CI | `TRD.md` |
| Algorithms, signatures, module contracts | `LLD.md` |
| Tables, DDL, constraints | `BACKEND_SCHEMA.md` |
| CLI output, reports, visual design | `UIUX_BRIEF.md` |
| State machine, user journeys, video | `APP_FLOW.md` |
| What to build today, gates, descoping | `IMPLEMENTATION_PLAN.md` |

**`IMPLEMENTATION_PLAN.md` is the schedule.** Check the current phase before starting work.

---

## Architecture in six lines

```
L0  ingest      3 heterogeneous sources → canonical      (pure)
L1  match       P0 identity → P3 tolerance               (pure, no LLM)
L2  verify      recompute obligations, D01–D08           (pure, no LLM)
L3  investigate agent, residual + L2 findings only       (LLM here, only here)
L4  report      close pack, metrics, exception list
```

**L2 runs on matched records too.** That is the entire product. `MATCHED` is not a terminal state.

Dependency direction is strict: `ingest → match → verify → agent → report`. No backward imports.

---

## Session ritual

**Start:** state the acceptance criteria, not the task. *"Done when defect recall ≥ 80% on T2 and zero false alarms on T4"* produces better work than *"implement D04."*

**End:**
1. Tests green → commit. Never commit red.
2. Push. Confirm CI green before treating the session's work as done.
3. `DEVLOG.md` entry — what broke, what changed. Dated. The track asks what broke and how you recovered; this file cannot be reconstructed later.
4. Read any deviation comments added this session and decide on them.

---

## Drift watchlist

Things that creep in over long sessions. Check for them before committing.

| Drift | Correction |
|---|---|
| A float in a money path | Rule 1 |
| L1/L2 reaching for the LLM | Rule 2 |
| A ninth defect class | Rule 5 |
| "forecast" in output or docs | Rule 6 |
| Metrics hand-edited into a doc | Rule 4 — every number comes from a run |
| Money abbreviated (`₹1.2k`) | Always `₹1,200.00`, two decimals, right-aligned |
| Decorative colour in CLI or UI | Three semantic colours, one meaning each |
| README metrics drifting from `metrics.json` | CI check exists — run it |
| `uuid4()` or `time` in the generator | Breaks byte-identical reproduction |

---

## Commands

```bash
make reproduce          # THE command — clean clone, no API key, headline numbers
make test               # full suite
make gen SEED=42 CONFIG=config_b       # generate a batch
make run BATCH=batch_main_200 ABLATION=hybrid
make score RUN=<run_id>
make ablate             # all three arms, writes ABLATION.md
make determinism        # 5 runs, hash comparison
```

---

## Conventions

- **Commits:** plain, imperative, present tense. No AI attribution, no co-author trailers, no emoji. This repo is read by a hiring panel.
- **IDs:** deterministic, seed-derived, zero-padded — `ord_00042`, `exc_00031`. Never `uuid4()`.
- **Columns:** money ends `_paise` (INTEGER), rates end `_bps` (INTEGER), times end `_utc` (TEXT ISO-8601 Z), JSON ends `_json`.
- **Errors:** state what happened and what to do. No "Oops", no "Something went wrong", no exclamation marks.
- **Tests:** hand-compute expected values on paper first. Never generate an expected value from the code under test.

---

## What is deliberately absent

No ORM. No migrations. No async. No auth. No multi-currency. No charts. No write-back. No web UI unless every gate through P3 is green with slack to spare.

At this scale, **simple and legible beats scalable.** The panel reads code.
