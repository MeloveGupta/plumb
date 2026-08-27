"""PRD §7/§12 GATE P2 -- "zero false alarms on T4." A real T4-tier batch
has zero injected defects by construction (plumb_gen/tiers.py forces
`defects={}`), so every check firing on one is a false positive by
definition -- this measures that criterion directly against a real
generated batch, not a hand-built approximation of it.
"""

from datetime import date

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
from plumb.verify.registry import CheckContext, run_checks
from plumb.verify.trace import VerifyConfig
from plumb.verify.unit import build_units

from plumb_gen.config import GeneratorConfig
from plumb_gen.io import write_sources
from plumb_gen.tiers import apply_tier
from plumb_gen.world import build_world

_CHECKS = [
    D01CommissionRateDrift(),
    D02ShortSettlementInTolerance(),
    D03RefundNettingError(),
    D04TcsBasisError(),
    D05TdsRateOrBasisError(),
    D06OrphanedHold(),
    D07ReversalWithoutRefund(),
]


@pytest.mark.parametrize("seed", [1, 2, 3, 7, 42])
def test_zero_findings_on_a_real_t4_batch(tmp_path, seed):
    config = apply_tier(GeneratorConfig(seed=seed, batch_id="t4_null_set"), "T4")
    world = build_world(config)
    assert world.injected_defects == []  # T4 is a null set by construction -- confirm before asserting on checks

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
    result = run_checks(units, _CHECKS, ctx)

    total_findings = sum(len(findings) for findings in result.findings_by_unit.values())
    assert total_findings == 0, {
        unit_id: findings for unit_id, findings in result.findings_by_unit.items() if findings
    }
