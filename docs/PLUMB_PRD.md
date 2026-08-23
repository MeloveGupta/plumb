# Plumb — Product Requirements Document

**A settlement assurance engine for Razorpay Route platforms.**

Target: Razorpay AI Buildathon 2026, Track 04 (AI Finance Controller).
Applications close **5 September 2026**. Deliverables: public GitHub repo, 5-minute pitch video, architecture write-up, reproducible setup.

---

## 0. How to use this document

This PRD is decision-complete on the things that are easy to get wrong and expensive to get wrong: metric definitions, tax rules, defect detection logic, and test design. Those are specified exactly. **Do not re-derive them, and do not "improve" them without flagging.**

Implementation is deliberately left open: language idioms, module boundaries within a layer, libraries, CLI ergonomics, storage. Use your judgment there.

Three standing rules:

1. **When a spec here conflicts with what you think is better, implement the spec and leave a `# PRD-DEVIATION:` comment explaining your objection.** Do not silently diverge.
2. **Never fabricate a number.** Every metric in every report must be computed from a real run. If a value is unavailable, print `NOT_MEASURED`, never a placeholder.
3. **Tax constants are sourced facts, not parameters to tune.** They live in one versioned module (§5) with citations. Do not inline them anywhere else.

---

## 1. Mission

> Reconciliation proves the numbers tie. Assurance proves they're right.
> A settlement can reconcile perfectly and still be short.

Every product in this market competes on **auto-match rate**. Plumb competes on **what the match rate is hiding** — matches that look clean and are wrong, and money that goes missing without ever raising an exception.

**Primary user:** the finance lead at a marketplace platform that uses Razorpay Route to split customer payments across multiple sellers.

**Primary job:** for one settlement cycle, prove that what the platform *intended* to happen (its own ledger) equals what *actually* happened (Razorpay) equals what *arrived* (bank) — and surface, in rupees, everything that doesn't.

**Whose errors are we catching?** Predominantly the **platform's own** — commission logic drifting from seller rate cards, refunds netted wrong, tax lines computed on the wrong basis, transfers held and forgotten. Razorpay-side checks exist in the taxonomy (D08) but are not the headline. Plumb is the merchant's second pair of eyes on their own books.

---

## 2. Track compliance map

Build against these. Every one must be demonstrably satisfied.

| Requirement (their words) | Where satisfied | Gate |
|---|---|---|
| "Build an **agent**" | L3 investigator | Agent must be the protagonist in README and pitch, not a postscript |
| "closes **one** finance-ops loop" | One loop, stated in README line 1 | See §2.1 |
| "**50+ record batch**" | Canonical batch = 200 records; a labelled 60-record batch with full per-record reporting must also ship | Panelist can audit every record |
| "of **synthetic data**" | Seeded generator (§8) | `--seed` reproduces byte-identical batches |
| "reporting its **match rate**" | §7, reported **first** | Their metric leads; ours follow |
| "**exceptions it could not resolve**" | §10.4 honest exception list | Every entry states what was tried and what would resolve it |
| Bar: **throughput** | §7.8 | Named first in their bar — do not skip |
| Bar: **measured accuracy** | §7 | Held-out (§8.4) |
| Bar: **honest exception list** | §10.4 | |
| "One cherry-picked match proves nothing" | Batch-level reporting + T3 adversarial tier + ablation (§9) | No single-record demos anywhere |

### 2.1 The one-loop statement

README line 1, verbatim:

> **One loop: settlement assurance for a single Razorpay Route settlement cycle — collection → split → deduction → settlement → bank credit → books.**

Everything built sits inside that arc. If a feature doesn't, it is out of scope.

---

## 3. Architecture — four layers

The layering is the argument. Each layer exists for a stated reason.

```
L0  INGEST      3 sources → canonical normalised records
L1  MATCH       deterministic, no LLM        → matched / candidate / unmatched
L2  VERIFY      deterministic, no LLM        → recompute obligations, diff vs actual
L3  INVESTIGATE agent, LLM                   → residual + L2 flags only
L4  REPORT      close pack + metrics + exception list
```

**L1 and L2 are pure functions.** Same input, same output, every time. This is a design commitment, not an accident — it is what makes the output auditable, and it is stated explicitly in the pitch.

**L3 is the only place an LLM runs.** If L3 does not measurably beat a rules-only baseline on the residual (§9), the architecture has failed and we need to know before submission.

### 3.1 Layer responsibilities

**L0 — Ingest & normalise.** Three sources, each with its own vocabulary for the same transaction (date formats, identifier schemes, counterparty naming, timezone). Normalisation is a named, separately tested stage — not a helper function.

| Source | Represents | Origin |
|---|---|---|
| Intent ledger | What the platform meant to happen | Synthetic (generator) |
| Razorpay reality | What Razorpay actually did | Test-mode API + recorded fixtures |
| Bank statement | What money arrived | Synthetic (generator) |

**L1 — Deterministic matcher.** Exact-key matching (order_id, payment_id, transfer_id, UTR) → n-way grouping (1:1, 1:many, many:1) → declared tolerance bands. Target 85–92% auto-match, which is honest against the 85–95% industry production benchmark. Every match emits a `rule_id` and evidence pointers.

**L2 — Obligation verifier.** *Matched records still get verified.* Recomputes from first principles what each party should have received, diffs against actual, emits typed defect findings (§6). This layer is the differentiator — it catches money that reconciles cleanly.

**L3 — Exception investigator.** Operates only on L1 residual + L2 findings. Contract in §10.

**L4 — Controller's close.** Cash position waterfall, metrics table, itemised leakage, honest exception list, unclaimed tax credit total.

---

## 4. Domain model

Minimum entities. Extend if needed; do not remove.

```
Order              order_id, seller_id, gross_amount, category, placed_at,
                   status, is_interstate
OrderLine          line_id, order_id, sku, taxable_value, gst_rate, gst_amount
Intent             order_id, seller_id, expected_seller_amount,
                   expected_commission, commission_rate_applied,
                   expected_tcs, expected_tds, rate_card_version
Payment            payment_id, order_id, amount, method, status, captured_at,
                   fee, tax          # Razorpay
Refund             refund_id, payment_id, amount, created_at
Transfer           transfer_id, payment_id, linked_account_id, amount,
                   on_hold, on_hold_until, settled_at     # Route
Reversal           reversal_id, transfer_id, amount, created_at
Dispute            dispute_id, payment_id, amount, status, deducted_amount
SettlementRecon    entity_id, entity_type, settlement_id, utr, amount,
                   fee, tax, debit, credit, settled_at, dispute_id
BankCredit         bank_ref, utr, amount, credited_at, narration
SellerRateCard     seller_id, category, commission_rate, effective_from,
                   effective_to, version
```

**Note on rate cards:** they are versioned and time-bounded. Mid-period rate changes applied to the wrong orders is defect D01 and must be representable.

---

## 5. Tax & fee rules module

**Single module. Versioned. Every constant carries an inline source comment with statute reference and effective date.** Nothing here may be hardcoded elsewhere.

### 5.1 Income-tax TDS on e-commerce

| Field | Value |
|---|---|
| Rate | **0.1%** |
| Basis | **GROSS** amount of sales facilitated — before commission, MDR, platform fees, logistics, or buyer refunds |
| Current provision | **Section 393(1), Table Sl. No. 8(v), payment code 1035**, Income-tax Act 2025 — effective 1 April 2026 |
| Legacy provision | Section 194-O, Income-tax Act 1961 (still the common name; keep as an alias) |
| Rate history | 1% → 0.1% effective 1 October 2024 (Finance (No. 2) Act 2024) |
| Non-PAN floor | 5% where participant has not furnished PAN/Aadhaar — §394A (legacy §206AA) |
| Threshold | ₹5,00,000/year, **resident Individuals and HUFs only**. Companies from the first rupee. |
| GST treatment | Excluded from the gross amount if separately indicated on the invoice |

**The gross-vs-net asymmetry is the single most important rule in this module.** A seller sees ₹100 gross, ₹15 commission, ₹2 MDR, ₹83 net settlement — and TDS deducted on the ₹100. Model this exactly.

### 5.2 GST TCS on e-commerce

| Field | Value |
|---|---|
| Rate | **0.5%** — 0.25% CGST + 0.25% SGST (intra-state) or 0.5% IGST (inter-state) |
| Basis | **NET** value of taxable supplies = aggregate taxable supplies through the operator in the month, **minus** supplies returned in that month. Excludes the GST component itself. |
| Provision | Section 52, CGST Act 2017 |
| Effective | 0.5% since **10 July 2024** (CBIC Notification No. 15/2024; IGST Notification No. 01/2024). Previously 1%. |
| Applicability | Only where the platform is an **e-commerce operator** — i.e. collects payment on behalf of third-party sellers. A pure D2C merchant selling its own goods is **not** an ECO and attracts no TCS on its settlements. |

> ⚠️ **Many online sources still state 1%.** They are stale. The correct current rate is 0.5%. Do not "correct" this to 1%.

### 5.3 GST on fees

18% on MDR and on platform commission. Recoverable by the recipient as input tax credit — so a mismatch between settlement-file GST and the tax invoice is an ITC exposure, not just a rounding nit (see D08).

### 5.4 MDR

**Not statutory.** MDR is contracted and varies by payment method (UPI / card / netbanking / wallet). It belongs in a **merchant rate-card fixture**, never in the tax module. D02 detects drift from the contracted rate.

### 5.5 Verification gate

Before submission, re-verify every rate and effective date above against a primary source (CBIC notification, Income Tax Department, or Razorpay docs). Record the verification date in the module header. **A wrong tax constant in front of a fintech panel invalidates everything else in the submission.**

---

## 6. Defect taxonomy

Ship **exactly these eight**. Do not add more; add depth instead. Each is generatable, detectable, and quantifiable in rupees.

| ID | Name | Side | Detection |
|---|---|---|---|
| **D01** | `COMMISSION_RATE_DRIFT` | Platform | Applied commission ≠ seller's contracted rate for that category at the order's timestamp. Catches mid-period rate-card changes applied to the wrong cohort. |
| **D02** | `SHORT_SETTLEMENT_IN_TOLERANCE` | Either | Recomputed net > actual net, and the delta falls **inside** L1's tolerance band. Reconciles clean, still short. **Flagship defect.** |
| **D03** | `REFUND_NETTING_ERROR` | Platform | Refund not netted from seller obligation, or netted twice, or netted in the wrong period. |
| **D04** | `TCS_BASIS_ERROR` | Platform | TCS computed on gross instead of net-of-returns; or applied where the platform is not an ECO; or wrong intra/inter-state split. |
| **D05** | `TDS_RATE_OR_BASIS_ERROR` | Platform | TDS computed on net instead of gross; or at the legacy 1% rate; or missing; or non-PAN 5% floor misapplied; or threshold wrongly applied to a company. |
| **D06** | `ORPHANED_HOLD` | Platform | Transfer with `on_hold = true` and `on_hold_until` null, aged beyond threshold. Money collected, split, and silently parked. |
| **D07** | `REVERSAL_WITHOUT_REFUND` | Platform | Reversal exists with no corresponding customer refund — seller debited for a refund the customer never received. |
| **D08** | `GST_ON_MDR_INVOICE_MISMATCH` | Razorpay | Sum of GST-on-fee across the settlement file ≠ the period tax invoice. ITC claim exposure. |

Each finding carries: `defect_id`, `severity`, `amount_at_risk_inr`, `affected_entities[]`, `evidence[]`, `recompute_trace`.

**`recompute_trace` is mandatory** — the full arithmetic from inputs to expected value, so a human can check the claim by hand.

---

## 7. Metrics

**These formulas are exact. Implement them as written.** Every metric is computed against generator ground truth (§8), never self-assessed by the LLM.

Report in this order. Their metric leads.

### 7.1 Auto-match rate *(reported first — their word)*
```
auto_matched_records / total_records
```

### 7.2 Match precision
```
correct_auto_matches / total_auto_matches
```
Of the matches we made, how many were right. **Almost nobody in this market publishes this.**

### 7.3 Match recall
```
correct_auto_matches / records_having_a_true_match
```

### 7.4 Silent-error rate *(headline metric)*
```
(auto_matches that are WRONG and were NOT flagged as exceptions) / total_auto_matches
```
Wrong matches that passed through cleanly. This is the number the product exists to drive down. Lead the pitch with it.

### 7.5 Defect detection
```
defect_recall     = defects_detected / defects_injected
defect_precision  = true_defects_flagged / total_flags        # false-alarm complement
root_cause_accuracy = correctly_classified / defects_detected
```

### 7.6 Money
```
leakage_caught_inr   = Σ amount_at_risk of correctly identified defects
leakage_missed_inr   = Σ amount_at_risk of undetected defects
false_alarm_inr      = Σ amount_at_risk claimed on non-defects
```
Report all three. Reporting only the first is dishonest.

### 7.7 Abstention quality
Ground truth labels each defect `resolvable_from_available_data: bool`.
```
correct_abstention_rate = correctly_escalated_unresolvable / total_unresolvable
over_abstention_rate    = escalated_but_resolvable / total_resolvable
```
Abstention is a scored behaviour, not a failure.

### 7.8 Throughput *(named first in their bar)*
```
records_per_second, wall_clock_seconds_total,
llm_tokens_per_1000_records, inr_cost_per_1000_records
```
Plus a scaling curve: 50 → 200 → 500 records.

### 7.9 Determinism
Run the identical batch **5 times**. Hash each record's final resolution.
```
determinism_score = records_identical_across_all_5_runs / total_records
```
L1 and L2 must score **1.000**. If they don't, there is a bug. L3's score is a finding, not a target.

---

## 8. Test corpus

### 8.1 The generator is the proof engine — build it first

It emits `(dataset, ground_truth)` as a pair. Every record carries a hidden truth block: its true counterpart, its true obligation breakdown, whether a defect was injected and of which class, and `resolvable_from_available_data`.

**The engine never sees ground truth. Only the scorer does.** Enforce this with a hard module boundary, not a convention.

Seeded: `--seed 42` regenerates byte-identical batches. A panelist must be able to reproduce every number in the report.

### 8.2 Five tiers

| Tier | Name | Purpose |
|---|---|---|
| **T1** | Clean | Happy path. Establishes the ceiling. |
| **T2** | Messy | Format drift, timezone offsets, 1:many and many:1 settlements, partial settlement, rounding, name variants. Realistic production noise. |
| **T3** | **Adversarial** | Engineered to produce **plausible-but-wrong** matches: two orders identical in amount on the same day; a refund shaped like a short settlement; commission at the wrong slab that still nets to a believable figure. **This tier is where the submission is won.** |
| **T4** | Null set | **Zero** injected defects. Does the agent hallucinate exceptions? Directly tests false-alarm behaviour. |
| **T5** | External validity | Real Razorpay test-mode settlement data. Proves the system isn't overfit to our own generator. |

### 8.3 Canonical batches
- `batch_audit_60` — 60 records, full per-record reporting, hand-auditable
- `batch_main_200` — headline metrics
- `batch_scale_500` — throughput curve only

### 8.4 Held-out discipline

Tune on generator **config A**. Evaluate on generator **config B** — different defect mix, different distributions, frozen *after* the engine is frozen. Both configs committed.

**Every reported number is labelled `IN_SAMPLE` or `HELD_OUT`.** Volunteering that distinction is a stronger credibility signal than any single metric.

---

## 9. The ablation study

**Highest-value artifact in the repo. Do not cut it.**

Same held-out batch, three configurations, all metrics from §7:

| Config | L1 | L2 | L3 |
|---|---|---|---|
| `rules_only` | ✅ | ✅ | ❌ (residual escalated unresolved) |
| `llm_only` | ❌ | ❌ | ✅ (LLM does everything) |
| `hybrid` | ✅ | ✅ | ✅ |

**Expected shape** — state the prediction in the repo *before* running, then report what actually happened:
- `llm_only` — plausible auto-match rate, poor determinism, poor match precision
- `rules_only` — perfect determinism, high precision, high unresolved residual
- `hybrid` — determinism of rules where it matters, meaningfully better residual resolution

**This is the pass/fail gate for the architecture.** If `hybrid` does not beat `rules_only` on residual resolution, L3 is not earning its place and must be deepened before submission.

---

## 10. L3 agent contract

### 10.1 Scope
Operates **only** on L1 residual + L2 findings. Never re-matches what L1 already matched. Never recomputes what L2 computed.

### 10.2 Required behaviours

The agent must do things a rules engine provably cannot. If it only paraphrases exceptions, the design has failed.

1. **Rank competing hypotheses** for the same break — plural, ordered, with reasoning. Not a single description.
2. **Choose which evidence to gather next**, and decide when it has enough. Adaptive, not a fixed script.
3. **Resolve genuine ambiguity** where the answer isn't derivable from data alone.
4. **Abstain well** — recognise unresolvable cases and say so, with what would resolve them.

### 10.3 Tools
Bounded, whitelisted, **read-only**. No write-back to any ledger. Suggested set:
```
fetch_payment(payment_id)
fetch_transfer(transfer_id)
fetch_refunds_for_payment(payment_id)
fetch_settlement_recon(date)
fetch_dispute(dispute_id)
fetch_rate_card(seller_id, as_of)
search_intent_ledger(query)
```
Every call logged with arguments, result hash, and timestamp.

### 10.4 Output — three outcomes

| Outcome | Condition |
|---|---|
| `AUTO_RESOLVED` | amount < ₹ threshold **AND** confidence > threshold |
| `PROPOSED` | evidence assembled, awaiting human approval |
| `ESCALATED_UNRESOLVED` | cannot resolve — **first-class outcome, not a failure** |

Every output carries:
```
exception_id, outcome, confidence, hypotheses_considered[],
evidence_chain[], recompute_trace, amount_at_risk_inr,
what_was_tried, what_would_resolve_it
```

The last two fields are what make the exception list *honest*. They are mandatory on every `ESCALATED_UNRESOLVED`.

### 10.5 Hard constraints
- **Read-and-recommend only.** No write-back in v1. This is a deliberate control position, stated as such in the pitch.
- **No parametric answers.** If the evidence doesn't support a conclusion, escalate. Never generate a plausible resolution from model knowledge.
- **No unsourced numbers.** Every rupee figure traces to a record or a `recompute_trace`.

---

## 11. Repo & deliverables

```
/plumb
  README.md              # one-loop statement, headline metrics, quickstart
  ARCHITECTURE.md        # 4 layers, why each exists, why L1/L2 are not AI
  METRICS.md             # definitions + latest held-out results
  ABLATION.md            # prediction, results, interpretation
  EXCEPTIONS.md          # honest exception list, latest run
  /src
    /ingest /match /verify /agent /report
    /rules                 # tax module — §5, sourced
  /generator
    /configs               # config_a.yaml (tune), config_b.yaml (held-out)
  /eval
    /scorer /tiers         # T1–T5
  /fixtures                # recorded Razorpay test-mode responses
  /reports                 # timestamped, committed run outputs
  .github/workflows/eval.yml
```

**CI:** every commit runs T1–T4, writes metrics to a versioned file. The metric history across the build is visible to the panel. Unusual for a student submission and cheap to add.

**Reproducibility gate:** a clean clone must reproduce every headline number with one documented command. Test this on a fresh container before submitting.

---

## 12. Build phases

| Phase | Days | Output | Gate — do not proceed until met |
|---|---|---|---|
| **P0** Generator + scorer | 1–3 | Seeded world, ground truth, T1–T4, all §7 metrics computable | Scorer runs against a stub engine and produces a full metrics table |
| **P1** L0 + L1 | 3–5 | Normalisation + deterministic matcher | Determinism = 1.000; auto-match ≥ 85% on T2 |
| **P2** L2 | 5–8 | 8 defect classes, tax module sourced | Defect recall ≥ 80% on T2; **zero** false alarms on T4 |
| **P3** L3 | 8–11 | Agent, tools, abstention | `hybrid` beats `rules_only` on residual resolution (§9) |
| **P4** Report + ablation + video | 11–13 | Close pack, ABLATION.md, pitch | Fresh-clone reproduction passes |

### 12.1 Cut list — in this order
1. L4 dashboard polish (a well-formatted CLI report is sufficient)
2. T5 external validity
3. Agent hypothesis *ranking* → fall back to single hypothesis
4. Defect classes D06 → D07 → D08

### 12.2 Never cut
- The generator and scorer
- The ablation
- The honest exception list
- The tax module's source citations

Those four **are** the submission.

---

## 13. Non-goals

Explicitly out of scope. Do not build these even if time allows.

- Write-back, journal entry posting, or any mutation of any ledger
- Live/production Razorpay keys — **test mode only**
- ML forecasting. The cash position is a settled / in-flight / held waterfall against the T+n schedule. **Call it a cash position, not a forecast.** Overclaiming here is fatal on a track about honest measurement.
- Multi-tenant auth, billing, onboarding
- A settlement Q&A chatbot
- More than eight defect classes
- Any UI beyond what the report needs

---

## 14. Standing risks

| Risk | Mitigation |
|---|---|
| **Reads as a rules engine with an LLM bolted on** | Highest-severity risk. L3 must be the protagonist in README, ARCHITECTURE, and pitch. The ablation must prove L3 earns its place. |
| **Scope creep in L2** | Eight defect classes is a ceiling, not a target. Depth over breadth. |
| **Wrong tax constant** | §5.5 verification gate before submission. Non-negotiable. |
| **Route test-mode setup friction** | Linked accounts need stakeholder + product configuration. **Start day 1.** Record fixtures immediately so the demo never depends on live setup. |
| **Metrics drift during the build** | CI writes every run to `/reports`. Never hand-edit a reported number. |
| **Tone** | Merchant-side assurance. Never "we found a bug in Razorpay." |

---

## 15. Pitch — the opening beat

Not a UI tour. This:

> "Here is a settlement that reconciles perfectly. The bank credit matches the settlement report to the paisa. Every tool on the market closes this and moves on.
>
> Here is the ₹4,180 missing from it. Here's which line, here's the contracted rate, here's the recomputation, here's the evidence chain.
>
> We found 23 more like it in this batch."

Then: metrics table → ablation → honest exception list.

The exception list is not an apology. It is the point.
