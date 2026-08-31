# Handoff — end of the P2 session (verify layer complete, GATE P2 met)

Written for a fresh session that has the seven specs and the committed
code, but not the conversation that produced them.

---

## 1. Where things stand

**GATE P0 met, P1 complete** — unchanged from the last two handoffs.

**P2 is complete. GATE P2 is met.** `verify/` now has: `SettlementUnit`
builder + `Completeness` classification (P2.1), the `Check`
protocol/registry (P2.2), all eight checks D01–D08 (P2.3–P2.10), a real
re-evaluation mechanism for `recompute_trace` (P2.11, §5 below), the
`on_matched_record` CLI line (P2.12), and the variance bar (P2.14).

**GATE P2's real numbers**, measured on `config_b`/T2 (HELD_OUT — see
§7 below for why this needed its own measurement pass), 5 canonical
seeds, via the real `plumb_eval.scoring.score_defects` function (not a
hand-rolled comparison):

| | seed 1 | seed 2 | seed 3 | seed 7 | seed 42 |
|---|---|---|---|---|---|
| defect_recall | 55/56 | 55/56 | 55/56 | 56/56 | 56/56 |

98.2%–100%, mean ~98.9%, well clear of the 80% gate. `defect_precision`
and `root_cause_accuracy` are both 100% on every seed. Committed as
`tests/plumb_eval/test_gate_p2_real_batch.py` — a real regression test,
not a one-off number in this doc.

**P3 (the agent) is next.** GATE P3 is the architecture pass/fail for
the whole submission: `hybrid` must beat `rules_only` on residual
resolution, or the honest negative gets shipped and written up plainly
— see PRD/IMPLEMENTATION_PLAN §5's own framing, unchanged by anything
this session did.

---

## 2. The recurring pattern: three times, the generator was wrong, not the check

Writing a real check against real generated data found a genuine
generator bug three separate times this build, not once:

1. **D03 (P0.8)** — clean data's refund-netting step was silently
   skipped for the wrong condition, producing a phantom shortfall.
2. **An unclamped dispute deduction (P0.8)** — could push
   `bank_credit.amount_paise` negative; found by scanning real batches,
   not by inspection.
3. **D04 (this session)** — `world.py` computed TCS on gross *before*
   an order's own organic refund was decided, so a clean order that
   rolled a refund kept gross-basis TCS forever, violating the tax law
   D04 exists to check. This produced a measured 35% D04 precision
   (6 true positives / 11 false positives) on real data — not accepted
   as a documented limitation, root-caused with three independent
   pieces of evidence (the generator's own comment admitting the
   unfinished intent; PRD §5.2's literal text; the check's own
   arithmetic already matching every forced-refund case exactly), then
   fixed with a post-loop correction pass
   (`_correct_tcs_for_organic_refunds`) rather than reordering
   `_build_order`'s RNG draws. **D04 precision: 35% → 100%** on the
   same real batch, confirmed after the fix, zero test breakage, zero
   `plumb_eval` scoring interaction (checked before touching anything).

**Relevant to P3, not just a war story**: when the agent's own
recompute disagrees with recorded data, "the data is wrong" has to be a
real, first-class hypothesis in the investigation loop and its prompts
— not a fallback reached only after exhausting "the check is wrong."
Three real generator bugs surfaced exactly because someone treated a
disagreement as informative rather than assuming the recorded number
was ground truth. Design P3's abstention/escalation logic (and its
prompts) so a confident "this input looks wrong, not my recompute" is
representable and doesn't get silently smoothed over into a low-
confidence resolution.

---

## 3. D08 is narrow by design, not by time pressure — `BatchCheck` is retired

PRD §6 describes D08 as settlement-file-vs-tax-invoice reconciliation —
two independently-sourced documents that could disagree. Built instead
as a per-unit rate-correctness check (`verify/checks/d08.py`), same
shape as D01/D04/D05: recompute GST-on-MDR per payment via the
registered `GST_ON_FEES` rate, compare against `Payment.tax_paise`.
`# PRD-DEVIATION:` comment in the module states plainly what this does
NOT catch: an invoice that's wrong independent of the settlement file.

**Why, precisely — not just "ran out of time"**: the literal version
costs ~7-9h (a genuinely new ingested artifact: new domain model, new
adapter or an extension to `RazorpayAdapter`, a schema change to
`source_file.source_id`'s CHECK constraint, plus a `BatchCheck`
protocol and its own registry). But `d08_wrong_tax_paise` (the only
D08 injector that exists) only ever corrupts a per-payment figure —
nothing in the generator can make "the invoice" wrong independent of
the settlement file. A genuinely separate invoice artifact would add
**zero detection power** over recomputing the correct total directly,
given what the generator can currently inject. The expensive version
buys nothing today; it only would once the generator can also corrupt
an invoice independently of the settlement file, which is separate,
unscoped work.

**`BatchCheck` (the protocol proposed for the literal version) was
retired, not built.** Don't revive it without first giving the
generator a way to make an invoice wrong on its own — otherwise it's
infrastructure for a defect that can't currently exist in the test
corpus.

---

## 4. The one recurring miss: ambiguous seller name — not a bug

Across this session's real-batch verification (D01 fixtures, D04
re-verification, and the GATE P2 measurement — 25 seed-runs total),
every single miss is the same known, deliberate fixture:
`intent.py::_resolve_seller_id`'s ambiguous-name collision (two seller
ids sharing one display name — "Sharma Electronics" in this build's
fixture data). When it fires, `Order.seller_id` stays the raw name
string, no `SellerRateCard` can resolve against it, and D01's
`applies_to()` correctly declines rather than guessing a contracted
rate. `score_defects` then correctly counts that instance as
undetected — a genuine, correct abstention, not a false negative to
chase.

**Do not build a heuristic to resolve this.** There is no reliable
signal to disambiguate two sellers sharing a display name after the
fact; guessing would be exactly the kind of pattern-guessing CLAUDE.md
rule 4 forbids. If this needs to stop happening, the fix is upstream
(sellers.csv shouldn't collide, or intent.csv should carry seller_id
directly) — a generator/fixture decision, not a verify-layer one.

---

## 5. `recompute_trace`'s re-evaluation mechanism (P2.11) — test-time only

LLD §5.4 requires "a trace can never describe arithmetic the code
didn't actually do," asserted by "re-evaluating simple formulas from
the inputs dict" — but gives no mechanism. Built: a small, restricted
AST evaluator (`verify/trace.py::reevaluate_step`/`reevaluate_trace`)
supporting `+ - * // /`, unary minus, `abs()/min()/max()`, integer
constants, and name lookups against a step's own `inputs` dict. Not a
bare `eval()`. Not wired into `TraceBuilder.step()` at runtime — LLD
says "asserted in tests," and `recompute_step`'s schema has no column
for a stored verified flag, confirming this is a test-time invariant.

**The retrofit obligation for any NEW check** (D08 already complies;
D01–D07 were retrofitted this session): every `.step()` call's
`formula` must be a literal, executable expression over its own
`inputs` — no human-only annotations like "(round-half-up)", no rate
constants baked into an f-string, no list aggregate compressed into a
bare count (pre-aggregate to a scalar first, or split into more,
smaller chained steps whose outputs feed the next step's inputs, per
TRD §6.2's own worked example). A business-rule gate (D02's tolerance
band, D06's age threshold) is not a step — only money arithmetic is;
describe the gate's outcome in the conclusion text instead. Wire
`assert_trace_reevaluates(finding)` (`tests/plumb/verify/_verify_fixtures.py`)
into every new check's own "fires" test.

---

## 6. Landmines carried forward from P1 (condensed — see git history for the full reasoning if one of these breaks)

- **`ToleranceProfile` lives in `plumb/domain/tolerance.py`, not `match/`** (LLD §1's module map is wrong on this point, deliberately) — D02/D08 and the generator's own D02 injector all read the same instance; never reconstruct a second one.
- **`match/passes.py`'s three-pool mechanism** (`groups`/`remaining`/`pending`) is authoritative per LLD §4.1 — a still-missing bank leg after P3 is `MISSING_BANK`, a legitimate outcome, not a matching failure.
- **`bank_credit_id` is derived from CSV row position, not a value in the row.** Any code that reorders `world.bank_credits` must renumber by final list position and remap every `TruthRecord.true_counterparts` reference — `_apply_settlement_messiness`'s tail in `world.py` is the reference implementation.
- **`plumb_gen/rates.py` duplicates `TDS_BPS`/`TCS_BPS`/`GST_ON_FEES_BPS` from `plumb/rules/ratebook.py` on purpose** — importing the engine's own rate lookup from the generator would make a rate-drift bug in the engine invisible to scoring.
- **No-float/no-clock discipline is enforced by AST-walking guard tests, not `grep`** — any new "never call X" guard should follow that pattern, not a text search.
- **T2 auto-match rate is 83.5% mean (79–89% range), honestly under GATE P1's 85% target, deliberately not tuned to pass.** Don't raise `settlement_in_flight_rate_bps` to fix this without the user's explicit sign-off.

---

## 7. Landmine: no persistence layer yet for verify's own output

`schema/run.sql` has had `settlement_unit`/`finding`/`recompute_step`/
`finding_evidence` tables since before P2 started, but `store/writer.py`
still has no `write_settlement_unit`/`write_finding`/`write_recompute_step`/
`write_finding_evidence` functions. Every check this session (and the
CLI's L2 line, and the GATE P2 measurement) worked entirely from
in-memory `SettlementUnit`/`Finding` objects — never a real `run.sqlite`
round trip. The GATE P2 measurement specifically had to build its own
adapter directly into `plumb_eval`'s `TruthStore`/`RunData` (both plain
dataclasses, no SQL connection required) rather than using the
"official" `plumb_eval.scorer.score_run` path, which requires real
files. Building the missing writer functions is separate, unscoped
work — relevant to whoever eventually wires a real CLI run or P4's
report layer, and possibly to P3 if any tool needs to read real
persisted findings rather than take them as arguments.

---

## 8. Session ritual

Push and confirm CI before treating a session's work as done.
`DEVLOG.md` is the user's own — they draft it outside the repo and
commit it themselves. Don't flag it as missing.
