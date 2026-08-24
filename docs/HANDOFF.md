# Handoff — end of the P1.4 session (sellers.csv)

Written for a fresh session that has the seven specs and the committed
code, but not the conversation that produced them. Several things below
are decisions that look wrong against a literal reading of a spec and are
correct anyway, for reasons that only exist in that missing conversation.
Read this before touching `plumb_gen/`, `plumb/domain/tolerance.py`, or
`plumb/ingest/`.

---

## 1. Where things stand

**GATE P0 is met.** All four criteria: byte-identical generator output
across two runs; scorer produces a complete metrics table against a
stub engine returning zero matches; CI green with no API key; the
import-boundary test fails on a deliberate violation (demonstrated,
not just asserted).

**P1.1–P1.4 (ingest & normalisation) are done.** Three transactional
adapters (`intent`, `razorpay`, `bank`) plus `sellers.csv` as a real
fourth source (see §5's own entry on this — it changes the "three
sources" framing several docs use, and two of those mentions were
*deliberately* left unchanged). The UTR extraction cascade, the full
provenance chain (`source_file`/`raw_record`/`transform_log`/
`quarantine`), and the `ingest → match → verify → agent → report`
layer-direction guard are all built and tested against real generated
data, not just hand-written fixtures.

**P1.5–P1.11 (the matcher) is next. Nothing in `match/` exists yet** —
it's still an empty package. `ToleranceProfile` (§2 below) is the one
piece already built and waiting to be imported, not redefined.

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

## 4. Landmines a fresh session would hit, reading only specs + code

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
(`tests/test_import_boundary*.py`, `tests/test_layer_direction.py`,
`tests/plumb_gen/test_world.py::test_generator_package_never_reads_the_clock`),
not a text search.

**The no-float exemption now covers `report/` *and* `plumb_eval/`.**
Both `tests/test_no_float_lint.py`'s `EXEMPT` set and the two docs that
state the rule (TRD §2 rule 5, `CLAUDE.md` rule 1) were updated
together when `plumb_eval`'s ratio metrics needed it — check both stay
in sync if this ever changes again. **The exemption does not extend to
`ingest/`, `match/`, `verify/`, or any other engine layer** — a float
inside those sits in L1/L2's determinism-critical path, unlike
`plumb_eval`'s read-only, downstream scoring. UTR confidence (below)
almost became a float here and didn't, on purpose.

**UTR confidence is basis points (`int`), not `float`.**
`plumb/ingest/narration.py`'s `UTR_PATTERNS` uses `confidence_bps`
(10000/9500/9500/9000/6000), not LLD §3.2's literal `float`
pseudocode — a `# TRD-DEVIATION:` comment in that file explains why:
this value lives inside the engine's own determinism-critical path
(unlike `plumb_eval`'s ratios), so widening the no-float exemption
again wasn't the right fix. TRD §2 rule 3's own basis-points
convention was — every value is a fixed constant, never computed or
divided at runtime.

**`normalise()` purity is easy to regress — this session caught a real
instance of it.** `bank.py`'s `normalise()` originally called
`IdSequence.next()` internally to assign `bank_credit_id`, so calling
it twice on the same `RawRecord` produced two different ids — silently
breaking LLD §3.1's explicit "pure function" requirement. Caught by a
call-twice test, not by inspection. Fixed by
`derive_canonical_id(raw_id, prefix)` (in `plumb/ingest/normalise.py`)
— it derives the canonical id from the `RawRecord`'s own already-fixed
`raw_id` instead of consulting a live counter. **Any new adapter (or,
later, any check) that needs to assign its own id inside `normalise()`
must use this pattern, not a fresh `IdSequence()` call inside the
function body** — and should get its own call-twice test, since this
class of bug produces no symptom other than that specific test
failing.

**`sellers.csv` is a real fourth generator output, and it changes the
"three sources" framing several docs use — read before "fixing" any
of them.** It's a seller master/reference file (`seller_id`,
`seller_name`, `category`, `commission_bps`, `effective_from`,
`effective_to`, `version`), closing two gaps found while building
`intent.py`: neither `seller_id<->seller_name` nor `SellerRateCard`
data had any path into the engine from the three transactional sources
alone — `world.seller_rate_cards` was generator-internal, never
serialized anywhere. Deliberately includes a display-name collision
(`sel_00001`/`sel_00011`, both `"Sharma Electronics"` in
`plumb_gen/fixtures.py::SELLER_NAMES`) so ambiguous resolution is
exercised by real generated data every run, not just a hand-built
fixture. Most "three sources" mentions were updated to four; **two
were deliberately left alone — do not "fix" them**:
- `PLUMB_TRD.md` (`SettlementUnit` "joined view... across all three
  sources") — stays three. That claim is specifically about one
  order's per-order lifecycle join; `sellers.csv` is seller-keyed
  reference data, not per-order.
- `PLUMB_PRD.md` §3.1 ("Three sources, each with its own vocabulary
  for the same transaction") — stays three, same reasoning:
  specifically about per-transaction vocabulary.

Genuinely updated to four: `BACKEND_SCHEMA.md` §1.2 (added the `sel_`
record-key prefix) and §2 (fourth table row + a clarifying note that
`sellers.csv` isn't a transactional source in the same sense), `TRD.md`
§5.1 ("four adapters"), and the illustrative CLI mockups in
`APP_FLOW.md`/`UIUX_BRIEF.md`/`PRD.md`'s architecture diagram.

**MDR is deliberately absent from `intent.csv` — do not add it.**
`Intent.expected_seller_amount_paise` is computed in `intent.py` as
`gross - commission` only, missing MDR (the true formula, in
`world.py`, is `gross - commission - MDR`). This was checked, not
assumed: D01's own PRD §6 detection text, TRD §6.2's worked
`recompute_trace` example, and LLD §5.1's requirement that D01 work on
`INTENT_ONLY` units (which structurally have no settlement data) all
independently confirm D01 never needs MDR or this field. The asymmetry
is real and deliberate — a real platform genuinely doesn't know MDR at
intent time, since it depends on a payment method the customer hasn't
chosen yet. L2 recompute (D02, the only other check with a spec'd
formula) is expected to pull the real MDR from the Razorpay side once
a unit is assembled, not from this approximation. **Do not "fix" this
by adding an MDR column to `intent.csv`** — it would misrepresent what
the platform actually knows at that point.

**`seller_name` resolution has exactly three outcomes, never a fourth
(a guess).** `intent.py`'s `_resolve_seller_id`, fed by a
`seller_lookup: dict[str, list[str]]` built by
`pipeline.py::run_ingest` from the sellers adapter's output *before*
`intent.csv` is read (an ordering requirement, not a suggestion —
sellers must run first): exactly one candidate → resolved (`rule_id
"seller_name_resolved"`); zero candidates → `"seller_name_not_found"`;
two or more (the deliberate collision) → `"seller_name_ambiguous"`,
`seller_id` stays the raw name rather than arbitrarily picking one,
both candidate ids listed in `transform_log.after_text`. Whoever
builds matching (P1.5+) is the one who actually resolves the ambiguous
case — cross-referencing `razorpay.json`'s `transfer.recipient` (which
embeds the true `seller_id`) is the likely mechanism, but that's
undecided, not implemented.

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
timestamps). Six entities, all fixed then. The lesson stands: PRD §4's
entity pseudocode predates `schema/run.sql` and uses looser names — any
new field on a domain model should be checked against the actual DDL,
not just PRD §4. (`Seller`, the new model added this session, followed
the DDL/BACKEND_SCHEMA §1.2 directly rather than PRD §4, which doesn't
mention it at all — no equivalent drift expected there.)

**`Order.seller_id`/`Intent.seller_id`/`SellerRateCard.seller_id` are
still plain `str`, not `RecordKey`, even though `Seller.seller_id` (new
this session) is `RecordKey`-typed.** Deliberate, not an oversight:
tightening the three FK-side fields to match would touch already-tested
code for a purely cosmetic improvement, not something either gap this
session closed actually needed. A reasonable, low-risk cleanup for a
future session, not done here.

**`tests/schema/_truth_db.py` (test-only) and `src/plumb_gen/truth_db.py`
(real) are similar-looking but deliberately separate.** The former exists
so schema-level tests can apply `schema/truth.sql` without depending on
`plumb_gen`'s business logic; it predates `plumb_gen` having real code at
all. Not duplication to consolidate. (`tests/schema/_eval_db.py` follows
the same pattern for `schema/eval.sql`.)

**Repo and CI**: `github.com/MeloveGupta/plumb`, public. Every push has
produced a green Actions run except one (the `VERIFIED_ON` UTC bug above,
fixed in the same session it broke) — GitHub's own runner queue has twice
shown a transient `queued`/`cancelled`-then-auto-retried state on push
that resolved to green on its own; that's infrastructure flakiness, not
a real failure, but always confirm the actual run status rather than
assuming. The workflow currently runs only `uv sync --locked && uv run
pytest` — not yet TRD §9's full 8-step pipeline (generate T1-T4, run
both ablation arms, score, append to history), since `match/`/`verify/`
don't exist yet.

---

## 5. Session ritual

Push and confirm CI before treating a session's work as done — added to
`CLAUDE.md`'s Session ritual and `PLUMB_IMPLEMENTATION_PLAN.md` §8.3/§10
after two sessions in a row ended with tested, committed work sitting
unpushed. `DEVLOG.md` is the user's own — they draft it outside the
repo and commit it themselves. Don't flag it as missing.
