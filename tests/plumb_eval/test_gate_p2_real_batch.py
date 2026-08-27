"""PRD §7.5/§12 GATE P2 -- "defect recall >= 80% on T2 (held-out)."

config_b.yaml is HELD_OUT (PRD §8.4: "every headline number in the
submission is measured against this config, frozen after the engine is
frozen"); config_a.yaml is tune-only. This measures the real thing: a
full ingest -> match -> verify run over real config_b/T2 batches,
scored by the actual plumb_eval.scoring.score_defects function (order_key
+ defect_class matching, the real PRD §7.5 rule) -- not a hand-rolled
amount-based comparison.

The adapter below transcribes in-memory World/SettlementUnit/Finding
objects directly into TruthStore/RunData -- both are plain dataclasses,
no SQL connection required to construct them (confirmed: `store/writer.py`
has no write_settlement_unit/write_finding yet, so the full DB-round-trip
`plumb_eval.scorer.score_run` path isn't available; this is the
legitimate, currently-viable alternative, not a workaround).
"""

from datetime import date
from pathlib import Path

import pytest

from plumb.domain.keys import IdSequence
from plumb.domain.tolerance import DEFAULT_V1
from plumb.ingest.pipeline import run_ingest
from plumb.match.engine import MatchEngine, RecordSet
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

from plumb_eval.metrics import _ratio
from plumb_eval.run_reader import Finding as EvalFinding
from plumb_eval.run_reader import RunData
from plumb_eval.run_reader import SettlementUnit as EvalSettlementUnit
from plumb_eval.scoring import score_defects
from plumb_eval.truth_store import TruthStore

from plumb_gen.config_loader import load_generator_config
from plumb_gen.io import write_sources
from plumb_gen.world import build_world

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


def _build_truth_store(world) -> TruthStore:
    closure_by_key: dict[str, frozenset[str]] = {}
    order_key_by_member: dict[str, str] = {}
    obligation_by_key: dict[str, dict[str, int]] = {}
    resolvable_by_key: dict[str, bool] = {}
    defects_by_key: dict[str, list[dict]] = {}

    for record in world.truth_records:
        closure = frozenset(record.true_counterparts)
        closure_by_key[record.record_key] = closure
        order_key_by_member[record.record_key] = record.record_key
        for leg in record.true_counterparts:
            closure_by_key[leg] = closure
            order_key_by_member[leg] = record.record_key
        obligation_by_key[record.record_key] = dict(record.true_obligation)
        resolvable_by_key[record.record_key] = record.resolvable_from_available_data

    for d in world.injected_defects:
        defects_by_key.setdefault(d.record_key, []).append(
            {
                "instance_id": d.instance_id,
                "record_key": d.record_key,
                "defect_class": d.defect_class,
                "amount_at_risk_paise": d.amount_at_risk_paise,
                "within_tolerance": d.within_tolerance,
                "params": dict(d.params),
            }
        )

    return TruthStore(closure_by_key, order_key_by_member, obligation_by_key, resolvable_by_key, defects_by_key)


def _build_run_data(units, findings_by_unit) -> RunData:
    settlement_units = [
        EvalSettlementUnit(u.unit_id, u.order.order_id, u.match_id, u.order.seller_id, "") for u in units
    ]
    findings: list[EvalFinding] = []
    counter = 0
    for u in units:
        for f in findings_by_unit[u.unit_id]:
            counter += 1
            findings.append(
                EvalFinding(
                    finding_id=f"find_{counter:05d}",
                    unit_id=f.unit_id,
                    defect_id=f.defect_id,
                    severity=f.severity.value,
                    amount_at_risk_paise=f.amount_at_risk_paise,
                    on_matched_record=f.on_matched_record,
                    conclusion=f.conclusion,
                    evidence_keys=[e.record_key for e in f.evidence],
                )
            )
    return RunData(
        run_id="gate_p2", started_at_utc="", finished_at_utc=None,
        match_groups=[], settlement_units=settlement_units, findings=findings,
        exceptions=[], resolutions=[], agent_call_tokens_total=0, agent_call_count=0,
    )


@pytest.mark.parametrize("seed", [1, 2, 3, 7, 42])
def test_defect_recall_at_least_80_percent_on_held_out_t2(tmp_path, seed):
    config = load_generator_config(
        Path("configs/config_b.yaml"), seed=seed, batch_id="gate_p2", batch_as_of=date(2026, 8, 20), tier="T2",
    )
    world = build_world(config)

    write_sources(world, tmp_path)
    conn = open_run_db(":memory:")
    ids = IdSequence()
    ingest_result = run_ingest(
        tmp_path / "sellers.csv", tmp_path / "intent.csv", tmp_path / "razorpay.json", tmp_path / "bank.csv",
        conn, ids,
    )

    records = RecordSet.from_ingest(ingest_result)
    match_result = MatchEngine(tolerance=DEFAULT_V1).run(records)
    match_ids = {i: ids.next("mtch") for i in range(len(match_result.groups))}

    units = build_units(ingest_result, match_result, match_ids, ids)
    ctx = CheckContext(ratebook=default_ratebook(), tolerance=DEFAULT_V1, as_of=date(2026, 8, 26), config=VerifyConfig())
    registry_result = run_checks(units, _CHECKS, ctx)

    truth = _build_truth_store(world)
    run = _build_run_data(units, registry_result.findings_by_unit)

    scored_defects, true_positive_finding_ids = score_defects(run, truth)

    defects_injected = len(truth.all_defects())
    defects_detected = sum(1 for sd in scored_defects if sd.was_detected)
    defect_recall = _ratio(defects_detected, defects_injected)

    assert defect_recall is not None
    assert defect_recall >= 0.80, (
        f"defect_recall={defect_recall} on config_b/T2 seed={seed} "
        f"({defects_detected}/{defects_injected}) -- below GATE P2's 80% threshold"
    )

    # Precision at 100% isn't the gate's own criterion, but a drop here
    # would mean a check is producing false positives against real
    # held-out data -- worth failing loudly, not just noting.
    total_flags = len(run.findings)
    defect_precision = _ratio(len(true_positive_finding_ids), total_flags)
    assert defect_precision == 1.0, f"defect_precision={defect_precision} on seed={seed} -- a check is false-alarming on held-out data"
