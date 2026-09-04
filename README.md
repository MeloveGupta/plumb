# Plumb

**For one settlement cycle, prove that what the platform *intended* to
happen (its own ledger) equals what *actually* happened (Razorpay)
equals what *arrived* (bank) — and surface, in rupees, everything that
doesn't.**

Reconciliation proves the numbers tie. Plumb proves they're right. A
settlement can reconcile perfectly and still be short.

Built for the finance lead at a marketplace that uses Razorpay Route to
split customer payments across sellers. Every competitor in this market
publishes an auto-match rate. Plumb measures **what the match rate is
hiding** — matches that look clean and are wrong, and money that goes
missing without ever raising an exception.

## Headline metrics — `HELD_OUT` (`config_b`, seed 42, tier T2, 200 records, tolerance `default_v1`)

| metric | `rules_only` | `hybrid` | |
|---|---|---|---|
| `auto_match_rate` | 0.79 | 0.79 | L1 — identical, L3 never re-matches |
| `match_precision` | 0.70 | 0.70 | matches scored against generator ground truth |
| `silent_error_rate` *(headline)* | 0.194 | *pending* | wrong auto-matches that raised no exception |
| `defect_recall` | 56 / 56 | 56 / 56 | injected defects D01–D08 caught by L2 |
| `defect_precision` / `root_cause_accuracy` | 1.00 / 1.00 | 1.00 / 1.00 | zero false alarms; every catch classified right |
| `leakage_caught_inr` | ₹24,375.98 | ₹24,375.98 | amount-at-risk of correctly identified defects |
| `false_alarm_inr` | ₹0.00 | *pending* | amount claimed on non-defects |
| `correct_abstention_rate` | 1.000 | *pending* | unresolvable cases correctly escalated |
| `over_abstention_rate` | 0.341 | *pending* | resolvable cases wrongly escalated |
| `residual_resolution_rate` | 0.000 | *pending* | share of the residual L3 resolves |
| L1/L2 `determinism_score` | 1.000 | 1.000 | pure functions, byte-identical across runs |
| L3 `determinism_score` | n/a | *pending* | expected < 1.000 — a finding, see `ABLATION.md` |

`rules_only` run: `reports/2026-09-03T05:26:40Z-8abdcbb/`. `hybrid` is
the LLM investigation arm — see `ABLATION.md` and `docs/RUN_HYBRID.md`.

## Reproduce

```
make reproduce
```

Clean clone, **no API key**. Generates from the committed seed, runs
both ablation arms (`hybrid` replays recorded cassettes), scores each
against generator ground truth, prints the metrics tables.

## What it does, in one run

```
plumb-gen --seed 42 --config configs/config_b.yaml --out data/batch_main_200 --tier T2
plumb run --data data/batch_main_200 --ablation rules_only --sample-label HELD_OUT \
          --seed 42 --generator-config configs/config_b.yaml
```
```
run_id            2026-09-03T05:26:40Z-8abdcbb
ablation          rules_only
exceptions        113
  AUTO_RESOLVED        0
  PROPOSED             0
  ESCALATED_UNRESOLVED 113
written           reports/2026-09-03T05:26:40Z-8abdcbb/
```

Each run writes `reports/<run_id>/`: `run.sqlite` (queryable evidence
store), `manifest.json` (reproducibility contract), `metrics.json/md`,
`close.md` (cash-position waterfall, ending on the on-hold bucket),
`exceptions.md` (every unresolved break, rupees-descending, with what
was tried and what would resolve it), and JSONL projections of the
database.

## Architecture

Five layers, one direction, no backward imports:

```
L0  ingest      3 heterogeneous sources → canonical            (pure)
L1  match       P0 identity → P3 tolerance band                (pure, no LLM)
L2  verify      recompute every obligation, D01–D08            (pure, no LLM)
L3  investigate agent, on L1's residual + L2's findings only   (LLM, only here)
L4  report      close pack, metrics, honest exception list
```

L1 and L2 are pure functions — same input, same output, `determinism_score`
exactly 1.000. The LLM runs only on what the deterministic layers could
not settle. `ARCHITECTURE.md` has the why, and the enforcement (an
AST-walking import-boundary test is what makes *"the model peeked at
the answers"* an unaskable question).

The L3 model client is
[`nvidia/nemotron-3.5-lightning-30b-a3b`](https://build.nvidia.com) via
an OpenAI-compatible endpoint — a build-time substitution for
`claude-sonnet-5`; see `docs/PLUMB_TRD.md` §7 and `ARCHITECTURE.md`.
Only the client changed.

## Layout

```
src/plumb/       the engine — never sees ground truth (CI-enforced)
src/plumb_gen/   the generator — writes ground truth from a seed
src/plumb_eval/  the scorer — reads ground truth, computes PRD §7 metrics
docs/            PRD, TRD, LLD, schema, UI/UX, app-flow, implementation plan
ABLATION.md      the LLM's value on the residual: prediction, then result
docs/SCORING.md  how matches and findings are scored against ground truth
```

MIT licensed. Python 3.12, `uv`.
