# Running the hybrid ablation arm

The `hybrid` arm makes live Anthropic API calls. It runs **locally,
with a key** — CI and everyone else replay the cassettes this produces
(TRD §9.1). Everything else — the persistence bridge, the scorer, the
`rules_only` baseline, the cassette replay layer, the determinism
harness — is already built and committed.

## Prerequisites

- `ANTHROPIC_API_KEY` in the environment.
- `uv sync` done, on a **clean git tree** (a dirty tree stamps the run
  `PROVISIONAL` and it can't be a headline number).
- The held-out batch:

```
plumb-gen --seed 42 --config configs/config_b.yaml --out data/batch_main_200 --tier T2
```

`data/` is gitignored and regenerable from the seed; don't commit it.

## The three commands

```
# 1. Record cassettes + run the hybrid arm (HELD_OUT)
ANTHROPIC_API_KEY=... plumb run \
  --data data/batch_main_200 --ablation hybrid --model-mode record \
  --sample-label HELD_OUT --seed 42 --generator-config configs/config_b.yaml

# 2. 5-run L3 determinism (PRD §7.9). Replays the step-1 cassettes,
#    so it needs no key and is fast. Writes determinism.json.
plumb run \
  --data data/batch_main_200 --ablation hybrid --repeat 5 \
  --sample-label HELD_OUT --seed 42 --generator-config configs/config_b.yaml

# 3. Score the step-1 run
plumb-eval --run reports/<hybrid_run_id_from_step_1> --truth data/batch_main_200/truth
```

Expected: `determinism_score` **< 1.000** (the Anthropic API has no
seed — a finding, not a defect; non-negotiable 8).

## Then

1. `git add -f fixtures/llm/ reports/<hybrid_run_id>/` and commit.
2. Fill `ABLATION.md` §4's `hybrid` row from
   `reports/<hybrid_run_id>/metrics.json` — at least:
   `over_abstention_rate`, `correct_abstention_rate`, `silent_error_rate`,
   `false_alarm_inr`, `residual_resolution_rate`,
   `escalated_unresolved_rate`, the outcome counts, and the L3
   `determinism_score` from `determinism.json`.
3. Evaluate the GATE P3 criterion (`ABLATION.md` §2) and the guardrails
   (§6):
   - **PASS** iff `over_abstention_rate(hybrid) < 0.341` **and**
     `correct_abstention_rate(hybrid) == 1.000` **and**
     `silent_error_rate(hybrid) <= 0.194` **and**
     `false_alarm_inr(hybrid) == 0`.
   - Read §6 first — the gate is soft; the guardrails and the magnitude
     are the substantive result.
4. Write `ABLATION.md` §5 the verdict. If it doesn't pass, ship the
   honest negative per `IMPLEMENTATION_PLAN.md` §5 — **do not tune
   toward a pass**, `config_b` is held out.
5. Confirm CI green (it now replays the committed cassettes).
