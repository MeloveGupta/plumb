# Plumb — Low-Level Design

Seventh document. Sits between `PLUMB_TRD.md` (stack, contracts) and code.

**Scope discipline:** this specifies only the parts where a wrong design choice is expensive to reverse — algorithms with correctness or determinism implications, interface contracts between layers, and money arithmetic. Everything else is marked *"straightforward — use judgment."*

---

## 1. Module map

```
plumb/
  domain/        models.py  keys.py  money.py  states.py
  ingest/        adapters/{intent,razorpay,bank}.py  normalise.py  narration.py
  match/         engine.py  passes.py  subsets.py  tolerance.py
  verify/        unit.py  registry.py  checks/d01..d08.py  trace.py
  agent/         loop.py  tools.py  schema.py  gates.py  prompts/
  rules/         ratebook.py  basis.py
  report/        cli.py  markdown.py  jsonl.py  variance_bar.py
  store/         ddl.py  writer.py  queries.py
  errors.py  config.py
```

**Dependency rule — enforced by the same AST test as the import boundary:**

```
domain  ←  everything          (domain imports nothing internal)
store   ←  all layers
rules   ←  verify only
ingest → match → verify → agent → report        (strictly one direction)
```

`match` may not import `verify`. `verify` may not import `agent`. A backward edge means a layer boundary has leaked.

---

## 2. `domain/money.py` — get this exactly right

Every rupee in the system passes through these four functions. They are the highest-leverage forty lines in the codebase.

```python
Paise = int   # type alias; documentation, not enforcement
Bps   = int   # 0.1% == 10

def apply_bps(amount_paise: Paise, rate_bps: Bps) -> Paise:
    """Apply a rate. ROUND_HALF_UP on magnitude, applied exactly once.

    Sign is handled explicitly: floor division rounds toward negative
    infinity, which for a negative amount is round-half-DOWN. A refund
    or adjustment would then round the wrong way and disagree with the
    counterparty's arithmetic by one paisa.
    """
    sign = -1 if amount_paise < 0 else 1
    magnitude = abs(amount_paise)
    return sign * ((magnitude * rate_bps + 5_000) // 10_000)

def sum_paise(values: Iterable[Paise]) -> Paise:
    return sum(values)          # exact; no accumulation error by construction

def format_inr(amount_paise: Paise) -> str:
    """₹1,20,000.00 — Indian grouping (2,2,3), two decimals, always."""

def parse_rupee_string(s: str) -> Paise:
    """'1,200.50' -> 120050. Rejects >2 decimal places.
    Used only at the CSV ingest boundary."""
```

**Never round an intermediate.** If a computation is `taxable × commission_bps × gst_bps`, apply the first rate, round once, then apply the second to the rounded result — because that is what the counterparty's system did. Rounding at the end produces a different number and a false defect.

`parse_rupee_string` rejecting a third decimal place is deliberate: source data with sub-paise precision is a data-quality signal, not something to silently truncate. Route it to quarantine.

---

## 3. `ingest/` — normalisation

### 3.1 Adapter contract

```python
class SourceAdapter(Protocol):
    source_id: Literal["intent", "razorpay", "bank"]
    source_tz: str          # "Asia/Kolkata" | "UTC"
    amount_unit: Literal["rupee_string", "paise_int"]

    def read(self, path: Path) -> Iterator[RawRecord]: ...
    def normalise(self, raw: RawRecord) -> NormalResult: ...

@dataclass(frozen=True)
class NormalResult:
    record: CanonicalRecord | None      # None ⇒ quarantined
    transforms: list[Transform]         # every field touched
    quarantine_reason: str | None
```

Returning transforms alongside the record — rather than logging as a side effect — keeps `normalise` a pure function and makes the transform log testable in isolation.

### 3.2 `narration.py` — UTR extraction

The hardest ingest problem and the source of a whole class of real matching pain. A cascade, most-specific first:

```python
UTR_PATTERNS: list[tuple[str, re.Pattern, float]] = [
    ("utr_labelled",  r"\bUTR[:\s-]*([A-Z0-9]{12,22})\b",        1.00),
    ("neft_ref",      r"\bNEFT[/\s-]*([A-Z]{4}[A-Z0-9]{8,18})\b", 0.95),
    ("rtgs_ref",      r"\bRTGS[/\s-]*([A-Z0-9]{16,22})\b",        0.95),
    ("imps_ref",      r"\bIMPS[/\s-]*(\d{12})\b",                 0.90),
    ("bare_token",    r"\b([A-Z]{4}[A-Z0-9]{12,18})\b",           0.60),
]

def extract_utr(narration: str) -> tuple[str | None, float, str]:
    """Returns (utr, confidence, pattern_name).
    First match wins — patterns are ordered by specificity, so
    ordering carries meaning and must not be sorted or reordered.
    """
```

Design decisions:

- **Confidence below 0.60 → `utr = NULL`.** Do **not** quarantine. A bank row with an unparseable narration is a valid row with a missing field, and it should fall through to the tolerance pass or become an honest exception. Quarantining it would hide a real-world case the product exists to handle.
- The chosen `pattern_name` goes into `transform_log`. When the agent later investigates a bank mismatch, "we read the UTR out of the narration using the bare-token pattern at 0.60 confidence" is exactly the evidence it needs.
- Multiple distinct matches from the *same* pattern tier → `utr = NULL`, transform records `ambiguous_narration`. Guessing here manufactures a false match.

---

## 4. `match/` — the matcher

### 4.1 Engine

```python
class MatchEngine:
    def __init__(self, tolerance: ToleranceProfile, cfg: MatchConfig): ...

    def run(self, records: RecordSet) -> MatchResult:
        """P0 finds every exact-identifier chain, but does not commit a
        chain the moment it spans >=2 sides. An intent+razorpay chain
        (order/intent/payment/transfer/settlement_recon) already spans 2
        sides even when the bank leg hasn't joined (BankCredit.utr
        failed to parse) -- committing it immediately would permanently
        claim the settlement_recon (a record is claimed exactly once,
        ever -- ix_member_claimed_once) before P1/P2/P3 get a turn to
        attach the orphaned bank_credit, and those passes would then
        have nothing left to compare it against. So P0 returns three
        pools instead of one:

            groups    -- fully resolved (every applicable side present)
            remaining -- single-side leftovers (e.g. INTENT_ONLY)
            pending   -- a >=2-side chain missing its bank leg, held open

        P1 (exact composite), P2 (grouped subset-sum), P3 (tolerance
        band) each get a turn to attach an orphaned bank credit to a
        still-open pending group, threading `pending` and the orphan
        bank-credit pool forward pass to pass -- whatever one pass
        resolves or rules ambiguous is absent from what the next pass
        receives. Whatever is still pending after P3 finalises as a
        plain P0 match: the identity chain was always certain; a
        still-missing bank leg is a legitimate MISSING_BANK outcome for
        verify (P2.1) to classify, not a matching failure. A pending
        group caught in an ambiguous tie still finalises for its known
        members -- only the contested bank leg is reported separately,
        so the ambiguity never blocks the part that was never in
        question.
        """
        groups, remaining, pending = PassP0().run(records, records.all_keys())
        orphan_bank = [k for k in remaining if is_bank_credit(records.get(k))]
        remaining = [k for k in remaining if k not in orphan_bank]

        ambiguous, contested = [], set()
        for p in (PassP1(), PassP2(self.cfg), PassP3(self.tolerance)):
            found, pending, orphan_bank, amb, pass_contested = p.run(records, pending, orphan_bank)
            groups += found
            ambiguous += amb
            contested |= pass_contested

        groups += [finalise_as_p0(pg) for pg in pending]
        unmatched = remaining + orphan_bank + list(contested)
        return MatchResult(groups=groups, unmatched=unmatched, ambiguous=ambiguous)
```

**`remaining` (and every pool threaded between passes) is an ordered structure, not a set.** Iteration order over a Python `set` varies with insertion history and hash randomisation; a matcher that iterates a set is not deterministic. Use a `list` with an accompanying membership index, or `dict.fromkeys()`.

**A record is claimed by at most one final `MatchGroup`, by construction, not by convention.** P1/P2/P3 only ever compare a pending group's *summary* figures (its net target amount, its settlement date) against a separate pool of still-unclaimed bank credits — never against another pending group's own members — so nothing already inside an open pending group is ever independently re-offered as a candidate. Within one pass, every possible pairing across the whole pool is computed *before* anything is claimed, so a three-way tie can never be resolved by whichever pairing happens to be checked first — it surfaces as ambiguous instead, exactly like §4.2's subset ties below.

### 4.2 `subsets.py` — grouped matching, and the ambiguity rule

The only genuinely algorithmic component. Bounded subset-sum over candidates, and **the important part is what happens when more than one subset fits.**

```python
def find_subset(target_paise: Paise,
                candidates: list[CanonicalRecord],
                max_members: int = 5) -> SubsetResult:
    """Deterministic bounded subset-sum.

    1. Partition by natural group key (settlement_id, else utr).
    2. Fast path: if sum(partition) == target, the whole partition is
       the answer. This is the common real case and must be tried first.
    3. Otherwise enumerate combinations of size 2..max_members over
       candidates sorted by (amount_paise, record_key).
    4. Collect ALL subsets that sum to target — do not stop at the first.
    """
    matches = [c for k in range(2, max_members + 1)
                 for c in combinations(sorted_candidates, k)
                 if sum_paise(x.amount_paise for x in c) == target_paise]

    if len(matches) == 0:
        return SubsetResult(status=NO_MATCH)
    if len(matches) == 1:
        return SubsetResult(status=UNIQUE, members=matches[0])
    return SubsetResult(status=AMBIGUOUS, candidates=matches)
```

**The ambiguity rule is a core design decision, not an edge case.**

When two subsets both sum to the target — two orders of identical value on the same day, the T3 adversarial trap — the engine does **not** pick one. Picking would be a coin flip recorded as a match, and it is precisely how a competitor's product manufactures a silent error.

`AMBIGUOUS` becomes an exception routed to L3 with all candidate subsets attached as evidence. This is the cleanest example in the system of work that only an agent can do: choosing between equally-arithmetic-valid options requires evidence a rules engine has no way to weigh.

**Sort before enumerating.** `combinations` over an unsorted list yields subsets in input order; sorting by `(amount_paise, record_key)` makes the enumeration reproducible.

Complexity: C(n,5) over a partition. Partitions are small by construction (grouped by settlement). Assert `len(candidates) <= 40` and route larger partitions to L3 rather than enumerating — 658k combinations is a hang, not an answer.

### 4.3 `tolerance.py`

```python
@dataclass(frozen=True)
class ToleranceProfile:
    name: str
    amount_abs_paise: Paise
    amount_rel_bps: Bps
    date_window_days: int

    def band_paise(self, amount_paise: Paise) -> Paise:
        """Effective band = max(absolute, relative)."""
        return max(self.amount_abs_paise, apply_bps(amount_paise, self.amount_rel_bps))

    def within(self, expected_paise: Paise, actual_paise: Paise) -> bool:
        return abs(expected_paise - actual_paise) <= self.band_paise(expected_paise)
```

**`ToleranceProfile` is injected into both `PassP3` and check D02.** They must compute the band identically — D02's whole definition is "a shortfall that falls *inside* the band P3 used." Two implementations of `band_paise()` would make the flagship defect undetectable in exactly the cases that matter.

---

## 5. `verify/`

### 5.1 `unit.py` — SettlementUnit assembly

```python
class Completeness(StrEnum):
    FULL                = "full"                 # intent + razorpay + bank
    MISSING_BANK        = "missing_bank"
    MISSING_SETTLEMENT  = "missing_settlement"
    INTENT_ONLY         = "intent_only"

@dataclass(frozen=True)
class SettlementUnit:
    unit_id: str
    completeness: Completeness
    order: Order
    lines: list[OrderLine]
    intent: Intent
    payments: list[Payment]
    refunds: list[Refund]
    transfers: list[Transfer]
    reversals: list[Reversal]
    disputes: list[Dispute]
    recon_rows: list[SettlementRecon]
    bank_credit: BankCredit | None
    rate_card: SellerRateCard | None
    match_id: str | None
```

**Units are built for unmatched records too.** A unit at `INTENT_ONLY` still supports D01, D04 and D05 — you can verify that intended commission and tax were computed correctly without knowing whether the money arrived. Gating L2 on a successful match would discard most of its value.

### 5.2 Check registry

```python
class Check(Protocol):
    defect_id: str
    requires: frozenset[Completeness]

    def applies_to(self, unit: SettlementUnit) -> bool: ...
    def run(self, unit: SettlementUnit, ctx: CheckContext) -> Finding | None: ...

@dataclass(frozen=True)
class CheckContext:
    ratebook: RateBook
    tolerance: ToleranceProfile
    as_of: date
    config: VerifyConfig
```

`requires` lets the registry skip checks a unit cannot support, and — more usefully — lets the report state *"D08 was not evaluated on 41 units: no bank credit."* Silence about a check that never ran is the kind of gap a panelist finds.

Checks are pure: `(unit, ctx) -> Finding | None`. No I/O, no DB, no clock. Testable against a hand-built unit fixture.

### 5.3 D02 — the flagship, in detail

```python
class D02ShortSettlementInTolerance(Check):
    defect_id = "D02"
    requires = frozenset({Completeness.FULL, Completeness.MISSING_BANK})

    def run(self, unit, ctx) -> Finding | None:
        expected = compute_expected_net(unit, ctx)      # full recompute
        actual   = sum_paise(r.credit_paise - r.debit_paise for r in unit.recon_rows)
        delta    = expected - actual

        if delta <= 0:
            return None                                  # not short
        if not ctx.tolerance.within(expected, actual):
            return None          # outside the band — P3 never matched it;
                                 # it is an ordinary break, not a SILENT one

        return Finding(defect_id="D02", amount_at_risk_paise=delta,
                       on_matched_record=unit.match_id is not None,
                       trace=build_trace(...))
```

Read the second guard carefully. **D02 fires only when the shortfall is inside the tolerance band** — that is what makes it silent. A shortfall outside the band was already caught by the matcher and is not interesting. The narrow window between "zero" and "the band" is the entire product thesis, expressed in four lines.

### 5.4 `trace.py`

```python
class TraceBuilder:
    def step(self, label: str, formula: str,
             inputs: dict[str, int | str], output_paise: Paise) -> Self:
        """Chainable. Every step's output must be reachable from its
        declared inputs by the stated formula — asserted in tests by
        re-evaluating simple formulas from the inputs dict."""

    def conclude(self, text: str) -> RecomputeTrace: ...
```

The re-evaluation assertion is worth the effort: it means a trace can never describe arithmetic the code didn't actually do. Traces that lie are worse than no traces.

---

## 6. `rules/ratebook.py`

```python
class Basis(StrEnum):
    GROSS          = "gross"
    NET_OF_RETURNS = "net_of_returns"
    TAXABLE_VALUE  = "taxable_value"

@dataclass(frozen=True)
class RateRule:
    rule_id: str
    rate_bps: Bps
    basis: Basis                  # positional-hostile: keyword-only in __init__
    effective_from: date
    effective_to: date | None
    provision: str
    legacy_provision: str | None
    source_url: str

class RateBook:
    VERIFIED_ON: Final[date] = date(2026, 8, 28)

    def rate_for(self, kind: RateKind, as_of: date) -> RateRule:
        """As-of lookup. Raises NoApplicableRate — never silently
        falls back to 'current'."""
```

Two deliberate frictions:

- **`basis` is keyword-only.** `RateRule(10, Basis.GROSS, ...)` won't compile. Defects D04 and D05 *are* basis errors; making basis impossible to pass positionally means our own code cannot commit the bug it is designed to detect.
- **`rate_for` raises rather than defaulting.** A missing rule for a date is a real condition — it becomes a finding, not a silent application of today's rate to a June transaction.

---

## 7. `agent/`

### 7.1 Loop state

```python
@dataclass
class InvestigationState:
    exception_id: str
    iteration: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    messages: list[dict] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    stop_reason: StopReason | None = None

    def budget_remaining(self, cfg) -> int:
        return cfg.token_budget - (self.tokens_in + self.tokens_out)
```

### 7.2 Loop

```python
def investigate(exc: Exception_, state: InvestigationState, cfg) -> Resolution:
    while True:
        if state.iteration >= cfg.max_iterations:
            return forced_escalation(state, StopReason.ITERATION_CAP)
        if state.budget_remaining(cfg) < cfg.reserve_tokens:
            return forced_escalation(state, StopReason.BUDGET_EXHAUSTED)

        state.iteration += 1
        resp = call_model(state.messages, TOOLS, cfg)
        state.tokens_in  += resp.usage.input_tokens
        state.tokens_out += resp.usage.output_tokens

        if is_submit(resp):
            return finalise(parse_submit(resp), state)

        for call in tool_calls(resp):
            try:
                result = TOOLS[call.name](**call.args)
            except ToolError as e:
                result = ToolFailure(str(e))          # degrade, never abort
            log_agent_call(state, call, result)
            state.messages.append(tool_result_message(call, result))
```

**Budget is checked *before* the call, with a reserve.** Checking after means the final call can overshoot and the recorded spend exceeds the declared budget — a number you then have to explain.

`reserve_tokens` exists so there is always enough budget left to emit a proper escalation. An agent that runs out of money mid-thought and produces nothing is worse than one that stops early and says why.

### 7.3 `gates.py`

```python
def apply_downgrade_gate(claimed: Resolution, cfg) -> Resolution:
    if claimed.outcome != "AUTO_RESOLVED":
        return claimed
    if claimed.amount_at_risk_paise >= cfg.auto_resolve_threshold_paise:
        return claimed.downgrade("amount_above_threshold")
    if claimed.confidence < cfg.confidence_threshold:
        return claimed.downgrade("confidence_below_threshold")
    return claimed

def assert_evidence_resolves(res: Resolution, index: RecordIndex) -> None:
    """Raises FabricationError. Aborts the run. Not recoverable."""
    for ref in res.evidence_chain:
        if ref.record_key not in index:
            raise FabricationError(res.exception_id, ref.record_key)
```

`downgrade()` returns a *new* Resolution preserving `model_claimed_outcome` and setting `was_downgraded=1` with a reason. The original claim is never overwritten — the audit value is in the difference between what was claimed and what was granted.

---

## 8. `plumb_eval/` — silent-error attribution

The one metric whose computation is subtle enough to specify.

```python
def score_match(group: MatchGroup, truth: TruthStore,
                findings_by_unit: dict[str, list[Finding]],
                exceptions_by_record: dict[str, str]) -> ScoredMatch:
    members  = {m.record_key for m in group.members}
    expected = truth.counterpart_closure(group.anchor_key)

    if members == expected:
        return ScoredMatch(group.match_id, TRUE_POSITIVE, silent=0)

    # Wrong. Was anything raised about it?
    flagged = (bool(findings_by_unit.get(group.unit_id))
               or any(k in exceptions_by_record for k in members))

    return ScoredMatch(group.match_id, FALSE_POSITIVE, silent=0 if flagged else 1)
```

**`silent = wrong AND nothing was raised.** A wrong match that L2 flagged or that surfaced as an exception is a caught error — the system did its job. A wrong match that passed through clean is the failure the product exists to prevent, and it is the only one that counts toward the headline number.

Getting this attribution wrong in the flattering direction (counting flagged errors as silent) understates your own performance; getting it wrong in the other direction is worse and a panelist will check. Unit-test both branches explicitly.

---

## 9. Error hierarchy

```python
class PlumbError(Exception): ...

# Recoverable — handled, logged, run continues
class IngestError(PlumbError): ...          # → quarantine
class ToolError(PlumbError): ...            # → ToolFailure, agent continues
class BudgetExhausted(PlumbError): ...      # → forced escalation
class NoApplicableRate(PlumbError): ...     # → finding

# Fatal — abort, non-zero exit
class FabricationError(PlumbError): ...     # evidence ref doesn't resolve
class ConservationError(PlumbError): ...    # terminal states != records in
class SchemaViolation(PlumbError): ...
class TruthJoinError(PlumbError): ...       # scorer only
```

The split maps exactly to App Flow §7: **fail loudly at boundaries, degrade gracefully inside the agent loop.** Every fatal error is a case where continuing would produce a number we cannot stand behind.

---

## 10. `config.py`

```python
class PlumbConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tolerance: ToleranceProfile
    verify: VerifyConfig            # d06_hold_age_days, severity thresholds
    agent: AgentConfig              # max_iterations=8, token_budget,
                                    # reserve_tokens, auto_resolve_threshold_paise,
                                    # confidence_threshold, model, temperature=0.0
    ablation: Literal["rules_only", "llm_only", "hybrid"]

    def sha256(self) -> str:
        return hashlib.sha256(
            self.model_dump_json(exclude_none=False).encode()
        ).hexdigest()
```

`extra="forbid"` catches typo'd config keys at load rather than letting a misspelled `confidence_treshold` silently take a default and quietly change your results.

`frozen=True` means config cannot mutate mid-run — otherwise `config_sha256` in the manifest describes a state that no longer applies.

---

## 11. Left to judgment

Straightforward; no design decisions with lasting consequences:

`report/markdown.py` · `report/jsonl.py` · `store/writer.py` · CLI argument wiring · `variance_bar.py` rendering · adapter CSV/JSON parsing mechanics · test fixture builders · the generator's world-building sequence (beyond the seeding discipline in TRD §8.1).

---

## 12. Design decisions worth defending in the panel

Five things here that a panelist may ask about, each with a real answer:

1. **Ambiguous subsets are never resolved by the matcher.** Two valid arithmetic answers means the engine has no basis to choose. Routing to L3 is the honest move, and it produces the clearest example of work only an agent can do.
2. **`ToleranceProfile` is shared by P3 and D02 by injection.** The flagship defect is defined relative to the matcher's band; two implementations would silently decouple them.
3. **`basis` is keyword-only.** Our own code cannot commit the error we detect.
4. **Budget is checked before the call, with a reserve.** So a run never overspends its declared budget and always has room to escalate properly.
5. **`silent` requires wrong *and* unflagged.** A caught error is not a silent error, and conflating them would inflate the headline number in our favour.
