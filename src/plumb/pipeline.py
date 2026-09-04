"""`plumb run` -- the L0->L4 orchestrator.

Lifts the chain that until now lived only in
tests/plumb/agent/test_runner_integration.py::_pipeline and
tests/plumb_eval/test_gate_p2_real_batch.py: ingest -> match -> verify
-> exception queue -> L3 -> write run.sqlite + manifest.

Does NOT generate the batch -- `plumb` may never import `plumb_gen`
(TRD §3.1). The caller runs `plumb-gen` first; this reads
`<data_dir>/dataset/{sellers.csv,intent.csv,razorpay.json,bank.csv}`.

The model client is chosen by `model_mode`: "replay" (default, and what
CI uses -- CassetteClient over fixtures/llm/), "record" (RecordingClient
wrapping the live API), "live" (AnthropicClient, no recording). Tests
inject a ScriptedClient via `client`. `rules_only` never constructs one.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import metadata
from pathlib import Path

from plumb.agent.config import AgentConfig
from plumb.agent.evidence import EvidenceStore, RecordIndex
from plumb.agent.model import TEMPERATURE, ModelClient
from plumb.agent.prompts import load_prompts
from plumb.agent.queue import build_exception_queue
from plumb.agent.runner import run_investigation_traced
from plumb.agent.tools import Toolbox
from plumb.domain.keys import IdSequence
from plumb.domain.tolerance import DEFAULT_V1, ToleranceProfile
from plumb.gitinfo import head_sha, is_dirty
from plumb.ingest.pipeline import run_ingest
from plumb.manifest_writer import write_manifest
from plumb.match.engine import MatchEngine, RecordSet
from plumb.rules.ratebook import RateBook, default_ratebook
from plumb.report.pack import write_report_pack
from plumb.run_writer import write_full_run
from plumb.store.ddl import SCHEMA_PATH, open_run_db
from plumb.verify.checks.d01 import D01CommissionRateDrift
from plumb.verify.checks.d02 import D02ShortSettlementInTolerance
from plumb.verify.checks.d03 import D03RefundNettingError
from plumb.verify.checks.d04 import D04TcsBasisError
from plumb.verify.checks.d05 import D05TdsRateOrBasisError
from plumb.verify.checks.d06 import D06OrphanedHold
from plumb.verify.checks.d07 import D07ReversalWithoutRefund
from plumb.verify.checks.d08 import D08GstOnFeeRateError
from plumb.verify.registry import CheckContext, run_checks
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import build_units

_CHECKS = [
    D01CommissionRateDrift(),
    D02ShortSettlementInTolerance(),
    D03RefundNettingError(),
    D04TcsBasisError(),
    D05TdsRateOrBasisError(),
    D06OrphanedHold(),
    D07ReversalWithoutRefund(),
    D08GstOnFeeRateError(),
]


@dataclass(frozen=True)
class RunOutcome:
    run_dir: Path
    run_id: str
    ablation: str
    exception_count: int
    resolution_outcomes: dict[str, int]  # outcome -> count


def _plumb_version() -> str:
    try:
        return metadata.version("plumb")
    except metadata.PackageNotFoundError:
        return "0.1.0"


def _make_client(model_mode: str) -> ModelClient:
    from plumb.agent.model import CassetteClient, NvidiaClient, RecordingClient

    cassette_dir = Path("fixtures/llm")
    if model_mode == "replay":
        return CassetteClient(cassette_dir)
    if model_mode == "record":
        return RecordingClient(NvidiaClient(), cassette_dir)
    if model_mode == "live":
        return NvidiaClient()
    raise ValueError(f"unknown model_mode {model_mode!r} -- one of replay, record, live")


def execute_run(
    *,
    data_dir: Path,
    out_dir: Path,
    ablation: str,
    sample_label: str,
    generator_seed: int,
    generator_config: Path,
    as_of: date,
    tolerance: ToleranceProfile = DEFAULT_V1,
    agent_config: AgentConfig | None = None,
    model_mode: str = "replay",
    client: ModelClient | None = None,
    batch_token_budget: int | None = None,
    now: datetime | None = None,
    run_id_suffix: str = "",
) -> RunOutcome:
    if ablation not in ("rules_only", "hybrid"):
        raise ValueError(f"ablation must be rules_only or hybrid, got {ablation!r}")
    if sample_label not in ("IN_SAMPLE", "HELD_OUT"):
        raise ValueError(f"sample_label must be IN_SAMPLE or HELD_OUT, got {sample_label!r}")

    cfg = agent_config or AgentConfig()
    started = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha = head_sha()
    run_id = f"{started}-{sha[:7]}" + (f"-{run_id_suffix}" if run_id_suffix else "")
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    dataset = data_dir / "dataset"
    conn = open_run_db(run_dir / "run.sqlite")
    ids = IdSequence()

    ingested = run_ingest(
        dataset / "sellers.csv", dataset / "intent.csv", dataset / "razorpay.json", dataset / "bank.csv",
        conn, ids,
    )
    records = RecordSet.from_ingest(ingested)
    match_result = MatchEngine(tolerance=tolerance).run(records)
    match_ids = {i: ids.next("mtch") for i in range(len(match_result.groups))}
    units = build_units(ingested, match_result, match_ids, ids)

    ctx = CheckContext(ratebook=default_ratebook(), tolerance=tolerance, as_of=as_of, config=VerifyConfig())
    registry_result = run_checks(units, _CHECKS, ctx)

    findings_with_ids: list[tuple[str, object]] = []
    for unit_id in sorted(registry_result.findings_by_unit):
        for finding in registry_result.findings_by_unit[unit_id]:
            findings_with_ids.append((ids.next("fnd"), finding))

    queue = build_exception_queue(match_result, records, findings_with_ids, ids)

    if ablation == "rules_only":
        traced = run_investigation_traced(
            queue, None, RecordIndex.from_ingest(ingested), None, cfg, load_prompts(),
            ablation="rules_only",
        )
    else:
        model_client = client or _make_client(model_mode)
        toolbox = Toolbox(EvidenceStore.from_ingest(ingested), ids)
        traced = run_investigation_traced(
            queue, toolbox, RecordIndex.from_ingest(ingested), model_client, cfg, load_prompts(),
            ablation="hybrid", batch_token_budget=batch_token_budget,
        )
    resolved = [(exc, resolution, state) for exc, (resolution, state) in zip(queue, traced, strict=True)]

    finished = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    generator_config_sha256 = hashlib.sha256(generator_config.read_bytes()).hexdigest()
    engine_config_sha256 = cfg.sha256()
    schema_sha256 = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    prompts = load_prompts()
    llm_model = cfg.model if ablation == "hybrid" else None
    llm_temperature = TEMPERATURE if ablation == "hybrid" else None

    write_full_run(
        conn,
        ids,
        run_id=run_id,
        plumb_version=_plumb_version(),
        git_sha=sha,
        git_dirty=is_dirty(),
        batch_id=data_dir.name,
        generator_seed=generator_seed,
        generator_config_sha256=generator_config_sha256,
        engine_config_sha256=engine_config_sha256,
        schema_sha256=schema_sha256,
        tolerance_profile=tolerance.name,
        rules_module_version=RateBook.VERIFIED_ON.isoformat(),
        ablation_config=ablation,
        sample_label=sample_label,
        llm_model=llm_model,
        llm_temperature=llm_temperature,
        started_at_utc=started,
        finished_at_utc=finished,
        config_snapshot={
            "agent": cfg.model_dump(),
            "tolerance": {
                "name": tolerance.name,
                "amount_abs_paise": tolerance.amount_abs_paise,
                "amount_rel_bps": tolerance.amount_rel_bps,
                "date_window_days": tolerance.date_window_days,
            },
            "ablation": ablation,
            "as_of": as_of.isoformat(),
        },
        ingest_result=ingested,
        match_result=match_result,
        match_ids=match_ids,
        units=units,
        findings_with_ids=findings_with_ids,
        resolved=resolved,
    )
    conn.close()

    write_manifest(
        run_dir,
        run_id=run_id,
        git_sha=sha,
        git_dirty=is_dirty(),
        generator_seed=generator_seed,
        generator_config=generator_config.name,
        generator_config_sha256=generator_config_sha256,
        engine_config_sha256=engine_config_sha256,
        schema_sha256=schema_sha256,
        prompt_sha256=prompts.sha256,
        tolerance_profile=tolerance.name,
        rules_module_version=RateBook.VERIFIED_ON.isoformat(),
        ablation_config=ablation,
        sample_label=sample_label,
        llm_model=llm_model,
        llm_temperature=llm_temperature,
    )

    write_report_pack(run_dir)  # close.md, exceptions.md, *.jsonl

    outcomes: dict[str, int] = {}
    for _exc, resolution, _state in resolved:
        outcomes[resolution.outcome] = outcomes.get(resolution.outcome, 0) + 1

    return RunOutcome(
        run_dir=run_dir,
        run_id=run_id,
        ablation=ablation,
        exception_count=len(queue),
        resolution_outcomes=outcomes,
    )


def _resolution_hashes(run_sqlite: Path) -> dict[str, str]:
    """exception_id -> a hash of the resolution's *semantic* content
    (never the generated hypothesis ids, which differ per run). This is
    what the L3 determinism score compares across runs."""
    import sqlite3

    conn = sqlite3.connect(run_sqlite)
    hyps: dict[str, list] = {}
    for exc_id, rank, statement, supports_json in conn.execute(
        "SELECT exception_id, rank, statement, supports_json FROM hypothesis ORDER BY exception_id, rank"
    ):
        hyps.setdefault(exc_id, []).append({"rank": rank, "statement": statement, "supports": supports_json})

    out: dict[str, str] = {}
    for row in conn.execute(
        "SELECT exception_id, outcome, confidence, iterations_used, stop_reason, what_was_tried, "
        "what_would_resolve_it, was_downgraded, downgrade_reason FROM resolution ORDER BY exception_id"
    ):
        exc_id = row[0]
        payload = json.dumps(
            {
                "outcome": row[1], "confidence": row[2], "iterations_used": row[3], "stop_reason": row[4],
                "what_was_tried": row[5], "what_would_resolve_it": row[6],
                "was_downgraded": row[7], "downgrade_reason": row[8], "hypotheses": hyps.get(exc_id, []),
            },
            sort_keys=True,
        )
        out[exc_id] = hashlib.sha256(payload.encode()).hexdigest()
    conn.close()
    return out


def run_repeated(*, repeat: int, **kwargs) -> dict:
    """Run the L3 pipeline `repeat` times against the same batch and
    score L3 determinism (PRD §7.9: identical resolutions across all
    runs / total). Expect < 1.000 -- the Anthropic API has no seed;
    that is a finding, not a defect (non-negotiable 8). Writes
    determinism.json into the first run dir and returns it."""
    if repeat < 2:
        raise ValueError("run_repeated needs repeat >= 2")

    outcomes = [execute_run(run_id_suffix=f"r{i + 1}", **kwargs) for i in range(repeat)]

    observations: list[tuple[int, str, str]] = []
    for run_index, outcome in enumerate(outcomes):
        for exc_id, h in _resolution_hashes(outcome.run_dir / "run.sqlite").items():
            observations.append((run_index, exc_id, h))

    total = outcomes[0].exception_count
    hashes_by_exc: dict[str, set[str]] = {}
    for _run_index, exc_id, h in observations:
        hashes_by_exc.setdefault(exc_id, set()).add(h)
    identical = sum(1 for hs in hashes_by_exc.values() if len(hs) == 1)
    score = identical / total if total else None

    result = {
        "ablation": outcomes[0].ablation,
        "runs": repeat,
        "exceptions_total": total,
        "exceptions_identical_across_all_runs": identical,
        "determinism_score": score,
        "run_ids": [o.run_id for o in outcomes],
        "note": (
            "L3 determinism. The Anthropic API has no seed, so < 1.000 is expected and is a "
            "finding, not a defect (non-negotiable 8). L1/L2 determinism is 1.000 -- see "
            "tests/plumb/match/test_determinism_harness.py."
        ),
    }
    (outcomes[0].run_dir / "determinism.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result
