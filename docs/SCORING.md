# The scoring instrument — why the L1↔scorer fix is sound

`plumb_eval` is the instrument every headline number in `ABLATION.md`
and `README.md` is measured with. On 2 Sep it was changed
(`7fba72e`) — under time pressure, because it could not score a real
run. This document is the justification a panelist is owed for a change
to the instrument.

---

## 1. What broke

`plumb_eval.score_all_matches` and `validate_no_fabrication` had **never
run against real matcher output**. GATE P1 tested only L1 determinism;
GATE P2's test builds its `RunData` with `match_groups=[]` and calls
`score_defects` directly. The first real `run.sqlite` — produced by the
persistence bridge — made `plumb_eval.scorer.score_run` abort.

`plumb_eval/truth_store.py` assumed, in a written comment, that *"a real
match_group's members can only ever be leg keys
(payment/transfer/settlement_recon/bank_credit), never the order's own
key."* The matcher that shipped in P1 (`match/engine.py`, P0 ID_CHAIN)
groups the **whole `payment_id` chain**:

```
P0 ID_CHAIN  [bank_00001, int_00002, ord_00002, pay_00002, setl_00002, txfr_00002]
             ^^^ leg      ^^^ intent ^^^ order  ^^^ leg     ^^^ leg     ^^^ leg
```

The order key and the intent key are both `match_member` rows tagged
`side="intent"`. A refund / dispute / reversal that shares the
payment's `payment_id` is grouped in too. Truth's `true_counterparts`
was `[payment, transfer, settlement_recon, bank_credit]` — no intent,
no order, no satellites. So:

- `score_match`'s `members == counterpart_closure(anchor)` could never
  be true — `members` always had ≥2 keys the closure lacked.
- `validate_no_fabrication` aborted on the first `int_` or `disp_` key,
  because truth had no closure for it.

## 2. The fix

Two places, plus one generator line.

**`world.py`** — `true_counterparts` now lists the intent leg. The
intent is generated one-to-one with its order from the same
`intent.csv` row and the matcher groups it; it belongs in the closure.

**`scoring.py::_is_settlement_identity(key, order_keys)`** — `True`
unless `key` is an order key or has a satellite prefix
(`rfnd_`/`disp_`/`rvsl_`/`oln_`). `score_match` filters `group.members`
through it before the `== closure` comparison;
`validate_no_fabrication` uses it to split keys into two checks
(§4 below).

**`run_reader.py` / `scoring.py`** — `RunData` now also reads
`record_index` and `resolution_evidence`; evidence keys are validated
against `record_index` instead of truth closures (§4).

The closure model, stated plainly: a correct `match_group` contains
exactly `{order key} ∪ true_counterparts` = order + intent + payment +
transfer + settlement_recon + bank_credit, plus whatever
refund/dispute/reversal rows hang off the payment. The truth closure is
the middle five (order key resolves to it but isn't stored in it).
`score_match` compares the identity legs; the order key and satellites
are filtered out on both sides implicitly (the order key is never in a
closure, and the satellites are stripped from `members`).

---

## 3. Q1 — does stripping order + intent + satellites make
`members == expected` too easy to satisfy?

**No.** The stripped keys carry no independent signal, and every
substantive matching error still fails the comparison.

### Why the stripped keys carry no signal

The matcher builds a group by following foreign-key edges outward from
one `order_id`:

```
Order.order_id == Intent.order_id == Payment.order_id
Payment.payment_id == Transfer.payment_id == Refund.payment_id == Dispute.payment_id
Transfer.transfer_id == Reversal.transfer_id == SettlementRecon.entity_key
```

An order key can only enter a group **on the same FK edge as its own
intent and payment**. A refund can only enter **on the same edge as its
own payment**. There is no path by which a stray `ord_9` or `rfnd_9`
joins a group without `pay_9` (or `int_9`) joining too — and those *are*
compared. So stripping `ord_*` and `rfnd_*/disp_*/rvsl_*` removes keys
whose presence is fully determined by an identity leg that survives the
strip.

### Every wrong match still fails `members == expected`

| wrong match | after the strip | verdict |
|---|---|---|
| missing an identity leg (in-flight bank, orphan) | `members` is a strict subset of the closure | FALSE_POSITIVE |
| extra identity leg (a leg from another settlement) | `members` is a strict superset | FALSE_POSITIVE |
| **substituted identity leg** (wrong payment/transfer/bank) | anchor resolves to a *different* order's closure; the sets differ | FALSE_POSITIVE |
| merged two settlements | ~10 legs vs a 5-leg closure | FALSE_POSITIVE |

The first row is `tests/plumb_eval/test_scoring.py`'s orders 2/3/4
(unchanged, still green). The substituted-leg row is a test added with
the fix:
`test_a_match_with_a_substituted_leg_still_scores_false_positive` —
`mtch_00002` is order 2's group with order 1's payment key swapped in.
After the strip, `members = {int_00002, pay_00001, txfr_00002}`; the
anchor `int_00002` resolves to `{int_00002, pay_00002, txfr_00002}`;
`members != closure` → FALSE_POSITIVE. The strip is not a rubber stamp.

`validate_no_fabrication` also still catches the substituted key at the
*identity* level if truth has never heard of it at all — the existing
`test_validate_no_fabrication_raises_on_an_unknown_record_key` covers
that.

---

## 4. Q2 — evidence validation moved from truth closures to
`record_index`. That is a weaker oracle. Justify it.

`validate_no_fabrication` now applies **two** checks:

- **Identity keys** — `match_member` keys and `UNMATCHED`-exception
  `record_key`s, minus order keys and satellites — must resolve to a
  truth closure. This is the strong check: a matched leg that ground
  truth has no settlement for is a fabricated settlement. It is also
  the "the generator was wrong three times this build" safety net.
- **Everything else** — order keys, satellites, finding evidence,
  resolution evidence — must be in `record_index`.

### Why `record_index` is the right oracle for evidence

1. **It is TRD §8.3 verbatim.** *"A key in engine output that is absent
   from **the dataset** fails the run — that is fabrication."*
   `record_index` is the engine's own row-per-ingested-record
   enumeration of the dataset (`RecordIndex.from_ingest` and the bridge
   write the identical set). Checking against it is the literal rule,
   not a proxy.

2. **Truth closures were the *wrong* oracle for evidence.** They are
   settlement-identity only. A D02 (short settlement), D03 (refund
   netting) or D07 (reversal-without-refund) finding legitimately cites
   the dispute / refund / reversal that *explains* the shortfall — none
   of which is a settlement leg. Checking evidence against closures
   *rejected correct evidence*. That was the abort.

3. **L2 cannot fabricate.** Every check in `verify/checks/` is a pure
   deterministic function. Its `EvidenceRef`s are read straight off the
   `SettlementUnit`'s own fields (`unit.order.order_id`,
   `unit.rate_card.rate_card_id`, `p.payment_id for p in unit.payments`,
   …) — every one a real ingested record by construction. There is no
   code path in `verify/` that synthesises a record key. Evidence
   that is real but not maximally relevant is measured by
   `root_cause_accuracy` and `defect_precision`, not by a fabrication
   abort.

4. **L3 evidence is caught three ways.** In-process by
   `agent/gates.py::assert_evidence_resolves` (raises `FabricationError`,
   aborts before any persist); at write time by
   `resolution_evidence.record_key`'s foreign key into `record_index`
   (schema §3.6: *"A fabricated reference cannot be written"*); and now
   at score time by `validate_no_fabrication`. For a `run.sqlite`
   produced by our own writer the score-time check is redundant with
   the FK — it exists to keep scoring safe against a `run.sqlite` that
   was *not* produced by our writer (foreign keys off, hand-edited).
   Test:
   `test_validate_no_fabrication_backstops_resolution_evidence`.

### What is deliberately *not* checked

Evidence **relevance** — that a finding's evidence belongs to the
finding's own order, or that a resolution's evidence was actually seen
during that exception's investigation. That needs a record→order map
the scorer does not have (`record_index` carries `entity_type`,
`source_id`, `raw_id` — no order FK; the canonical detail tables the
map would need were only persisted at P4). It is a `root_cause_accuracy`
concern, not a fabrication one, and is out of scope for
`validate_no_fabrication`.

---

## 5. Effect on the committed numbers

`score_match` now scores real matches correctly instead of scoring
every one FALSE_POSITIVE. `validate_no_fabrication` no longer aborts on
legitimate evidence. `score_abstentions` was also fixed to dedupe per
order (`is_resolvable` is a per-order signal; without the dedup
`correct_abstention_rate` could exceed 1.0).

The `rules_only` HELD_OUT baseline in `ABLATION.md` §4 is the first
measurement taken with the corrected instrument. There is no "before"
to compare against — the instrument could not produce a number before
the fix.
