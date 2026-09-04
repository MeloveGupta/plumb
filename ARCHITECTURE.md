# Architecture

## The one decision this repo is built around

**L1 (match) and L2 (verify) are pure functions. The LLM runs only in
L3, only on what L1 and L2 could not settle.**

Reconciliation tools compete on auto-match rate. That number hides two
failure modes Plumb exists to measure: a match that looks clean and is
wrong, and money that goes missing without raising an exception. Both
are deterministic questions — *does the recomputed obligation equal the
recorded one?* — and a deterministic layer answers them the same way
every time. `determinism_score` for L1 and L2 is exactly **1.000**
(`tests/plumb/match/test_determinism_harness.py`: five runs, hashed,
compared). An LLM cannot make that guarantee, so it does not touch that
path.

L3 takes L1's residual (records nothing matched, ambiguous candidate
sets) and L2's findings (a recomputed obligation disagreeing with a
recorded one). It investigates with seven read-only tools, ranks
hypotheses, and either proposes a resolution or escalates with *what
would resolve it*. It never re-matches and never re-runs a recompute —
that work is done and it is deterministic.

`ABLATION.md` is the test of whether L3 earns its place: `hybrid`
(L1+L2+L3) versus `rules_only` (L1+L2, residual all escalated), same
held-out batch, prediction written before the run.

## Why the deterministic layers are not AI — concretely

- **Money is `int` paise everywhere.** A single `float` in a money path
  silently breaks the 1.000 guarantee (floating-point addition is not
  associative). A lint test walks the AST of every module under `src/`
  and fails on a `float` type annotation outside `report/` and
  `plumb_eval/` (both read-only, downstream, incapable of feeding L1/L2).
- **Ordered structures, never `set`.** Python set iteration order
  varies with hash randomisation. Deterministic paths use `list` +
  index or `dict.fromkeys()`.
- **Confidence is basis points (`int`), not a float** — same treatment
  as `MatchGroup.confidence_bps`. The only `float` in the engine's
  own code is `confidence_bps / 10_000` at the SQLite `REAL`-column
  boundary in `store/writer.py`, a bare expression the rest of the
  engine never sees.
- **IDs are seed-derived and zero-padded** (`ord_00042`, `exc_00031`) —
  never `uuid4()`, never time-based. Two runs of the generator on one
  seed produce byte-identical files.

## The answer to "you graded your own homework"

The engine (`src/plumb/`) must never see ground truth. The generator
(`src/plumb_gen/`) writes it; the scorer (`src/plumb_eval/`) reads it.
This is enforced, not asserted:

- `tests/test_import_boundary.py` walks the AST of every module and
  fails on any `import plumb_gen` / `import plumb_eval` from the engine
  (and checks the generator and scorer's own allowed-import rows).
- `tests/test_import_boundary_dynamic.py` catches
  `importlib.import_module("plumb_gen")` and `__import__` with a
  literal string.
- `tests/test_layer_direction.py` enforces `ingest → match → verify →
  agent → report`, one direction, no backward edge.
- `tests/schema/test_truth_isolation.py` monkeypatches `sqlite3.connect`
  and fails if any `src/plumb/` code opens `truth.sqlite`.
- `truth/` is on a separate path from `dataset/`, gitignored, and is
  never a parameter to any engine entrypoint.

Every headline number carries a `manifest.json` (git sha, dirtiness,
seeds, config hashes, schema hash, model, sample label). A dirty tree
stamps the report `PROVISIONAL`.

## How matches and findings are scored

`plumb_eval` joins engine output to generator truth. The closure model
(what set of record keys a *correct* `match_group` contains), why the
scorer was corrected on 2 Sep, and the two questions that correction
raises are in **`docs/SCORING.md`**. Short version: the matcher groups
the whole payment chain (identity legs + order key + refund/dispute/
reversal satellites); the closure is the identity legs; `score_match`
strips the rest before comparing; a genuinely wrong match still fails
(demonstrated by `test_a_match_with_a_substituted_leg_still_scores_false_positive`).
Fabrication is checked against `record_index` — TRD §8.3's "absent from
the dataset" — and, for L3 evidence, three times over (the in-process
gate, the `resolution_evidence` foreign key, the scorer backstop).

## The L3 model client

The specs (`docs/PLUMB_TRD.md` §7) call for the Anthropic Messages API
with `claude-sonnet-5`. An Anthropic key was not available at build
time; a build.nvidia.com key was. L3 runs against
`nvidia/nemotron-3.5-lightning-30b-a3b` through an OpenAI-compatible
`chat/completions` endpoint.

**Only the model client changed.** `agent/model.py::NvidiaClient`
translates the loop's Anthropic-shaped messages and tool schemas to
OpenAI function-calling on the way out and parses `tool_calls` back.
The investigation loop, the eight-iteration cap, the token budget with
its reserve, the downgrade gate, the fabrication gate, the seven tools,
the structured `submit_resolution` output, the cassette record/replay
layer, and the determinism harness are all provider-neutral and
unchanged. `agent/model.py::AnthropicClient` is kept — swapping back is
a key, a config string, and a `_make_client` line.

No `seed` is passed even though NVIDIA NIM accepts one: forcing
bit-reproducibility would be engineering around the very finding L3's
`determinism_score` is there to report (non-negotiable 8).

## Dependencies, and why (TRD §1)

| dep | why |
|---|---|
| `pydantic` v2 | schema violations fail loudly at boundaries — the domain models, `AgentConfig`, `Resolution` |
| `typer` | the three CLIs (`plumb`, `plumb-gen`, `plumb-eval`) |
| `pyyaml` | generator config files |
| `polars` | report-layer aggregation only; domain logic stays plain Python |
| `anthropic` | the original / swap-back L3 client; imported lazily, never in CI |
| `openai` | the L3 client actually used (OpenAI-compatible endpoint); imported lazily, never in CI |
| `pytest`, `hypothesis` (dev) | the suite; property tests on the matcher |

No ORM, no migrations, no async, no web framework. The panel reads the
code; a short dependency list is part of that argument.
