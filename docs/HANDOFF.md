# Handoff — end of the P1 session (matcher, T1–T4 tiers, partial settlement)

Written for a fresh session that has the seven specs and the committed
code, but not the conversation that produced them. Several things below
are decisions that look wrong against a literal reading of a spec and are
correct anyway, for reasons that only exist in that missing conversation.
Read this before touching `match/`, `plumb_gen/world.py`, or
`plumb/domain/tolerance.py`.

---

## 1. Where things stand

**GATE P0 is met.** Unchanged from last handoff: byte-identical
generator output across two runs; scorer produces a complete metrics
table against a stub engine returning zero matches; CI green with no
API key; the import-boundary test fails on a deliberate violation
(demonstrated, not just asserted).

**P1 is complete.** P0–P3 matcher (`match/engine.py`, `match/passes.py`,
`match/subsets.py`, `match/tolerance.py`); Hypothesis property tests
over randomised scenarios (P1.9); L1 determinism = 1.000 across 5
independent full pipeline runs (P1.10); CLI v1, L0/L1 output only
(P1.11, `report/cli.py`). Also shipped, not in the original P1 task
list: PRD §8.2's T1–T4 generator tiers (§4 below) and genuine partial
settlement (§5 below) — both came out of re-measuring GATE P1's own
"auto-match ≥ 85% on T2" criterion and discovering T1–T4 didn't exist
as generator infrastructure at all.

**P2 (verify/checks D01–D08) is next.** `verify/` doesn't exist yet.
Sections 5, 6, 9, 10 below are the ones most likely to matter for it.

---

## 2. `ToleranceProfile` lives in `plumb/domain/tolerance.py`, not `match/`

LLD §1's module map puts `tolerance.py` under `match/`. **Do not move it
there.** Deliberate deviation, forced by two requirements that only both
hold if it stays in `domain/`:

- TRD §3.1: `plumb_gen` may import `plumb.domain` only — `match/` is
  engine-only and unreachable from the generator.
- D02 injection must read the *same* tolerance profile the engine
  checks against, so the generator has to be able to import it too.

`match/tolerance.py` imports `ToleranceProfile` from
`plumb.domain.tolerance` (built this session) rather than redefining
it — confirmed working, this is not still a TODO.

**LLD §4.3's `ToleranceProfile` pseudocode was corrected this session**
to match what's actually shipped: the method is `band_paise()`, not
`band()`; `within(expected_paise, actual_paise)` computes
`band_paise(expected_paise)`, not `band(max(abs(a), abs(b)))`. The
previous handoff flagged this drift and it went unfixed for a session —
it's fixed in the doc now. Trust LLD §4.3 as written; don't "fix" it
back to the old prose.

---

## 3. The matcher's pending/contested-pool mechanism — LLD §4.1 is now authoritative

LLD §4.1's engine pseudocode used to show each pass committing a
component the moment it spans >=2 sides. **That pseudocode was wrong,
not just simplified** — followed literally, it breaks the matcher:

An order's intent+razorpay chain (order/intent/payment/transfer/
settlement_recon) already spans 2 sides even when the bank leg hasn't
joined (narration unparseable). Committing it immediately permanently
claims the `settlement_recon` (`ix_member_claimed_once` — a record is
claimed exactly once, ever) before P1 (exact composite)/P2 (grouped
subset-sum)/P3 (tolerance band) get a turn to attach the orphaned
`bank_credit` — so those passes would never have anything left to
compare it against, and would never resolve anything.

**The actual mechanism, and what LLD §4.1 now documents:** P0 returns
three pools, not one — `groups` (fully resolved), `remaining`
(single-side leftovers, e.g. an order that never got paid), `pending`
(a >=2-side chain missing its bank leg, held open). P1/P2/P3 each get a
turn against still-open pending groups, threading `pending` and the
orphan-bank-credit pool forward pass to pass. Whatever survives to the
end finalises as a plain P0 match — the identity chain was always
certain; a still-missing bank leg is `MISSING_BANK`, a legitimate
outcome for verify's `SettlementUnit` builder (P2.1) to classify, not a
matching failure. A pending group caught in an ambiguous tie (LLD
§4.2's rule: never pick between two equally-valid subsets) still
finalises for its known members — only the contested bank leg is
reported separately in `MatchResult.ambiguous`, so the ambiguity never
blocks the part that was never actually in question.

**This is now correct in LLD §4.1 itself, not a code-only deviation.**
Whoever builds `SettlementUnit` (P2.1) should read `match_group.pass`/
`confidence` and `MatchResult.unmatched`/`.ambiguous` directly against
that section — do not revert it to the old eager-claim sketch.

Also still true from LLD §4.1: `remaining` (and every pool threaded
between passes) is a `list`, never a `set` — Python `set` iteration
order varies with hash randomisation, which would make the matcher
non-deterministic.

---

## 4. T1–T4 generator tiers, orthogonal to config_a/config_b

PRD §8.2 defines T1 (Clean)/T2 (Messy)/T3 (Adversarial)/T4 (Null set).
None of this existed before this session — no CLI flag, config field,
or code path referenced a tier anywhere, and `IMPLEMENTATION_PLAN.md`
had no scheduled task for it. Built because GATE P1 cites "auto-match
≥ 85% on T2" and because T4's "zero findings" is a P2 gate — building
these under P2's own deadline pressure would produce shallow tiers.

**The structural decision**: tier controls how hard a batch is to
*match* (L1); config (`config_a.yaml`/`config_b.yaml`) controls defect
*mix* and general business-event volume (refund/dispute/hold/
interstate rates) — genuinely disjoint field sets. `--tier
{T1,T2,T3,T4}` is a CLI-only flag (`plumb_gen/cli.py`), parallel to
`--seed`/`--batch-as-of`, **never written into YAML** — a T2 batch
under `config_b` is a valid, intended combination, not a conflict.
`plumb_gen/tiers.py::apply_tier(config, tier)` applies a tier's
override dict via `dataclasses.replace`, called once inside
`load_generator_config` after YAML loading; `tier=None` is a verified
no-op (byte-identical to calling `build_world` directly — every
existing config and test is untouched until `--tier` is explicitly
passed).

One field is shared and tier always wins when requested:
`unparseable_narration_rate_bps` (it's the one existing knob that
actually determines matching difficulty). Every other tier field
(`settlement_batch_rate_bps`, `settlement_split_rate_bps`,
`settlement_in_flight_rate_bps`, `format_drift_rate_bps`,
`adversarial_pair_count`) is new, defaults to 0/inert, and is never set
via YAML. T4 is the one tier that also overrides `defects` to empty
regardless of config — a defect-bearing "null set" batch is a
contradiction in terms, not a combination to support.

**T2's many:1 batching and 1:many splitting** (`world.py`'s post-loop
`_apply_settlement_messiness`) give the matcher's P2 real generator
data for the first time — previously P2 only had hand-built/Hypothesis
fixtures. Both run strictly after the main per-order loop finishes, so
they can never shift any existing seed's per-order output regardless of
rate.

**T3's adversarial pairs** (`world.py`'s `_construct_adversarial_pairs`)
are LLD §4.2's ambiguity trap, built from real data: two orders forced
to share one settlement's exact (amount, date), both bank credits
forced unparseable. Verified end-to-end against the real matcher:
5 requested pairs produced exactly 10 `AmbiguousMatch` entries, zero
silently resolved. **T3's other two PRD §8.2 cases — a refund shaped
like a short settlement; commission at the wrong slab that still nets
to a believable figure — are deliberately not built.** Both are checks
D02/D01 already know how to represent, just tuned harder, not a new
mechanism, but there's no L2 check yet to validate the construction
against. Sketch only; build when P2's D01/D02 checks exist.

---

## 5. Genuine partial settlement — the first real `resolvable_from_available_data=False`

PRD §8.2 lists "partial settlement" as a tier concept **separate from**
"1:many/many:1 settlements" — they're different failure modes, and an
earlier pass at this session conflated them (splitting always resolves
within the batch — it's still fully determinable, exactly what P2
exists to solve; that's not what "partial settlement" means).

`settlement_in_flight_rate_bps` (T2-owned): only 30–70% of a
settlement's true net target arrives in the batch **at all** — the
rest is genuinely withheld past `batch_as_of`, not just harder to see.
`settlement_recon.credit_paise` is **not** reduced (Razorpay's own
report reflects what it processed); only the bank side lags. Forced
`utr=None` for a sharper reason than batching/splitting's: **P0 joins
on identifier equality alone and never checks amounts** — a genuinely
parseable UTR on a partial credit would let P0 silently commit a full
P0 match on partial money, a real false negative in the test corpus,
not a matching puzzle. A settlement already netting to exactly zero
(fully consumed by dispute/refund netting) is excluded — there's no
meaningful "30–70% of zero."

Affected orders get `resolvable_from_available_data=False`
(`world.py`'s `_mark_unresolvable`) — **this field was hardcoded
`True` unconditionally everywhere before this session; this is its
first real population.** Confirmed directly (not assumed) before
writing this: `plumb_eval`'s §7.7 abstention math
(`correct_abstention_rate`/`over_abstention_rate` in `metrics.py`,
`score_abstentions` in `scoring.py`) was already built to handle real
`False` values correctly — `_ratio`'s zero-denominator path (`None`,
not `0.0`) was already the *live* path (since `total_unresolvable`
had always been 0), and existing eval-side tests already exercised
real `resolvable=False` fixtures end to end. Nothing in `plumb_eval`,
`schema/truth.sql`, or `truth_db.py` needed to change.

---

## 6. Regression risk: `bank_credit_id` is derived from CSV row position, not from a value in the row

**Read this before writing any code that reorders `world.bank_credits`.**

`plumb/ingest/adapters/bank.py`'s `normalise()` derives
`bank_credit_id` via `derive_canonical_id(raw.raw_id, "bank")` — i.e.
purely from **which row of `bank.csv` it is**, in file order. This is
unlike every other entity: `settlement_recon_id`/`payment_id`/
`transfer_id`/etc. are all read verbatim from an explicit `"id"` field
`razorpay.json` already carries per row. `bank_credit_id` is the one
exception.

This was safe as long as `world.bank_credits`' list order exactly
matched generation order (true by construction, always, before this
session). **T2's batching/splitting/in-flight machinery
(`_apply_settlement_messiness`) breaks that**: it removes consumed
entries and appends new ones at the end, which changes every
*surviving* record's effective row position too, not just the
manufactured ones. Concretely demonstrated this session: order_00001's
true bank credit (per generator truth) was one id; the matcher's
actual P2 group for that same order — reading the ingested CSV —
contained a completely different, unrelated, cleanly-resolvable bank
credit belonging to a different order entirely. The naive auto-match
rate this produced was 3–11%, obviously broken, before the bug was
found.

**The fix, and the rule for any future code touching this list**:
after all reordering decisions are final, renumber `world.bank_credits`
by final list position (`bank_00001`, `bank_00002`, ... in final list
order) and remap *every* `TruthRecord.true_counterparts` reference
through the same old-id → new-id table — not just the ids you know you
touched, since renumbering shifts everyone after a removal or
insertion. `_apply_settlement_messiness`'s tail in `world.py` is the
reference implementation. If you add a new mechanism that reorders
this list, it needs the same renumber-and-remap step, or truth silently
stops matching what ingest actually produces.

---

## 7. T2 auto-match rate: 83.5% (79–89% across 15 real batches) — under GATE P1's 85%, not tuned to meet it

Measured with the real `plumb_eval.metrics._auto_matched_order_keys`
function (not an approximation — see the note below on why that
distinction mattered), across `config_a`/`config_b`/default ×
seeds 1/2/3/7/42, all with `tier="T2"`:

| | seed 1 | seed 2 | seed 3 | seed 7 | seed 42 |
|---|---|---|---|---|---|
| config_a + T2 | 82.5% | 80.5% | 84.5% | 83.5% | 83.0% |
| config_b + T2 | 89.0% | 81.0% | 85.5% | 83.5% | 79.0% |
| default + T2 | 84.5% | 85.0% | 83.5% | 85.5% | 82.5% |

Mean 83.5%, range 79.0–89.0%, 4/15 inside PRD §8.2's 85–92% band. **This
is the honest number. GATE P1's "auto-match ≥ 85% on T2" is reported as
under, not adjusted to pass** — `settlement_in_flight_rate_bps` (1500
bps / 15%) was chosen once from the order-level auto-match math before
ever running the measurement, and was deliberately left alone after
seeing this result. Landing a few points under a target you were
aiming at is evidence you weren't fitting the data to the metric,
which is the exact failure this whole product exists to detect in
other people's systems.

**Do not "fix" this by raising `settlement_in_flight_rate_bps` or any
other tier rate.** If GATE P1 needs to be literally met, that's a
product decision for the user to make explicitly, not a knob a future
session turns quietly to make a number go green.

**Why "measured with the real function" is its own note**: earlier in
this session, "auto-match rate" was computed as a naive
`claimed_records / total_records` ratio. The actual PRD §7.1 metric,
as `_auto_matched_order_keys` implements it, requires an order's
*entire* true counterpart closure to share one `match_id` — one
unresolved leg fails the whole order, not just that record. The naive
metric had been reporting 95–100%; re-measuring with the real function
is what surfaced the `bank_credit_id` bug in §6 in the first place
(the real metric read 3–11% before that fix, which was the tell that
something was structurally wrong, not just imprecise).

---

## 8. Confidence is basis points (`int`) in the engine, not float

`match/passes.py`'s `_CONFIDENCE_BPS` (10000/9500/9000/7000 for
P0/P1/P2/P3) and `MatchGroup.confidence_bps: int` — never a bare
`float` field anywhere in `match/` or `store/`, same TRD §2.5 reasoning
as `plumb/ingest/narration.py`'s existing `confidence_bps` (below).
`match_group.confidence` is `REAL` in the schema (fixed, can't change),
so the `/10000` division happens exactly once, as a bare expression, in
`store/writer.py::write_match_group` — never bound to a named float
value the rest of the engine could pick up and propagate.

---

## 9. `debit_paise` netting — must be subtracted from `credit_paise` before comparing

`match/passes.py`'s `_PendingGroup.target_paise` must be
`sum(r.credit_paise - r.debit_paise for r in recons)`, not raw
`credit_paise`. `plumb_gen`'s own `bank_credit.amount_paise` is
already net of `debit_paise` (dispute/refund netting) at generation
time. P0 is unaffected (it joins via UTR string equality, never
amounts), but P1/P2/P3's fallback comparison silently failed to
re-attach any settlement that had both a nonzero `debit_paise` and an
unparseable bank narration — found by tracing the one record a real
generated batch left unmatched back to its exact arithmetic
(`279198 − 167683 = 111515`, exactly the bank credit's amount).

---

## 10. Landmines still live

**`plumb_gen/rates.py` duplicates `TDS_BPS`/`TCS_BPS` from
`plumb/rules/ratebook.py` on purpose.** Importing from `plumb.rules`
instead breaks the import-boundary test — if the generator ever
imported the engine's own rate lookup, a drift bug in the engine's
rates would be invisible to scoring, since ground truth and the answer
would move together.

**`ratebook.py` has no `GST_ON_FEES` rate registered — this blocks
D08's real check (P2.10).** PRD §5.3 never gives a sourced
`effective_from` for the 18% rate, so `default_ratebook()` registers
`RateKind.TDS`/`RateKind.TCS` only; `rate_for(RateKind.GST_ON_FEES, ...)`
always raises `NoApplicableRate` today. Whoever builds D08 needs either
a real registered rate (find the citation P0.5 didn't have) or its own
independently-sourced constant, same shape as `plumb_gen/rates.py`'s
own `GST_ON_FEES_BPS = 1800`.

**No-float and no-clock-read discipline is enforced by AST-walking
guard tests, not `grep`** (`tests/test_import_boundary*.py`,
`tests/test_layer_direction.py`,
`tests/plumb_gen/test_world.py::test_generator_package_never_reads_the_clock`,
`tests/test_no_float_lint.py`). A naive text grep for `datetime.now`
once false-positived on this project's own docstrings. Any new "never
call X anywhere in this package" guard should follow this pattern.

**The no-float exemption covers `report/` and `plumb_eval/` only** — it
does not extend to `ingest/`, `match/`, `verify/`, or any other engine
layer, since a float there sits in L1/L2's determinism-critical path.
`plumb/ingest/narration.py`'s `confidence_bps` (10000/9500/9500/9000/
6000) is the original precedent this session's match-confidence-as-bps
decision (§8) followed.

**MDR is deliberately absent from `intent.csv` — do not add it.**
`Intent.expected_seller_amount_paise` is `gross - commission` only
(missing MDR, which depends on a payment method the customer hasn't
chosen at intent time). D01/D02's own spec text and LLD §5.1's
`INTENT_ONLY` unit requirement all independently confirm D01 never
needs MDR. L2 recompute (D02) pulls the real MDR from the Razorpay side
once a unit is assembled — directly relevant to whoever builds D01/D02
next.

**`seller_name` resolution has exactly three outcomes, never a fourth
(a guess)** — `intent.py`'s `_resolve_seller_id`: one candidate →
resolved; zero → `"seller_name_not_found"`; two or more (the
deliberate `sel_00001`/`sel_00011` collision) →
`"seller_name_ambiguous"`, `seller_id` stays the raw name. **Correction
to the previous handoff**: it said "whoever builds matching (P1.5+) is
the one who resolves the ambiguous case." The matcher is now built and
does **not** resolve this — it's out of scope for the bank/settlement
P0–P3 matcher, which never touches seller identity at all. This
remains genuinely unresolved and undecided, not silently punted a
second time.

**Method, not just a fact: run the generator across many seeds and
check real output, don't just read the code.** Caught two real bugs in
"clean" generated data in an earlier session (an unclamped dispute
deduction pushing `bank_credit.amount_paise` negative; D08's injected
GST-rate error being a silent no-op on UPI orders). Caught the
`bank_credit_id` bug (§6) this session the same way — by re-measuring
against real generated batches with the actual scorer function instead
of trusting an approximation. Any new generator mechanism or matcher
change should get the same treatment before being trusted.

---

## 11. Session ritual

Push and confirm CI before treating a session's work as done.
`DEVLOG.md` is the user's own — they draft it outside the repo and
commit it themselves. Don't flag it as missing.
