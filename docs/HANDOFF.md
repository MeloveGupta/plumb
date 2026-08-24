# Handoff — end of the P0.8 session

Written for a fresh session that has the seven specs and the committed
code, but not the conversation that produced them. Several things below
are decisions that look wrong against a literal reading of a spec and are
correct anyway, for reasons that only exist in that missing conversation.
Read this before touching `plumb_gen/` or `plumb/domain/tolerance.py`.

---

## 1. Where P0 actually stands

**GATE P0 is not met.** P0.8 finishing ("the last big P0 task" per the
implementation plan's own framing) reads like P0 is basically done. It
isn't — no scorer exists yet, and GATE P0 requires one.

| Task | Status |
|---|---|
| T0.1 Route approval | **Unknown.** Flagged to the user on D0 as the longest-lead item; never confirmed either way in any later session. Check before assuming it landed. |
| T0.2 Repo skeleton | Done |
| T0.3 First DEVLOG.md entry | **Not done.** See §6. |
| P0.1 CI skeleton | Done — import boundary, no-float lint, STRICT-schema, all AST-based, all demonstrated failing on a real violation |
| P0.2 Pydantic domain models | Done, but needed two rounds of fixes discovered in later sessions — see §5 |
| P0.3 schema/run.sql | Done — full DDL, all 10 BACKEND_SCHEMA §8 schema tests pass |
| P0.4 schema/truth.sql | Done |
| P0.5 Rules module | Done — `RateBook`, `apply_bps`, hand-computed TDS/TCS tests |
| P0.6 Generator core | Done, but see §5 for corrections made in later sessions |
| P0.7 Three source writers | Done — `dataset/` now holds real `intent.csv`/`razorpay.json`/`bank.csv`; the canonical JSON dump P0.6 wrote as a stand-in is retired |
| P0.8 Defect injectors D01-D08 | Done |
| P0.9 Truth writer | **Half done** — see §4 |
| P0.10 Byte-identical determinism test | Done — pulled forward into P0.6 rather than done as its own separate task later, then updated in P0.7 to hash the real `dataset/` files instead of the retired canonical dump |
| P0.11 Scorer, all 8 metric families | **Not started** |
| P0.12 Scorer vs. stub engine | **Not started** |
| P0.13 Config files (config_a.yaml / config_b.yaml) | **Not started.** `GeneratorConfig` and `InjectionConfig` exist as Python dataclasses with sensible defaults; no YAML loading exists |

GATE P0 checklist against the above: byte-identical (met), CI green with
no API key (met), import-boundary test fails on a deliberate violation
(met, demonstrated repeatedly, not just asserted) — but "scorer produces
a complete metrics table against a stub engine" is **not met**. P0.11/12
are the actual remaining gate blockers, not P0.13.

---

## 2. `ToleranceProfile` lives in `plumb/domain/tolerance.py`, not `match/`

LLD §1's module map puts `tolerance.py` under `match/`. **Do not move it
there.** This was a deliberate deviation, not an oversight, forced by two
requirements that only both hold if it stays in `domain/`:

- TRD §3.1: `plumb_gen` may import `plumb.domain` only — `match/` is
  engine-only and unreachable from the generator.
- TRD §3.3: D02 injection must read the *same* tolerance profile the
  engine will check against ("the generator imports the profile so the
  two cannot drift apart") — if the profile lived in `match/`, the
  generator couldn't import it at all, and would have to duplicate it,
  which is exactly what TRD §3.3 says not to do.

When P1.8 (`match/tolerance.py`, matcher's tolerance pass) gets built, it
should **import `ToleranceProfile` from `plumb.domain.tolerance`**, not
redefine it or host its own copy. `domain ← everything` (LLD §1's own
dependency rule) makes that import legal in that direction.

---

## 3. One defect per record, not stacking

`plumb_gen/injectors.py` assigns each defect class to a disjoint set of
order indices — no order carries two injected defects. Chosen for
unambiguous attribution: `defect_recall_per_class` and
`leakage_caught_inr` have no clean answer for a record where an agent
catches one of two co-occurring defects and misses the other, and that
ambiguity isn't worth the added realism at this stage.

The schema does **not** enforce this — `injected_defect.record_key` isn't
unique, so stacking is schema-representable. This is a generator policy
choice living in `injectors.py`, not a constraint from BACKEND_SCHEMA. If
T3 (adversarial tier) ever wants stacked defects for realism, that's a
deliberate future change to `_assign_defects`, not something blocked by
the data model.

---

## 4. P0.9 — what's already done, what's left

The real truth-writing code already exists and is tested, built during
P0.8 because P0.8's own acceptance criteria required "recorded in
truth.sqlite":

- `src/plumb_gen/truth_db.py` — `open_truth_db()`, `write_truth()`
- `tests/plumb_gen/test_truth_db.py` — round-trip and FK-enforcement tests

What's still actually P0.9's job:

- **`cli.py` never calls `write_truth`.** It only calls `write_sources`
  for `dataset/`. Truth is not written by the CLI path at all yet — check
  `src/plumb_gen/cli.py` before assuming otherwise.
- `write_truth` needs to land at `data/{batch_id}/truth/` per TRD §3.2
  (already excluded in `.gitignore` from T0.2 — `data/*/truth/`).
- The CLI has no flag for passing an `InjectionConfig` at all right now —
  `plumb-gen` always generates a clean batch. Wiring that in sits at the
  seam between "P0.9: wire truth writing into the CLI" and "P0.13:
  load config from YAML" — whoever picks this up should decide which task
  owns it rather than assuming either already covers it.

---

## 5. Landmines a fresh session would hit, reading only specs + code

**`plumb_gen/rates.py` duplicates `TDS_BPS`/`TCS_BPS` from
`plumb/rules/ratebook.py` on purpose.** This looks like something to DRY
up by importing from `plumb.rules` instead. Doing that breaks
`tests/test_import_boundary.py::test_plumb_gen_only_imports_plumb_domain`
— same reasoning as §2. If the generator ever imported the engine's own
rate lookup, a drift bug in the engine's rates would be invisible to
scoring, since ground truth and the answer would move together.

**`plumb_gen/rates.py`'s `GST_ON_FEES_BPS = 1800` is not a duplicate of
anything — `ratebook.py` has no `GST_ON_FEES` rate registered at all.**
P0.5 left it out deliberately: PRD §5.3 never gives a sourced
`effective_from` for the 18% GST-on-fees rate, so `default_ratebook()`
registers `RateKind.TDS` and `RateKind.TCS` only. `RateKind.GST_ON_FEES`
exists as an enum member but `rate_for(RateKind.GST_ON_FEES, ...)` raises
`NoApplicableRate` today, always. This matters for whoever builds D08's
real check (P2.10): it cannot call `ratebook.rate_for(RateKind.GST_ON_FEES, ...)`
yet — it'll need either a real registered rate (find the citation P0.5
didn't have) or its own independently-sourced constant, same shape as
`plumb_gen/rates.py`'s. The injector's D08 already generates its
discrepancy using its own locally-defined `D08_WRONG_GST_BPS` in
`plumb_gen/world.py`, independent of both.

**No-float and no-clock-read discipline is enforced by AST-walking guard
tests, not `grep`.** A naive text grep for `datetime.now` once
false-positived on this project's own docstrings, which describe the rule
in prose. Any new "never call X anywhere in this package" guard should
follow the existing AST pattern
(`tests/test_import_boundary*.py`,
`tests/plumb_gen/test_world.py::test_generator_package_never_reads_the_clock`),
not a text search.

**`RateBook.VERIFIED_ON` and its freshness test are anchored to UTC
explicitly** (`datetime.now(UTC)`, not `date.today()`). The dev sandbox
this project has been built in runs IST; GitHub Actions runs UTC. A
`date.today()`-based date comparison caused one real red CI run. Any
future "is this value stale" check needs the same UTC anchoring, not
system-local time.

**The domain models (`plumb/domain/models.py`) had six real field-name
and nullability mismatches against `schema/run.sql`**, found piecemeal
across three sessions after P0.2 shipped, not caught at the time:
`Intent` was missing its own `intent_id` (had `order_id` doing double
duty); `Order.gross_amount_paise` should be `gross_paise`; `OrderLine`
had three misnamed fields; `SettlementRecon` was missing its own id, had
`entity_id`/`dispute_id` where the schema says `entity_key`/`dispute_key`,
and wrongly made `utr` nullable (that nullability belongs to
`BankCredit.utr`, not this one — Razorpay's own settlement report always
states its own reference); `BankCredit` was missing its own id and had
`credited_at_utc` where the schema says `credited_on` (it's a date, not a
timestamp — the schema comment says so explicitly); `SellerRateCard` had
three renamed fields (`commission_rate_bps`, `effective_from_utc`,
`effective_to_utc` should be `commission_bps`, `effective_from`,
`effective_to` — no `_utc` suffix, since these are dates, not
timestamps). Six entities, all fixed now. The lesson: PRD §4's entity
pseudocode predates `schema/run.sql` and uses looser names — any new
field on a domain model should be checked against the actual DDL, not
just PRD §4.

**Two real bugs in "clean" generated data, both found by scanning actual
generated output across many seeds, not by reading the code:** an
unclamped dispute deduction could push `bank_credit.amount_paise`
negative (present in roughly half of 200 scanned seeds before the fix);
D08's injected GST-rate error was a silent no-op whenever a UPI-method
order was selected, since UPI has 0 MDR and a wrong rate applied to zero
is still zero. Both fixed. Worth restating as a working method for this
codebase specifically: for the generator, code that looks correct on
inspection has twice turned out to have a real bug that only showed up by
actually running it across a range of seeds and checking the output, not
by reading the logic. Any new injector or generation rule should get the
same treatment before being trusted.

**Clean data now nets partial refunds from settlement**, via
`settlement_recon.debit_paise` (the same mechanism already used for
dispute deductions). This was added specifically so D03
("refund not netted from seller obligation") has a correct baseline to
deviate from — before this fix, clean data never netted refunds anywhere,
so D03 wouldn't have been a meaningful defect. This is intentional
generation behavior, not scope creep to revert.

**`tests/schema/_truth_db.py` (test-only) and `src/plumb_gen/truth_db.py`
(real) are similar-looking but deliberately separate.** The former exists
so schema-level tests can apply `schema/truth.sql` without depending on
`plumb_gen`'s business logic; it predates `plumb_gen` having real code at
all. Not duplication to consolidate.

**Repo and CI**: `github.com/MeloveGupta/plumb`, public. Every push has
produced a green Actions run except one (the `VERIFIED_ON` UTC bug above,
fixed in the same session it broke). The workflow currently runs only
`uv sync --locked && uv run pytest` — not yet TRD §9's full 8-step
pipeline (generate T1-T4, run both ablation arms, score, append to
history), since the matcher/verify/scorer layers it needs don't exist
yet.

---

## 6. DEVLOG.md still does not exist

Flagged at the end of nearly every session so far; still hasn't been
written, including the very first entry. There is now real material that
will become hard to reconstruct convincingly the longer it's left: the
six-field schema-drift discovery, the negative-settlement bug, the
D08/UPI zero-effect bug, the `VERIFIED_ON` timezone bug that caused an
actual CI failure. The track's own submission criteria ask what broke and
how it was recovered — this is exactly that material, and none of it is
written down anywhere durable yet.
