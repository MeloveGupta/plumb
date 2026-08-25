# Plumb — Implementation Plan

Sixth document. Execution schedule for `PLUMB_PRD.md`, `PLUMB_TRD.md`, `PLUMB_APP_FLOW.md`, `PLUMB_UIUX_BRIEF.md`, `PLUMB_BACKEND_SCHEMA.md`.

**Deadline: 5 September 2026.** Target submission **4 September**, leaving one day of buffer. Deadlines without buffer are deadlines you miss.

---

## 0. Calendar

| Day | Date | Phase | Focus |
|---|---|---|---|
| **D0** | **Sun 23 Aug** | **Unblock** | **Route approval request + repo skeleton — today** |
| D1 | Mon 24 Aug | P0 | Schema, rules module |
| D2 | Tue 25 Aug | P0 | Generator |
| D3 | Wed 26 Aug | P0 | Scorer · **GATE P0** |
| D4 | Thu 27 Aug | P1 | Ingest + normalisation |
| D5 | Fri 28 Aug | P1 | Matcher · **GATE P1** |
| D6 | Sat 29 Aug | P2 | Checks D01–D03 |
| D7 | Sun 30 Aug | P2 | Checks D04–D06 |
| D8 | Mon 31 Aug | P2 | Checks D07–D08 · **GATE P2** |
| D9 | Tue 1 Sep | P3 | Tool layer + loop |
| D10 | Wed 2 Sep | P3 | Gates + ablation arms |
| D11 | Thu 3 Sep | P3 | Ablation run · **GATE P3** |
| D12 | Fri 4 Sep | P4 | Reports, README, video · **SUBMIT** |
| D13 | Sat 5 Sep | — | **Buffer. Do not plan work here.** |

**Estimated effort: ~95 hours across 13 days — roughly 7 hours a day.** That is heavy alongside coursework. Read the descope ladder (§7) now, not on D10, so that cutting is a decision you already made rather than a panic.

---

## 1. D0 — today, before anything else

Three tasks. Ninety minutes. The first one has unknown latency and everything downstream assumes it.

### T0.1 — Razorpay Route test-mode setup ⏱ 45m · **START NOW**
1. Razorpay account, test mode, generate keys
2. Create 3 Linked Accounts (sellers)
3. Create stakeholders for each
4. Request product configuration for each — **this is the approval step with unknown turnaround**
5. Note the exact submission time in `DEVLOG.md`

**If approval hasn't landed by end of D4, invoke the fixture fallback (§7.1).** Do not idle waiting for it.

### T0.2 — Repo skeleton ⏱ 30m
`uv init`, `pyproject.toml`, package dirs per TRD §3, `.gitignore` (must exclude `data/*/truth/`), MIT licence, empty `CLAUDE.md`.

### T0.3 — `DEVLOG.md` entry one ⏱ 15m
Dated. What you're building, why Track 04, what you expect to be hard. The track asks what broke and how you recovered — this file cannot be convincingly reconstructed on D12.

---

## 2. P0 — Foundation & proof harness · D1–D3

**The generator and scorer exist before the engine does.** You cannot build toward a metric you cannot yet measure.

| ID | Task | Governs | ⏱ | Done when |
|---|---|---|---|---|
| P0.1 | CI skeleton: import-boundary AST test, no-float lint, STRICT-schema test | TRD §3.1, §9 | 2h | All three fail correctly against a deliberate violation |
| P0.2 | Pydantic domain models | PRD §4 | 2h | Round-trip a fixture of every entity |
| P0.3 | `schema/run.sql` full DDL + triggers + indexes | Schema §3 | 3h | Applies clean; all 10 schema tests pass |
| P0.4 | `schema/truth.sql` | Schema §4 | 30m | Applies clean |
| P0.5 | **Rules module** — `RateRule`, `Basis` enum, as-of lookup, `VERIFIED_ON` | PRD §5 | 3h | Hand-computed tests for TDS-on-gross and TCS-on-net both pass |
| P0.6 | Generator core: seeded world (orders → payments → transfers → settlements → bank) | TRD §8.1 | 5h | 200 clean records, zero defects |
| P0.7 | Three heterogeneous source writers (CSV-rupees-IST / JSON-paise-epoch / CSV-narration) | Schema §2 | 2h | Formats genuinely differ; UTR is buried in narration |
| P0.8 | Defect injectors D01–D08, declarative config | PRD §6 | 4h | Each injectable in isolation; `within_tolerance` read from the live profile |
| P0.9 | Truth writer | Schema §4 | 1h | Every record has a truth row |
| P0.10 | **Byte-identical determinism test** | TRD §8.1 | 1h | Two runs, same seed → identical file hashes |
| P0.11 | Scorer: all 8 metric families | PRD §7 | 5h | Formulas match the PRD exactly |
| P0.12 | Scorer vs stub engine returning zero matches | TRD §8.3 | 1h | Full metrics table, all zeros, no crash |
| P0.13 | Configs `config_a.yaml` (tune) / `config_b.yaml` (held-out) | PRD §8.4 | 1h | Different defect mixes, both committed |

### 🚦 GATE P0 — end of D3
- [ ] Generator produces byte-identical output across two runs
- [ ] Scorer produces a complete metrics table against a stub engine
- [ ] CI green, no API key
- [ ] Import-boundary test fails on a deliberate violation

**Do not start P1 until all four are true.** A scorer built after the engine will be built to flatter the engine.

---

## 3. P1 — Ingest & match · D4–D5

| ID | Task | ⏱ | Done when |
|---|---|---|---|
| P1.1 | Three source adapters + `normalise()` | 3h | Each declares its own tz, units, id scheme |
| P1.2 | **UTR extraction from bank narration** | 1.5h | Handles the messy cases; failures → nullable, not crash |
| P1.3 | `transform_log` writer | 1h | Every normalisation logged before/after |
| P1.4 | Quarantine path | 1h | Bad rows counted, never dropped |
| P1.5 | Matcher P0 identity | 1.5h | Confidence 1.00, `rule_id` on every match |
| P1.6 | Matcher P1 exact composite | 1h | |
| P1.7 | Matcher P2 grouped n:1 / 1:n, bounded subset search (cap 5), stable sort | 3h | Deterministic across runs |
| P1.8 | Matcher P3 tolerance band | 1.5h | Profile from config, printed in header |
| P1.9 | Hypothesis property tests | 2h | No record claimed twice; totals conserved |
| P1.10 | Determinism harness — 5 runs, hash resolutions | 1h | L1 score = 1.000 |
| P1.11 | CLI run output v1 + conservation line | 2h | Matches UIUX_BRIEF §3.1 layout |

### 🚦 GATE P1 — end of D5
- [ ] `determinism_score = 1.000` on L1 across 5 runs
- [ ] Auto-match ≥ 85% on T2
- [ ] Conservation check balances
- [ ] Every match carries a resolvable evidence chain

---

## 4. P2 — Verify · D6–D8

The differentiator. Also the phase most likely to overrun — hold the line at eight checks.

| ID | Task | ⏱ | Done when |
|---|---|---|---|
| P2.1 | `SettlementUnit` builder (joined lifecycle view) | 2h | Built for matched **and** unmatched |
| P2.2 | `Check` protocol + registry | 1h | Order-free, independently testable |
| P2.3 | **D01** commission rate drift (as-of rate card) | 2h | Catches mid-period rate-card change on wrong cohort |
| P2.4 | **D02** short settlement in tolerance ← flagship | 2h | Fires *inside* the band, not outside |
| P2.5 | **D03** refund netting error | 1.5h | |
| P2.6 | **D04** TCS basis error | 2h | Gross-vs-net-of-returns proven by test |
| P2.7 | **D05** TDS rate/basis error | 2h | Catches stale 1%, net-basis, missing line |
| P2.8 | **D06** orphaned hold | 1h | `on_hold=1 AND on_hold_until IS NULL` + age |
| P2.9 | **D07** reversal without refund | 1h | |
| P2.10 | **D08** GST-on-MDR vs tax invoice | 1.5h | |
| P2.11 | `recompute_trace` emitter | 2h | Structured steps, paise units, hand-verifiable |
| P2.12 | `on_matched_record` flag + CLI sub-line | 1h | *"of 31 findings: 24 on MATCHED"* prints |
| P2.13 | T4 null-set run | 1h | **Zero** findings |
| P2.14 | Variance bar, CLI rendering | 1.5h | True proportional scale |

Every check gets a **hand-computed fixture test** — you work the arithmetic on paper, then assert it. Do not generate expected values from the code under test.

### 🚦 GATE P2 — end of D8
- [ ] Defect recall ≥ 80% on T2 (held-out)
- [ ] **Zero** false alarms on T4
- [ ] Every check has a hand-computed fixture
- [ ] Rules module `VERIFIED_ON` set within 30 days

---

## 5. P3 — The agent · D9–D11

Highest ceiling, highest risk. This phase decides whether the submission reads as an AI product or a reconciliation script.

| ID | Task | ⏱ | Done when |
|---|---|---|---|
| P3.1 | 7 read-only tools + `agent_call` logging | 3h | Fixed signatures, no free-form queries |
| P3.2 | Versioned prompt files, hashed into manifest | 1.5h | Abstention stated as a valid outcome |
| P3.3 | Tool loop: iteration cap 8, token budget | 3h | Budget exhaustion → recorded escalation |
| P3.4 | `submit_resolution` schema + validation | 2h | Structured tool call, never parsed text |
| P3.5 | **Fabrication gate** | 1.5h | Bad evidence ref fails the run — test it |
| P3.6 | **Downgrade gate** + `was_downgraded` | 1.5h | Code overrides the model's claimed autonomy |
| P3.7 | Abstention path + `what_would_resolve_it` | 1.5h | DB rejects escalation without it |
| P3.8 | `rules_only` arm as a real code path | 1h | Exercised in CI, not hand-edited |
| P3.9 | `llm_only` arm | 1.5h | |
| P3.10 | Cassette record + CI replay | 2.5h | **CI green with no API key** |
| P3.11 | Write ablation prediction, then run all three arms | 2h | Prediction committed *before* the run |
| P3.12 | `ABLATION.md` | 1.5h | Prediction, result, honest interpretation |

### 🚦 GATE P3 — end of D11 · **the architecture decision**
- [ ] `hybrid` beats `rules_only` on residual resolution
- [ ] CI green with no API key
- [ ] Fabrication gate demonstrably fails a corrupted run

**If hybrid does not beat rules-only:** do not hide it. You have two options, and both are defensible. Deepen L3 on D12 if the cause is diagnosable, or ship the honest finding — *"on this problem, at this scale, the deterministic layer did the work; here is where the LLM did and did not help."* A rigorous negative result presented plainly beats a flattering result nobody believes. Say which you chose and why.

---

## 6. P4 — Reports, docs, video · D12

One day. It is tight because P0–P3 carry the weight; if you arrive here with debt, use the descope ladder rather than eating the buffer.

| ID | Task | ⏱ | Done when |
|---|---|---|---|
| P4.1 | `close.md` waterfall, held bucket in ochre | 1.5h | UI/UX §4.2 layout |
| P4.2 | `exceptions.md`, ₹-escalated-% in header | 1h | No truncation |
| P4.3 | JSONL projections + round-trip test | 1.5h | Every field traces to a column |
| P4.4 | `README.md` — the 60-second surface | 1.5h | Metrics table, `HELD_OUT`, one command |
| P4.5 | `ARCHITECTURE.md` | 1.5h | Why L1/L2 are deliberately not AI |
| P4.6 | README-vs-metrics CI check | 30m | Fails on drift |
| P4.7 | **Fresh-container reproduce test** | 1h | Clean clone, no API key, one command |
| P4.8 | Anti-slop checklist pass | 1h | UI/UX §6, every box |
| P4.9 | Video: record + edit to the beat sheet | 3h | App Flow §6 timings |
| P4.10 | **Submit** | 30m | Form, repo link, video link |

**S3 (The Ledger) is not on this list.** It only happens if you reach end of D11 with all gates green and genuine slack. It is the first thing cut and should never be the reason P4 slips.

---

## 7. Descope ladder

Decide now. Cut in this order, top first.

| # | Cut | Trigger |
|---|---|---|
| 1 | The Ledger (S3) | Default — assume it's cut |
| 2 | T5 external validity (real Razorpay data) | Route approval late, or D11 slack < 3h |
| 3 | D08, then D07, then D06 | P2 running past D8 |
| 4 | Agent hypothesis *ranking* → single hypothesis | P3 running past D10 |
| 5 | `llm_only` ablation arm → 2-arm comparison | P3 running past D11 |
| 6 | Scale curve at 500 → report 50 and 200 only | P4 tight |

### 7.1 Never cut
Generator · scorer · ablation (≥2 arms) · honest exception list · rules-module citations · fresh-container reproduce · video.

**Those seven are the submission.** Everything else is supporting evidence.

### 7.2 Fixture fallback — if Route approval is late
Hand-write realistic Razorpay-shaped JSON fixtures from the API docs (`fixtures/razorpay/`). The generator produces Razorpay-shaped data anyway, so nothing structural depends on live access. Note the substitution honestly in the README — using documented response shapes because sandbox provisioning was pending is a perfectly respectable engineering decision, and claiming live data you didn't have is not.

---

## 8. Working with Claude Code

### 8.1 Session scoping
One session per task cluster, not per phase. A session that spans P2.3 through P2.10 will drift by the fourth check.

Per session, load: `CLAUDE.md` (always) + the one governing doc section + the task's acceptance criteria. **Do not paste all six documents into a session** — context bloat causes exactly the constraint-drift `CLAUDE.md` exists to prevent.

### 8.2 Start every session with the gate
Open with the acceptance criteria, not the task description. *"This session is done when defect recall ≥ 80% on T2 and zero false alarms on T4"* produces better work than *"implement the D04 check."*

### 8.3 End every session with four things
1. Run the test suite; commit only green
2. Push; confirm CI green
3. `DEVLOG.md` entry — what broke, what you changed
4. If a `# TRD-DEVIATION:` or `# PRD-DEVIATION:` comment was added, read it and decide

### 8.4 Watch for these drifts
| Drift | Correction |
|---|---|
| Floats appear in money paths | Point at TRD §2. Non-negotiable. |
| L1/L2 start calling the LLM | Point at PRD §3. They are pure functions. |
| Defect classes multiply past eight | Depth, not breadth. |
| "Forecast" appears in output | It is a cash position. |
| Metrics get hand-edited into a doc | Every number comes from a run. |
| L3 determinism gets "fixed" | Sub-1.000 is the finding, not a bug |

---

## 9. Parallel tracks

Running alongside the build, every day. Neither survives being left to D12.

**`DEVLOG.md` — 10 min/day.** Dated. Real failures, real fixes. This is the raw material for *"what broke and how you recovered."*

**Video capture — as you go.** Every time something looks good on screen, record it. Terminal runs, the first time D02 fires, the ablation table landing. On D12 you edit; you do not shoot. The single most valuable clip is **the first real run where a defect fires on a record that matched cleanly** — capture it the moment it happens on D6 or D7.

---

## 10. Daily ritual

**Morning, 5 min:** read today's tasks and their acceptance criteria. Note the one thing that must be true by tonight.

**Evening, 15 min:**
- [ ] Tests green? Commit.
- [ ] Pushed? CI green?
- [ ] `DEVLOG.md` written?
- [ ] Metrics moved in the right direction? (`reports/history.jsonl`)
- [ ] Any footage worth keeping?
- [ ] Behind? **Consult the ladder tonight, not on D11.**

---

## 11. Replan triggers

| If, by… | And… | Then |
|---|---|---|
| End D3 | GATE P0 not met | Take D4 for P0. Cut D08+D07 to pay for it. |
| End D5 | Match rate < 80% | Ship P3 as tolerance-band-only; move effort to L2 — the verifier is the differentiator, not the matcher |
| End D8 | Fewer than 5 checks working | Ship 5. Say so plainly. Five well-tested beats eight half-built. |
| End D10 | Agent loop not closing | Cut to 2-arm ablation, single hypothesis, ship |
| End D11 | GATE P3 failed | §5 — deepen or ship the honest negative |
| Any point | Two consecutive days lost | Drop to ladder rung 3 immediately and re-baseline |

---

## 12. The finish line

Submission is complete when all eight are true:

1. Public repo, README readable in 60 seconds
2. `make reproduce` works on a **fresh container**, no API key
3. Every headline metric labelled `HELD_OUT`
4. `ABLATION.md` carries prediction *and* result
5. `EXCEPTIONS.md` complete and untruncated, ₹-escalated-% in the header
6. Rules module cites every rate with statute and effective date, `VERIFIED_ON` current
7. 5-minute video, every on-screen number traceable to a committed report
8. `DEVLOG.md` shows real failures and real recoveries

**Then stop.** On D13, do not add a feature. Re-read the README as a stranger would, fix what's unclear, and submit.
