# Ablation — does the LLM earn its place on the residual?

**Status:** prediction committed 2 Sep 2026, before any `hybrid` run.
`rules_only` measured 2 Sep. `hybrid` pending its own session (needs a
live `ANTHROPIC_API_KEY`; this repo's CI runs the arm from recorded
cassettes). See `docs/RUN_HYBRID.md` for the three commands.

---

## 0. The instrument

`plumb_eval` — the scorer every number below comes from — was corrected
on 2 Sep (`7fba72e`), *after* the prediction was written, because it
could not score a real run. The closure model, the fix, and the
justification for both changes are in **`docs/SCORING.md`**. Every
number here is the first measurement taken with the corrected
instrument; there is no "before" to compare against.

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

Run `reports/2026-09-03T05:26:40Z-8abdcbb/` — clean tree, **not
provisional**. Reproduce:

```
plumb-gen --seed 42 --config configs/config_b.yaml --out data/batch_main_200 --tier T2
plumb run --data data/batch_main_200 --ablation rules_only --sample-label HELD_OUT \
          --seed 42 --generator-config configs/config_b.yaml
plumb-eval --run reports/<run_id> --truth data/batch_main_200/truth
```

`data/` is regenerable from the seed and stays gitignored; the run
directory is the committed artifact.

| metric | value | note |
|---|---|---|
| `over_abstention_rate` | **0.341** | the gate baseline — `hybrid` must come in below this |
| `correct_abstention_rate` | **1.000** | escalates every unresolvable order (it escalates everything) — `hybrid` must hold this |
| `residual_resolution_rate` | **0.000** | by construction — L3 disabled |
| `escalated_unresolved_rate` | 1.000 | all 113 exceptions escalated |
| `silent_error_rate` | **0.194** | L1's own rate; guardrail for `hybrid` |
| `false_alarm_inr` | **0** | L2's own; guardrail for `hybrid` |
| `defect_recall` | 1.000 | 56/56 injected defects caught (L2) |
| `defect_precision` / `root_cause_accuracy` | 1.000 / 1.000 | |
| `auto_match_rate` | 0.79 | L1; identical in both arms |
| `match_precision` / `match_recall` | 0.697 / 0.575 | L1; identical in both arms |
| `leakage_caught_inr` | 2,437,598 | ₹24,375.98 caught by L2 |
| `exceptions_total` | 113 | 113 residual + finding exceptions, all escalated |
| L3 `determinism_score` | `NOT_MEASURED` | n/a — no L3 in this arm |

Full table: `reports/2026-09-03T05:26:40Z-8abdcbb/metrics.md`.

Note `correct_abstention_rate = 1.000` is the ceiling — the `hybrid`
guardrail *"≥ rules_only"* means `hybrid` must also be exactly 1.000,
i.e. it must not auto-resolve a single one of the ~15 % genuinely
in-flight settlements. That is a deliberately hard bar.

### `hybrid` — HELD_OUT

`PENDING — hybrid session.` Recorded cassettes under `fixtures/llm/`,
then the same three commands with `--ablation hybrid`, plus the 5-run
determinism harness.

---

## 5. Verdict

`PENDING` — written once `hybrid` is measured. Per
`IMPLEMENTATION_PLAN.md` §5, if `hybrid` does not beat `rules_only` the
honest negative ships plainly; if the cause is diagnosable, L3 is
deepened first. Whichever it is will be stated here with its reason.

---

## 6. Interpretation — the gate is soft; the guardrails are the finding

The committed GATE P3 criterion (§2) is
`over_abstention_rate(hybrid) < over_abstention_rate(rules_only)`. That
prediction is not moved. But it should be read for what it is: **a soft
gate, close to structurally guaranteed to pass.** `rules_only` escalates
*every* exception (`residual_resolution_rate` 0.000,
`escalated_unresolved_rate` 1.000); its `over_abstention_rate` of 0.341
is every genuinely-resolvable exception being escalated. Any exception
`hybrid` resolves — correctly or not — removes it from the
over-abstention count and lowers the rate. Direction is nearly
foreordained; only a `hybrid` that resolves essentially nothing could
fail it.

So the direction of `over_abstention_rate` is not the finding. The
substantive results are:

1. **Do the guardrails hold?** `hybrid` must keep
   `correct_abstention_rate` at exactly **1.000** — it must not buy a
   lower over-abstention rate by *wrongly resolving* the ~15 % of
   settlements that are genuinely in-flight and unresolvable from this
   batch. And `silent_error_rate` (0.194) and `false_alarm_inr` (0)
   must not rise — L3 operates only on the residual and must introduce
   no new wrong answers. These are the real pass/fail.

2. **Magnitude.** How much of the residual does L3 actually resolve
   (`residual_resolution_rate`), and how far does `over_abstention_rate`
   fall? A drop from 0.341 to 0.30 is a different result from a drop to
   0.05.

3. **L3 `determinism_score`.** Expected < 1.000 (the Anthropic API has
   no seed). Reported as a finding, contrasted against L1/L2's exact
   1.000 (§7). Not engineered around.

Naming a soft gate as soft is a stronger submission than claiming a
pass it could not have failed.

---

## 7. L1/L2 determinism = 1.000

Not re-measured here — it is already proven:
`tests/plumb/match/test_determinism_harness.py` runs the L1 pipeline 5×
on one seed and asserts `determinism_score == 1.000` (and the paired
anti-vacuity test: seed 42 ≠ seed 43). L2 is a pure function over L1's
output with no `set` iteration on any ordered path (non-negotiable 7),
so its determinism is structural. The point of the ablation is the
*contrast*: the deterministic layers stay exactly 1.000 while L3 does
not, and that is the case for putting the LLM only where its
non-determinism is acceptable.
