"""PRD §7 formulas against hand-computed tiny fixtures -- every expected
value below is worked out on paper in the fixture's own comments, never
derived from compute_metrics itself.
"""

import pytest

from plumb_eval.metrics import compute_metrics
from plumb_eval.run_reader import RunData
from plumb_eval.scoring import score_abstentions, score_all_matches, score_defects
from plumb_eval.truth_store import TruthStore

from _fixtures import (
    insert_agent_call,
    insert_exception_unmatched,
    insert_finding,
    insert_injected_defect,
    insert_leg,
    insert_match,
    insert_order,
    insert_resolution,
    insert_run_row,
    insert_settlement_unit,
    insert_truth_record,
    make_run_db,
    make_truth_db,
)


def _metric_dict(metrics):
    return {m.name: (m.value, m.unit) for m in metrics}


@pytest.fixture
def rich_scenario(tmp_path):
    """Six orders exercising every metric family with a nonzero
    denominator. Hand-computed expectations are in the test functions
    below, not here -- this fixture only builds the topology.

    ord_1: complete, correct match (TRUE_POSITIVE). Clean, no finding.
    ord_2: incomplete/wrong match (FALSE_POSITIVE), caught by a finding
           that also correctly detects+classifies its injected D02.
    ord_3: incomplete/wrong match (FALSE_POSITIVE), nothing raised ->
           silent. Its injected D05 goes undetected.
    ord_4: complete, correct match (TRUE_POSITIVE). Clean, but a finding
           was raised anyway -> false alarm.
    ord_5: never matched at all. Injected D06 undetected. Escalated and
           genuinely unresolvable -> correct abstention.
    ord_6: never matched, no injected defect, escalated anyway even
           though resolvable -> over-abstention.
    """
    run_conn = make_run_db(tmp_path / "run.sqlite")
    truth_conn = make_truth_db(tmp_path / "truth.sqlite")
    insert_run_row(run_conn, started_at_utc="2026-01-01T00:00:00Z", finished_at_utc="2026-01-01T00:00:10Z")

    # ord_1 -- complete correct match, clean.
    insert_order(run_conn, "ord_00001")
    insert_leg(run_conn, "pay_00001")
    insert_leg(run_conn, "txfr_00001")
    insert_match(run_conn, "mtch_00001", ["pay_00001", "txfr_00001"])
    insert_settlement_unit(run_conn, "unit_00001", "ord_00001", match_id="mtch_00001")
    insert_truth_record(truth_conn, "ord_00001", ["pay_00001", "txfr_00001"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})

    # ord_2 -- incomplete match (missing txfr_2), caught + correctly-classified D02.
    insert_order(run_conn, "ord_00002")
    insert_leg(run_conn, "pay_00002")
    insert_leg(run_conn, "txfr_00002")
    insert_match(run_conn, "mtch_00002", ["pay_00002"])
    insert_settlement_unit(run_conn, "unit_00002", "ord_00002", match_id="mtch_00002")
    insert_finding(run_conn, "fnd_00001", "unit_00002", "D02", 500, ["pay_00002"])
    insert_truth_record(truth_conn, "ord_00002", ["pay_00002", "txfr_00002"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})
    insert_injected_defect(truth_conn, "inst_00001", "ord_00002", "D02", 500)

    # ord_3 -- incomplete match (missing txfr_3), nothing raised, D05 undetected.
    insert_order(run_conn, "ord_00003")
    insert_leg(run_conn, "pay_00003")
    insert_leg(run_conn, "txfr_00003")
    insert_match(run_conn, "mtch_00003", ["pay_00003"])
    insert_settlement_unit(run_conn, "unit_00003", "ord_00003", match_id="mtch_00003")
    insert_truth_record(truth_conn, "ord_00003", ["pay_00003", "txfr_00003"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})
    insert_injected_defect(truth_conn, "inst_00002", "ord_00003", "D05", 700)

    # ord_4 -- complete correct match, clean, but a false-alarm finding.
    insert_order(run_conn, "ord_00004")
    insert_leg(run_conn, "pay_00004")
    insert_leg(run_conn, "txfr_00004")
    insert_match(run_conn, "mtch_00004", ["pay_00004", "txfr_00004"])
    insert_settlement_unit(run_conn, "unit_00004", "ord_00004", match_id="mtch_00004")
    insert_finding(run_conn, "fnd_00002", "unit_00004", "D03", 200, [])
    insert_truth_record(truth_conn, "ord_00004", ["pay_00004", "txfr_00004"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})

    # ord_5 -- never matched, D06 undetected, escalated + unresolvable.
    insert_order(run_conn, "ord_00005")
    insert_leg(run_conn, "pay_00005")
    insert_leg(run_conn, "txfr_00005")
    insert_exception_unmatched(run_conn, "exc_00001", "pay_00005")
    insert_resolution(run_conn, "exc_00001", "ESCALATED_UNRESOLVED", what_would_resolve_it="more data")
    insert_agent_call(run_conn, "call_00001", "exc_00001", tokens_in=150, tokens_out=250)
    insert_truth_record(truth_conn, "ord_00005", ["pay_00005", "txfr_00005"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0}, resolvable=False)
    insert_injected_defect(truth_conn, "inst_00003", "ord_00005", "D06", 300)

    # ord_6 -- never matched, clean, escalated even though resolvable.
    insert_order(run_conn, "ord_00006")
    insert_leg(run_conn, "pay_00006")
    insert_leg(run_conn, "txfr_00006")
    insert_exception_unmatched(run_conn, "exc_00002", "pay_00006")
    insert_resolution(run_conn, "exc_00002", "ESCALATED_UNRESOLVED", what_would_resolve_it="nothing, it was resolvable")
    insert_truth_record(truth_conn, "ord_00006", ["pay_00006", "txfr_00006"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0}, resolvable=True)

    run_conn.commit()
    truth_conn.commit()
    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()
    return run, truth


def _compute(run, truth):
    scored_matches = score_all_matches(run, truth)
    scored_defects, true_positive_finding_ids = score_defects(run, truth)
    scored_abstentions = score_abstentions(run, truth)
    return compute_metrics(run, truth, scored_matches, scored_defects, true_positive_finding_ids, scored_abstentions)


def test_hand_computed_metrics(rich_scenario):
    run, truth = rich_scenario
    metrics = _metric_dict(_compute(run, truth))

    # total_records = 6 orders.
    # auto_matched_records = 2 (ord_1, ord_4 -- both legs under one match_id).
    assert metrics["auto_match_rate"] == (2 / 6, "ratio")

    # total_auto_matches = 4 match_groups (mtch_1..4).
    # correct_auto_matches = 2 (mtch_1, mtch_4 -- TRUE_POSITIVE).
    assert metrics["match_precision"] == (2 / 4, "ratio")

    # records_having_a_true_match = 6 (every order has a 2-leg closure).
    assert metrics["match_recall"] == (2 / 6, "ratio")

    # silent_count = 1 (mtch_3 only -- mtch_2 was caught).
    assert metrics["silent_error_rate"] == (1 / 4, "ratio")

    # defects_injected = 3 (inst_1 D02, inst_2 D05, inst_3 D06).
    # defects_detected = 1 (inst_1 only, via fnd_1).
    assert metrics["defect_recall"] == (1 / 3, "ratio")

    # total_flags = 2 (fnd_1, fnd_2). true_defects_flagged = 1 (fnd_1 only).
    assert metrics["defect_precision"] == (1 / 2, "ratio")

    # correctly_classified = 1 (inst_1). defects_detected = 1.
    assert metrics["root_cause_accuracy"] == (1 / 1, "ratio")

    assert metrics["leakage_caught_inr"] == (500, "paise")  # inst_1
    assert metrics["leakage_missed_inr"] == (700 + 300, "paise")  # inst_2 + inst_3
    assert metrics["false_alarm_inr"] == (200, "paise")  # fnd_2

    # total_unresolvable = 1 (ord_5). total_resolvable = 5 (the rest).
    assert metrics["correct_abstention_rate"] == (1 / 1, "ratio")  # exc_1
    assert metrics["over_abstention_rate"] == (1 / 5, "ratio")  # exc_2

    assert metrics["wall_clock_seconds_total"] == (10.0, "seconds")
    assert metrics["records_per_second"] == (6 / 10.0, "count")
    assert metrics["llm_tokens_per_1000_records"] == ((400 / 6) * 1000, "tokens")  # 150+250 tokens over 6 records

    assert metrics["inr_cost_per_1000_records"] == (None, "paise")  # no sourced rate -- always NOT_MEASURED
    assert metrics["determinism_score"] == (None, "ratio")  # single run, no observations


@pytest.fixture
def zero_denominator_scenario(tmp_path):
    """One order, an otherwise-empty run: every ratio whose components
    are all zero should print NOT_MEASURED, not 0.0 -- and every sum
    over an empty set should print a real 0, not NOT_MEASURED.
    """
    run_conn = make_run_db(tmp_path / "run.sqlite")
    truth_conn = make_truth_db(tmp_path / "truth.sqlite")
    insert_run_row(run_conn, started_at_utc="2026-01-01T00:00:00Z", finished_at_utc="2026-01-01T00:00:00Z")
    insert_truth_record(truth_conn, "ord_00001", ["pay_00001", "txfr_00001"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})

    run_conn.commit()
    truth_conn.commit()
    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()
    return run, truth


def test_zero_denominator_ratios_are_not_measured_not_zero(zero_denominator_scenario):
    run, truth = zero_denominator_scenario
    metrics = _metric_dict(_compute(run, truth))

    # total_auto_matches = 0 -> 0/0.
    assert metrics["match_precision"] == (None, "ratio")
    assert metrics["silent_error_rate"] == (None, "ratio")
    # defects_injected = 0 -> 0/0.
    assert metrics["defect_recall"] == (None, "ratio")
    # total_flags = 0 -> 0/0.
    assert metrics["defect_precision"] == (None, "ratio")
    # defects_detected = 0 -> 0/0.
    assert metrics["root_cause_accuracy"] == (None, "ratio")
    # total_unresolvable = 0 (the one order is resolvable) -> 0/0.
    assert metrics["correct_abstention_rate"] == (None, "ratio")
    # wall clock elapsed = 0 seconds -> can't divide by zero elapsed time.
    assert metrics["records_per_second"] == (None, "count")
    assert metrics["inr_cost_per_1000_records"] == (None, "paise")
    assert metrics["determinism_score"] == (None, "ratio")

    # total_records = 1 (nonzero denominator) -> real zeros, not NOT_MEASURED.
    assert metrics["auto_match_rate"] == (0.0, "ratio")
    # records_having_a_true_match = 1 -> 0/1.
    assert metrics["match_recall"] == (0.0, "ratio")
    # total_resolvable = 1 -> 0/1.
    assert metrics["over_abstention_rate"] == (0.0, "ratio")
    assert metrics["llm_tokens_per_1000_records"] == (0.0, "tokens")

    # SUM over an empty set is a real 0, not NOT_MEASURED.
    assert metrics["leakage_caught_inr"] == (0, "paise")
    assert metrics["leakage_missed_inr"] == (0, "paise")
    assert metrics["false_alarm_inr"] == (0, "paise")

    # wall_clock_seconds_total itself: both timestamps present, 0 seconds
    # apart -- a real measurement, not NOT_MEASURED (the manifest is complete).
    assert metrics["wall_clock_seconds_total"] == (0.0, "seconds")


@pytest.fixture
def empty_truth_scenario(tmp_path):
    """No orders at all -- total_records itself is 0."""
    run_conn = make_run_db(tmp_path / "run.sqlite")
    truth_conn = make_truth_db(tmp_path / "truth.sqlite")
    insert_run_row(run_conn)
    run_conn.commit()
    truth_conn.commit()
    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()
    return run, truth


def test_completely_empty_truth_store_reports_not_measured_where_denominator_is_the_record_count(empty_truth_scenario):
    run, truth = empty_truth_scenario
    metrics = _metric_dict(_compute(run, truth))
    assert metrics["auto_match_rate"] == (None, "ratio")
    assert metrics["match_recall"] == (None, "ratio")
    assert metrics["over_abstention_rate"] == (None, "ratio")
    assert metrics["llm_tokens_per_1000_records"] == (None, "tokens")


def test_every_prd_7_metric_has_a_row(rich_scenario):
    run, truth = rich_scenario
    names = {m.name for m in _compute(run, truth)}
    assert names == {
        "auto_match_rate", "match_precision", "match_recall", "silent_error_rate",
        "defect_recall", "defect_precision", "root_cause_accuracy",
        "leakage_caught_inr", "leakage_missed_inr", "false_alarm_inr",
        "correct_abstention_rate", "over_abstention_rate",
        "records_per_second", "wall_clock_seconds_total",
        "llm_tokens_per_1000_records", "inr_cost_per_1000_records",
        "determinism_score",
    }
