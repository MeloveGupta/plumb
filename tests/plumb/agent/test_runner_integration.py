"""P3 step 10 -- L3 end to end against a real ingest -> match -> verify
run (config_a, the tune config -- this is wiring verification, not a
headline metric). Plus the rules_only arm, the fabrication abort, the
batch-budget cutoff, and ambiguous-subset routing.

The model is a trivial in-process client that submits immediately, so
the test exercises the queue -> loop -> gates wiring, not model
behaviour.
"""

from datetime import date
from pathlib import Path

import pytest

from _agent_fixtures import ingest_result as make_ingest

from plumb.agent.config import AgentConfig
from plumb.agent.evidence import EvidenceStore, RecordIndex
from plumb.agent.loop import _initial_user_message
from plumb.agent.model import ModelResponse, ToolCall, Usage
from plumb.agent.prompts import load_prompts
from plumb.agent.queue import build_exception_queue
from plumb.agent.runner import run_investigation
from plumb.agent.schema import StopReason
from plumb.agent.tools import Toolbox
from plumb.domain.keys import IdSequence
from plumb.domain.tolerance import DEFAULT_V1
from plumb.errors import FabricationError
from plumb.ingest.pipeline import run_ingest
from plumb.match.engine import AmbiguousMatch, MatchEngine, MatchResult, RecordSet
from plumb.rules.ratebook import default_ratebook
from plumb.store.ddl import open_run_db
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

from plumb_gen.config_loader import load_generator_config
from plumb_gen.io import write_sources
from plumb_gen.world import build_world

_CHECKS = [
    D01CommissionRateDrift(), D02ShortSettlementInTolerance(), D03RefundNettingError(),
    D04TcsBasisError(), D05TdsRateOrBasisError(), D06OrphanedHold(),
    D07ReversalWithoutRefund(), D08GstOnFeeRateError(),
]
_PROMPTS = load_prompts()
_CFG_AS_OF = date(2026, 8, 26)


class _SubmitsImmediately:
    """Returns a one-turn submit_resolution for every call. `outcome`
    and `confidence_bps` are fixed; `evidence_key` is cited on every
    resolution (must be a real key for the fabrication gate to pass)."""

    def __init__(self, evidence_key: str, *, outcome="PROPOSED", confidence_bps=8_000, usage=(10, 10)):
        self._key = evidence_key
        self._outcome = outcome
        self._confidence_bps = confidence_bps
        self._usage = usage
        self.call_count = 0

    def call(self, system, messages, tools, cfg) -> ModelResponse:
        self.call_count += 1
        args = dict(
            outcome=self._outcome,
            confidence_bps=self._confidence_bps,
            hypotheses=[
                {"rank": 1, "statement": "recorded figure is correct", "supports": []},
                {"rank": 2, "statement": "the recorded figure is itself wrong", "supports": []},
            ],
            chosen_hypothesis_index=0,
            evidence_chain=[{"record_key": self._key, "role": "cited"}],
            what_was_tried="submitted without further tool calls",
            what_would_resolve_it="a human decision" if self._outcome == "ESCALATED_UNRESOLVED" else None,
            trivially_determined=False,
        )
        return ModelResponse(
            stop_reason="tool_use",
            tool_calls=[ToolCall("s", "submit_resolution", args)],
            usage=Usage(*self._usage),
        )


def _pipeline(tmp_path, seed=42):
    config = load_generator_config(
        Path("configs/config_a.yaml"), seed=seed, batch_id="l3_integ", batch_as_of=date(2026, 8, 20), tier="T2",
    )
    world = build_world(config)
    write_sources(world, tmp_path)
    conn = open_run_db(":memory:")
    ids = IdSequence()
    ingested = run_ingest(
        tmp_path / "sellers.csv", tmp_path / "intent.csv", tmp_path / "razorpay.json", tmp_path / "bank.csv",
        conn, ids,
    )
    records = RecordSet.from_ingest(ingested)
    match_result = MatchEngine(tolerance=DEFAULT_V1).run(records)
    match_ids = {i: ids.next("mtch") for i in range(len(match_result.groups))}
    units = build_units(ingested, match_result, match_ids, ids)
    ctx = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=_CFG_AS_OF, config=VerifyConfig())
    registry_result = run_checks(units, _CHECKS, ctx)

    all_findings = [f for fs in registry_result.findings_by_unit.values() for f in fs]
    findings_with_ids = [(f"fnd_{i:05d}", f) for i, f in enumerate(all_findings, start=1)]
    queue = build_exception_queue(match_result, records, findings_with_ids, ids)

    return ingested, records, match_result, queue


def _first_intent_key(ingested) -> str:
    for record in ingested["intent"]["records"]:
        if type(record).__name__ == "Intent":
            return record.intent_id
    raise AssertionError("no intent in the batch")


def test_hybrid_run_resolves_every_queued_exception(tmp_path):
    ingested, _records, match_result, queue = _pipeline(tmp_path)
    assert len(queue) > 0

    toolbox = Toolbox(EvidenceStore.from_ingest(ingested), IdSequence())
    index = RecordIndex.from_ingest(ingested)
    client = _SubmitsImmediately(_first_intent_key(ingested), outcome="AUTO_RESOLVED", confidence_bps=8_000)

    resolutions = run_investigation(queue, toolbox, index, client, AgentConfig(), _PROMPTS)

    assert len(resolutions) == len(queue)
    assert client.call_count == len(queue)
    # every AUTO_RESOLVED claim with confidence 8000 (< 9000) is downgraded to PROPOSED
    assert all(r.outcome == "PROPOSED" for r in resolutions)
    assert all(r.was_downgraded and r.model_claimed_outcome == "AUTO_RESOLVED" for r in resolutions)
    # queue_rank order preserved
    assert [r.exception_id for r in resolutions] == [e.exception_id for e in queue]


def test_rules_only_arm_escalates_everything(tmp_path):
    ingested, _records, _match_result, queue = _pipeline(tmp_path)
    toolbox = Toolbox(EvidenceStore.from_ingest(ingested), IdSequence())
    index = RecordIndex.from_ingest(ingested)
    client = _SubmitsImmediately(_first_intent_key(ingested))

    resolutions = run_investigation(
        queue, toolbox, index, client, AgentConfig(), _PROMPTS, ablation="rules_only"
    )
    assert len(resolutions) == len(queue)
    assert client.call_count == 0  # L3 bypassed entirely
    assert all(r.outcome == "ESCALATED_UNRESOLVED" for r in resolutions)
    assert all(r.stop_reason == StopReason.RULES_ONLY for r in resolutions)
    assert all(r.what_was_tried == "rules-only configuration" for r in resolutions)


def test_a_fabricated_evidence_key_aborts_the_run(tmp_path):
    ingested, _records, _match_result, queue = _pipeline(tmp_path)
    toolbox = Toolbox(EvidenceStore.from_ingest(ingested), IdSequence())
    index = RecordIndex.from_ingest(ingested)
    client = _SubmitsImmediately("pay_99999")  # not a real record

    with pytest.raises(FabricationError, match="pay_99999"):
        run_investigation(queue, toolbox, index, client, AgentConfig(), _PROMPTS)


def test_batch_budget_escalates_the_cheap_tail(tmp_path):
    ingested, _records, _match_result, queue = _pipeline(tmp_path)
    assert len(queue) >= 3
    toolbox = Toolbox(EvidenceStore.from_ingest(ingested), IdSequence())
    index = RecordIndex.from_ingest(ingested)
    client = _SubmitsImmediately(_first_intent_key(ingested), usage=(1_000, 0))

    # budget covers ~2 exceptions (1_000 tokens each) before the cutoff trips
    resolutions = run_investigation(
        queue, toolbox, index, client, AgentConfig(), _PROMPTS, batch_token_budget=1_500
    )
    assert len(resolutions) == len(queue)
    assert client.call_count == 2  # exc 1 and 2 investigated; the rest cut off
    tail = resolutions[2:]
    assert all(r.stop_reason == StopReason.BUDGET_EXHAUSTED and r.iterations_used == 0 for r in tail)
    assert all(r.outcome == "ESCALATED_UNRESOLVED" for r in tail)


def test_ambiguous_subset_routes_with_its_candidates_in_the_prompt():
    # a hand-built ambiguous match -- config_a doesn't reliably produce one
    match = AmbiguousMatch(
        pass_="P1",
        reason="settlement stlbatch_x: 2 bank credit candidates",
        candidates=(("int_00001", "pay_00001", "bank_00003"), ("int_00001", "pay_00001", "bank_00004")),
    )
    batch = make_ingest()  # empty batch is fine -- we only need RecordIndex membership for the cited key
    records = RecordSet.from_ingest(batch)
    ids = IdSequence()
    queue = build_exception_queue(MatchResult(groups=(), unmatched=(), ambiguous=(match,)), records, [], ids)
    assert len(queue) == 1
    exc = queue[0]
    assert exc.record_key == "bank_00003"
    assert exc.candidates == match.candidates

    prompt_text = _initial_user_message(exc)["content"]
    assert "candidate 0: int_00001, pay_00001, bank_00003" in prompt_text
    assert "candidate 1: int_00001, pay_00001, bank_00004" in prompt_text
