# Plumb — UI/UX Brief

Fourth document. Amends `PLUMB_PRD.md` §13.

---

## 0. Amendment to the PRD

PRD §13 lists as a non-goal: *"Any UI beyond what the report needs."* That stands for dashboards, admin panels, settings screens, and charts-for-the-sake-of-charts.

It was wrong in one respect: **it treated "no GUI" as "no design work."** The CLI output and the report artifacts are the interface. They are what a panelist reads. Leaving them unspecified is how a rigorous engine ends up looking like a weekend script.

Revised position — **three surfaces, in priority order**:

| # | Surface | Ships | Cut priority |
|---|---|---|---|
| **S1** | CLI output | Always | Never |
| **S2** | Report artifacts (`close.md`, `exceptions.md`, `metrics.md`, README) | Always | Never |
| **S3** | **The Ledger** — one web screen, the exception workspace | P4 only, if P0–P3 gates are met | **Cut first** |

S3 is conditional. A polished CLI with no web UI beats a half-finished dashboard by a wide margin. **If you reach day 11 and P3's ablation gate isn't met, S3 does not get built.** Nobody was ever rejected for shipping a beautiful terminal.

---

## 1. The problem this brief is solving

There is a recognisable look that says *generated, not designed*. A panelist at a payments company sees it twenty times a week. It reads as: this person prompted their way here and did not make any decisions.

**The tells, concretely:**

- Gradient hero, purple-to-blue or cream-to-terracotta
- Three stat cards in a row, big number + icon + subtle shadow
- Decorative icons on every heading
- `rounded-2xl` on everything, layered drop shadows
- Tailwind palette defaults — `indigo-500`, `slate-800`, `emerald-400`
- Inter at four weights with no hierarchy discipline
- Emoji in the interface
- A sidebar with eight nav items for a one-screen app
- Sparklines that encode nothing
- Centred empty states with an illustration and a friendly apology
- Animation on every element
- Generous whitespace masquerading as design, on a product about dense data

**The through-line: decoration in place of information.**

Our counter-position is not "make it prettier." It is **information density plus semantic discipline** — a screen that is full because the work is dense, where every visual property encodes something true. That is what a tool designed by someone who has used the tool looks like.

---

## 2. Design direction

### 2.1 Grounding

This product lives in the world of the Indian settlement statement: the UTR, the bank narration string, the ruled ledger column, the paise place, the auditor's tick. Its ancestor artifact is the **greenbar continuous-form accounting printout** — zebra-striped not for style but because alternating bands let the eye hold a row across a wide dense table.

That is the one heritage cue we take, and we take it **for its function**, not its nostalgia.

### 2.2 Palette — six values, three of them semantic

```
--paper       #F6F5F1   ground; ledger stock, warm-neutral
--band        #EFEEE8   zebra band; the greenbar cue, desaturated
--rule        #D8D6CE   hairlines and column rules
--ink         #17171A   primary text
--ink-muted   #6B6B70   labels, secondary
--variance    #A8321E   oxide red  — ONLY money at risk
--verified    #2F5F4A   ledger green — ONLY verified clean
--held        #8A6A1F   dark ochre — ONLY the on-hold bucket
```

**The rule that makes this work: the three semantic colours have exactly one meaning each and appear nowhere decoratively.** No red borders, no green buttons, no ochre headings. If something is oxide red, it is money at risk. A panelist will notice that discipline within thirty seconds of scrolling, and it will do more for perceived quality than any amount of polish.

Note the deliberate absences: no blue, no purple, no gradient anywhere, no shadow. Depth comes from hairline rules, which is how ledgers have always done it.

### 2.3 Type

**IBM Plex superfamily.** Not Inter.

| Role | Face | Use |
|---|---|---|
| UI / body | IBM Plex Sans | Labels, prose, navigation |
| **All figures, IDs, traces, CLI** | **IBM Plex Mono** | Every number in the product |
| Display | **IBM Plex Mono, 32–48px, uppercase, tracking −2%** | The one or two large moments |

Justification, not habit: Plex was commissioned for an engineering institution, it has genuine tabular figures, and the mono is a first-class member of the family rather than an afterthought. It reads as *instrument*, not *startup*.

**The one aesthetic risk: the display face is the mono.** No serif. In a product whose entire subject is figures, the headline treatment is set in the same face as the figures — large, uppercase, tight. Numbers are the typography.

Scale — three sizes, hard limit:
```
display   32px / mono / uppercase / -2% tracking
body      14px / sans / 1.5
micro     11px / mono / uppercase / +6% tracking   (column headers, labels)
```

**Every numeral uses `font-variant-numeric: tabular-nums`.** Non-negotiable. Figures that don't align in a column are the fastest way to look amateur in a finance product.

### 2.4 Alignment — the paise rule

All money is **right-aligned on the decimal**, always shown to two places, always with `₹`. `₹1,200.00`, never `₹1200` and never `₹1.2k`.

Abbreviating money is the single most common tell that a UI was built by someone who has never had to tie out a statement.

### 2.5 The signature — the Variance Bar

The one element this product is remembered by.

Per record, a single horizontal bar drawn at **true proportional scale**: expected obligation as a filled band in ink, actual as the measured extent, and the delta rendered as an oxide-red overhang past the expected mark.

```
D01  ord_00042   ████████████████▏▌       ₹  30.00 short
D02  ord_00087   ████████████▏▏           ₹   4.18 short
     ord_00088   ████████████████         ✓
```

Why this and not a chart: it encodes the actual arithmetic at actual scale, one row per record, in the same visual rhythm as the table it sits in. A screen of these shows you where the money went **before you read a single number**. It is data, not decoration — which is precisely the distinction §1 is about.

The bar appears in the CLI (box-drawing characters), in the reports (unicode), and in The Ledger (SVG). One idea, three renderings.

---

## 3. S1 — CLI design

The primary surface. Design it like a product, because it is one.

### 3.1 Run output

```
plumb · settlement assurance
run 2026-08-28T14:22:03Z-a3f9c1 · batch_main_200 · HELD_OUT · tolerance default_v1

  L0  ingest         812 records · 3 sources                    4 quarantined
  L1  match          738 matched  90.9%          74 unmatched
  L2  verify         812 verified                31 findings   ₹47,300 at risk
                     └─ 24 findings on MATCHED records
  L3  investigate    105 exceptions   62 resolved   28 proposed   15 escalated

  ledger balances    812 in · 812 accounted for ✓

  reports/2026-08-28T14:22:03Z-a3f9c1/
```

Design rules embedded there:

- **The L2 sub-line is the product's argument.** 24 defects on records that reconciled cleanly. Indent it, keep it, never suppress it.
- **The conservation check prints every run.** `812 in · 812 accounted for` — visible proof nothing was dropped. If it ever fails, that line goes oxide red and the run exits non-zero.
- **The tolerance profile is in the header.** A match rate without its tolerance band is not a number. Never print one without the other.
- **`HELD_OUT` / `IN_SAMPLE` in the header.** Always.
- **No spinner without a count.** Progress is expressed in records, not in animation.
- Colour: the same three semantics only. Degrade to plain text when not a TTY, and respect `NO_COLOR`.

### 3.2 Voice

Errors state what happened and what to do. They do not apologise and they are never vague.

```
✗ evidence reference does not resolve
  exception exc_00031 cites record pay_99999, which is not in this batch.
  This is a fabrication guard. The run has been stopped.
  Inspect: reports/{run_id}/agent_calls.jsonl
```

No "Oops!", no "Something went wrong", no emoji, no exclamation marks.

---

## 4. S2 — report artifacts

### 4.1 README — the 60-second surface

Per App Flow §5.1. Design notes:

- Headline metrics as a **table**, not badge images. Auto-match rate first. Every row carries `HELD_OUT`.
- The one command in a fenced block, above the fold.
- **One screenshot maximum** — the exception queue if S3 exists, otherwise the CLI run output.
- No badge row. No logo. No table of contents on a README this short.

### 4.2 `close.md` — the cash position

The waterfall is set as a ruled ledger, right-aligned on the decimal, with the held bucket in ochre and given its own visual weight:

```
                                              ₹
  gross collected                    12,84,000.00
    − Razorpay fees                    −25,680.00
    − GST on fees                       −4,622.40
    − platform commission            −1,92,600.00
    − TCS withheld  (0.5% net)           −5,140.00
    − TDS withheld  (0.1% gross)         −1,284.00
    − refunds, reversals, disputes      −48,200.00
  ─────────────────────────────────────────────────
  expected settleable                 10,06,473.60
      settled                          7,58,473.60
      in flight  (T+2)                 1,34,000.00
      ON HOLD    no release date       2,14,000.00   ← 6 transfers, oldest 47 days
```

The held line is the emotional centre of the whole report. Give it the ochre, give it the arrow, give it the age. That is money the platform collected and cannot see.

### 4.3 `exceptions.md`

Sorted by rupees descending, no truncation. Header states **₹ escalated as a percentage of ₹ processed** — the denominator is never buried.

Each entry is a ledger block, not a card: rule above, micro-label column on the left, recompute trace indented as a working note.

---

## 5. S3 — The Ledger (conditional)

**One screen. No nav. No dashboard.**

If it can't be described in one sentence, it isn't this screen. The sentence: *a two-pane workspace for working the exception queue.*

### 5.1 Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ PLUMB   run a3f9c1 · batch_main_200 · HELD_OUT · tolerance default_v1 │
├───────────────────────────────────┬──────────────────────────────────┤
│ QUEUE            105 · ₹47,300    │ exc_00031        D01             │
│                                   │ COMMISSION RATE DRIFT            │
│ ▸ exc_00031 D01  ███████▏  30.00  │ ─────────────────────────────    │
│   exc_00044 D02  █████▏     4.18  │ 1  gross order value             │
│   exc_00051 —    ░░░░░░     0.00  │       taxable 1,000.00           │
│   exc_00062 D06  ██████   214.00  │     + gst       180.00 = 1,180.00│
│   …                               │                                  │
│                                   │ 2  contracted commission         │
│ ─────────────────────────────     │       1,000.00 × 15.00%          │
│ 62 resolved  28 proposed          │       rate card v3, from 01 Jul  │
│ 15 escalated                      │                        = 150.00  │
│                                   │                                  │
│                                   │ 3  expected − actual             │
│                                   │       150.00 − 180.00 = −30.00   │
│                                   │ ─────────────────────────────    │
│                                   │ EVIDENCE   4 records             │
│                                   │ HYPOTHESES 2 considered          │
│                                   │ OUTCOME    proposed · conf 0.82  │
└───────────────────────────────────┴──────────────────────────────────┘
```

### 5.2 Rules

- **Zebra bands on the queue.** Functional, per §2.1.
- **Keyboard first.** `j`/`k` to move, `Enter` to open, `/` to filter, `e` to jump to escalated. A finance tool that requires a mouse was designed by someone who never used one.
- **The recompute trace is the hero of the right pane** — rendered as a stepped working note with the arithmetic visible, exactly as an accountant would show their work in a margin. Not a JSON dump, not a collapsed accordion.
- **Density is correct.** Rows are ~28px. If the queue looks crowded, it is right.
- **No charts.** The variance bars are the visualisation.
- **Static.** Reads committed report JSON. No backend, no auth, no live API. It is a viewer.

### 5.3 Empty and edge states

- Zero exceptions (T4 null set): the pane states the fact — `no exceptions · 200 records verified clean · T4 null set`. No illustration, no congratulation.
- Long IDs, 8-digit rupee figures, 12-step traces: build with the ugliest real record, not a tidy one.
- Reduced motion respected. Visible keyboard focus. Responsive down to a tablet — a phone is not a use case for this screen and pretending otherwise is where fake polish comes from.

### 5.4 Motion

One transition: the right pane cross-fades over 120ms on selection. **That is the entire motion budget.** Everything else is instant. In a tool people navigate at speed, animation is latency.

---

## 6. Anti-slop checklist

Run before submitting. Every line must be checkable.

**Ship-blocking**

- [ ] No gradient anywhere
- [ ] No `box-shadow` anywhere — depth is hairline rules only
- [ ] No Tailwind default palette values
- [ ] No decorative icons; no emoji in any interface
- [ ] No stat-card row
- [ ] No chart that isn't a variance bar
- [ ] `tabular-nums` on every numeral
- [ ] Money always `₹` + two decimals, right-aligned, never abbreviated
- [ ] Each semantic colour used for exactly one meaning, zero decorative uses
- [ ] Exactly three type sizes
- [ ] Every match rate printed alongside its tolerance profile
- [ ] Every metric printed alongside `HELD_OUT` / `IN_SAMPLE`
- [ ] No error message containing "Oops", "Something went wrong", or an exclamation mark
- [ ] Total motion budget: one 120ms cross-fade

**Judgment calls**

- [ ] Built and tested against the ugliest real record, not a tidy one
- [ ] Keyboard-navigable end to end
- [ ] Terminal output legible with colour disabled
- [ ] Nothing on screen that a user cannot act on

### 6.1 The test

Screenshot any surface and ask: **could this be a screenshot of a different product with the labels swapped?**

If yes, it is generic. Every screen should be unmistakably about settlement variance and nothing else — because the variance bars, the paise alignment, and the three semantic colours are all doing work that only this product needs.

---

## 7. Build order

| When | What |
|---|---|
| P1, day 3–5 | CLI run output, header, conservation line — as the matcher lands |
| P2, day 5–8 | Variance bar in CLI; `findings` output format |
| P4, day 11 | `close.md`, `exceptions.md`, README |
| P4, day 12 | **The Ledger — only if P0–P3 gates are green** |
| P4, day 13 | Anti-slop checklist; screenshot; fresh-container check |

**Design the CLI as you build, not at the end.** It is the surface you will look at a thousand times, and the one that will be on screen in the video whether or not S3 ever exists.
