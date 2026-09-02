# Ablation — does the LLM earn its place on the residual?

**Status:** prediction committed 2 Sep 2026, before any `hybrid` run.
`rules_only` measured 2 Sep. `hybrid` pending its own session (needs a
live `ANTHROPIC_API_KEY`; this repo's CI runs the arm from recorded
cassettes).

---

## 1. Two arms, not three

PRD §9's table has three configurations — `rules_only`, `llm_only`,
`hybrid`. **`llm_only` is cut.** This is descope-ladder rung 5
(`IMPLEMENTATION_PLAN.md` §7: *"`llm_only` ablation arm → 2-arm
comparison"*), and §7.1's floor is *"ablation (≥ 2 arms)"*. GATE P3
itself only ever compares `hybrid` against `rules_only`.

Why `llm_only` is the arm to cut, not a coin flip: an LLM doing the
matching and the verification directly is a **known quantity** — it is
non-deterministic (no API seed), and its match precision is bounded by
the model's willingness to guess where a rules engine abstains. We do
not need to spend a held-out run proving that; the determinism contrast
alone (`llm_only` ≪ 1.000 vs L1/L2's exact 1.000) is already the
argument. The run budget the held-out comparison needs is better spent
on `hybrid` vs `rules_only`, which is the question that actually decides
the architecture: *given* a deterministic L1/L2, does adding L3 to the
residual do measurably better than escalating all of it?

---

## 2. The GATE P3 criterion

> `hybrid` beats `rules_only` on residual resolution.

Operationalised (no metric for "residual resolution" exists in PRD §7;
this is the definition used):

**Primary, gating:** `over_abstention_rate(hybrid) < over_abstention_rate(rules_only)`.
`over_abstention_rate` (PRD §7.7) = escalated-but-resolvable /
total-resolvable. `rules_only` escalates *every* exception, so it
over-abstains on every genuinely-resolvable one. `hybrid` should
resolve a real fraction of those (AUTO_RESOLVED / PROPOSED) and drop
them out of the abstention count. T2/`config_b` gives this metric a
real denominator: ~15 % of settled orders are in-flight settlements the
generator marks `resolvable_from_available_data = false`
(`plumb_gen/world.py::_mark_unresolvable`), so there is a genuine
unresolvable population to *not* over-abstain against.

**Guardrails, must also hold:**
- `correct_abstention_rate(hybrid) ≥ correct_abstention_rate(rules_only)`
  — `hybrid` must not buy a lower over-abstention rate by wrongly
  *resolving* the genuinely-unresolvable.
- `silent_error_rate(hybrid) ≤ silent_error_rate(rules_only)` and
  `false_alarm_inr(hybrid) ≤ false_alarm_inr(rules_only)` — L3 must not
  introduce new wrong answers.

**Reported alongside (not gating):** `residual_resolution_rate` =
(AUTO_RESOLVED + PROPOSED) / total_exceptions, and the full outcome
breakdown. `rules_only` scores exactly 0 here by construction. It does
not gate because a PROPOSED resolution's *correctness* is not scored —
the schema carries no proposed-correction amount to compare against
`true_obligation` (`docs/HANDOFF.md`). It is a progress count, not a
correctness measure.

---

## 3. Prediction (written before the `hybrid` run)

| Metric | `rules_only` | `hybrid` (predicted) |
|---|---|---|
| L1/L2 `determinism_score` | 1.000 (exact) | 1.000 (exact — L1/L2 unchanged) |
| L3 `determinism_score` | n/a (no L3) | **< 1.000** — the Anthropic API has no seed. This is a finding, not a defect (non-negotiable 8); the contrast with L1/L2's exact 1.000 *is* the architecture argument. |
| `residual_resolution_rate` | 0 (escalates everything) | materially > 0 — L3 resolves a real fraction of the residual |
| `over_abstention_rate` | high — every resolvable exception escalated | **lower than `rules_only`** — the gate |
| `correct_abstention_rate` | ~1.0 (escalates the unresolvable too) | ≈ `rules_only` — still escalates the in-flight cases |
| `silent_error_rate` | L1's own rate; L2 findings flag some | ≤ `rules_only` — L3 adds no silent errors |
| `false_alarm_inr` | L2's own | ≤ `rules_only` |
| `match_precision`, `match_recall` | L1's own | identical — L3 never re-matches |

Rationale for the shape: L1 and L2 are pure functions (PRD §3); L3
operates *only* on L1's residual and L2's findings (PRD §10.1) and never
re-matches or re-computes. So every L1/L2 metric is identical across the
two arms by construction. The only thing that can move is what happens
to the residual — and the honest question is whether an agent, given
seven read-only tools and a per-exception budget, resolves enough of it
to beat "escalate all of it", without fabricating or wrongly
auto-resolving.

---

## 4. Results

### `rules_only` — HELD_OUT (`config_b`, seed 42, tier T2, 200 records)

`NOT_MEASURED` — run pending a clean-tree measurement. Command:

```
plumb-gen --seed 42 --config configs/config_b.yaml --out data/batch_main_200 --tier T2
plumb run --data data/batch_main_200 --ablation rules_only --sample-label HELD_OUT \
          --seed 42 --generator-config configs/config_b.yaml
plumb-eval --run reports/<run_id> --truth data/batch_main_200/truth
```

The committed `reports/<run_id>/{manifest.json,metrics.json,metrics.md,run.sqlite}`
are the artifact; `data/` is regenerable from the seed and stays
gitignored.

### `hybrid` — HELD_OUT

`PENDING — hybrid session.` Recorded cassettes under `fixtures/llm/`,
then the same three commands with `--ablation hybrid`, plus the 5-run
determinism harness.

---

## 5. Verdict

`PENDING` — written once both arms are measured. Per
`IMPLEMENTATION_PLAN.md` §5, if `hybrid` does not beat `rules_only` the
honest negative ships plainly; if the cause is diagnosable, L3 is
deepened first. Whichever it is will be stated here with its reason.

---

## 6. L1/L2 determinism = 1.000

Not re-measured here — it is already proven:
`tests/plumb/match/test_determinism_harness.py` runs the L1 pipeline 5×
on one seed and asserts `determinism_score == 1.000` (and the paired
anti-vacuity test: seed 42 ≠ seed 43). L2 is a pure function over L1's
output with no `set` iteration on any ordered path (non-negotiable 7),
so its determinism is structural. The point of the ablation is the
*contrast*: the deterministic layers stay exactly 1.000 while L3 does
not, and that is the case for putting the LLM only where its
non-determinism is acceptable.
