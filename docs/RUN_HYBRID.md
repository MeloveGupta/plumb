# Running / re-recording the hybrid ablation arm

L3 runs against **build.nvidia.com** —
`nvidia/nemotron-3.5-lightning-30b-a3b`, an OpenAI-compatible
`chat/completions` endpoint (see the deviation in `docs/PLUMB_TRD.md`
§7). The `--record` step makes live calls and needs a key; everyone
else replays the committed cassettes with no key.

## Prerequisites

- `NVIDIA_API_KEY` in the environment, on an account entitled to run
  that model (`curl` it first — many build.nvidia.com keys 404 with
  "not entitled for account").
- Clean git tree (a dirty tree stamps the run `PROVISIONAL`).
- The held-out batch (regenerable, gitignored):

```
plumb-gen --seed 42 --config configs/config_b.yaml --out data/batch_main_200 --tier T2
```

## The sequence

```
# 1. Record the cassettes (live calls). Resumable -- re-run on a
#    rate-limit / credit / timeout stall; existing cassettes aren't re-paid.
NVIDIA_API_KEY=... plumb run --data data/batch_main_200 --ablation hybrid \
  --model-mode record --sample-label HELD_OUT --seed 42 \
  --generator-config configs/config_b.yaml

git add -f fixtures/llm/ && git commit -m "record hybrid cassettes"

# 2. The headline hybrid run -- replay, clean tree, not provisional
plumb run --data data/batch_main_200 --ablation hybrid --model-mode replay \
  --sample-label HELD_OUT --seed 42 --generator-config configs/config_b.yaml

# 3. L3 determinism across 5 runs (replay -- free, no key). Writes determinism.json.
plumb run --data data/batch_main_200 --ablation hybrid --repeat 5 \
  --sample-label HELD_OUT --seed 42 --generator-config configs/config_b.yaml

# 4. Score the step-2 run
plumb-eval --run reports/<headline_run_id> --truth data/batch_main_200/truth
```

Expected: L3 `determinism_score` **< 1.000** — the endpoint gives no
bit-reproducibility guarantee at temperature 0 and we pass no `seed`
(non-negotiable 8). Whatever it comes out as is the finding.

## The guardrail check (do this before writing anything up)

From `reports/<headline>/metrics.json`:

- `correct_abstention_rate` must be **exactly 1.000** — hybrid must not
  auto-resolve any of the ~15 % genuinely-in-flight settlements.
- `silent_error_rate` must be **≤ 0.194** (the rules_only baseline).
- `false_alarm_inr` must be **0**.

**If any of those breaks, that is a real finding — report the raw
numbers and stop. Do not interpret or write it up.**

## If the guardrails hold

Fill `ABLATION.md` §4's `hybrid` row from `metrics.json` +
`determinism.json`, evaluate the gate (§2), write §5 the verdict and
§6/§7 per the actual determinism. Read §6 first — the
`over_abstention_rate` gate is soft; the guardrails and the magnitude
are the substantive result. If the gate isn't cleared, ship the honest
negative (`IMPLEMENTATION_PLAN.md` §5) — do not tune, `config_b` is
held out.

`git add -f reports/<headline>/ fixtures/llm/` and commit `ABLATION.md`
+ the run dir. Confirm CI green (replay).

## Swapping back to Anthropic

Set `ANTHROPIC_API_KEY`, change `AgentConfig.model` to `claude-sonnet-5`,
point `pipeline._make_client` at `AnthropicClient` (kept for exactly
this), re-record. Nothing else changes.
