"""score_match's two branches (LLD §8) hand-computed on paper first:
silent = wrong AND nothing was raised. A wrong match that was flagged
(a finding on its unit, or an exception on one of its members) is
caught, not silent -- both get their own explicit test, per the
instruction that getting this wrong in either direction is a real
failure mode, not just a style question.
"""

import pytest

from plumb_eval.errors import TruthJoinError
from plumb_eval.run_reader import RunData
from plumb_eval.scoring import score_abstentions, score_all_matches, score_defects, validate_no_fabrication
from plumb_eval.truth_store import TruthStore

from _fixtures import (
    insert_exception_unmatched,
    insert_finding,
    insert_leg,
    insert_match,
    insert_order,
    insert_run_row,
    insert_settlement_unit,
    insert_truth_record,
)


@pytest.fixture
def scenario(tmp_path):
    """Four orders, each with a match_group, covering all four score_match
    outcomes. Every leg's amounts/dates are irrelevant to score_match --
    only record_keys and the match/truth topology matter here.
    """
    run_path = tmp_path / "run.sqlite"
    truth_path = tmp_path / "truth.sqlite"

    from _fixtures import make_run_db, make_truth_db

    run_conn = make_run_db(run_path)
    truth_conn = make_truth_db(truth_path)

    insert_run_row(run_conn)

    # --- Order 1: correctly and completely matched -> TRUE_POSITIVE ---
    # The matcher groups the order key and the intent leg alongside the
    # razorpay/bank legs (match/engine.py P0 ID_CHAIN), so a complete
    # match_group carries all six; truth's closure = intent leg +
    # true_counterparts + the order's own key (truth_store.py).
    insert_order(run_conn, "ord_00001")
    for key in ("int_00001", "pay_00001", "txfr_00001", "setl_00001", "bank_00001"):
        insert_leg(run_conn, key)
    insert_match(run_conn, "mtch_00001", ["ord_00001", "int_00001", "pay_00001", "txfr_00001", "setl_00001", "bank_00001"])
    insert_settlement_unit(run_conn, "unit_00001", "ord_00001", match_id="mtch_00001")
    insert_truth_record(
        truth_conn, "ord_00001",
        ["int_00001", "pay_00001", "txfr_00001", "setl_00001", "bank_00001"],
        {"commission_paise": 100, "tcs_paise": 10, "tds_paise": 5},
    )

    # --- Order 2: wrong match (missing a leg), but a finding on its unit
    #     catches it -> FALSE_POSITIVE, silent=False ---
    insert_order(run_conn, "ord_00002")
    insert_leg(run_conn, "pay_00002")
    insert_leg(run_conn, "txfr_00002")
    insert_match(run_conn, "mtch_00002", ["pay_00002"])  # missing txfr_00002 -- wrong
    insert_settlement_unit(run_conn, "unit_00002", "ord_00002", match_id="mtch_00002")
    insert_finding(run_conn, "fnd_00001", "unit_00002", "D02", 500, ["pay_00002"])
    insert_truth_record(truth_conn, "ord_00002", ["pay_00002", "txfr_00002"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})

    # --- Order 3: wrong match, caught by an exception directly on a
    #     member (not via a finding) -> FALSE_POSITIVE, silent=False ---
    insert_order(run_conn, "ord_00003")
    insert_leg(run_conn, "pay_00003")
    insert_leg(run_conn, "txfr_00003")
    insert_match(run_conn, "mtch_00003", ["pay_00003"])  # missing txfr_00003 -- wrong
    insert_settlement_unit(run_conn, "unit_00003", "ord_00003", match_id="mtch_00003")
    insert_exception_unmatched(run_conn, "exc_00001", "pay_00003")
    insert_truth_record(truth_conn, "ord_00003", ["pay_00003", "txfr_00003"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})

    # --- Order 4: wrong match, nothing raised at all -> FALSE_POSITIVE,
    #     silent=True -- the headline number ---
    insert_order(run_conn, "ord_00004")
    insert_leg(run_conn, "pay_00004")
    insert_leg(run_conn, "txfr_00004")
    insert_match(run_conn, "mtch_00004", ["pay_00004"])  # missing txfr_00004 -- wrong
    insert_settlement_unit(run_conn, "unit_00004", "ord_00004", match_id="mtch_00004")
    insert_truth_record(truth_conn, "ord_00004", ["pay_00004", "txfr_00004"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})

    run_conn.commit()
    truth_conn.commit()

    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()
    return run, truth


def test_correct_and_complete_match_is_true_positive(scenario):
    run, truth = scenario
    scored = {s.match_id: s for s in score_all_matches(run, truth)}
    assert scored["mtch_00001"].verdict == "TRUE_POSITIVE"
    assert scored["mtch_00001"].silent is False


def test_wrong_match_caught_by_a_finding_is_not_silent(scenario):
    run, truth = scenario
    scored = {s.match_id: s for s in score_all_matches(run, truth)}
    assert scored["mtch_00002"].verdict == "FALSE_POSITIVE"
    assert scored["mtch_00002"].silent is False


def test_wrong_match_caught_by_an_exception_on_a_member_is_not_silent(scenario):
    run, truth = scenario
    scored = {s.match_id: s for s in score_all_matches(run, truth)}
    assert scored["mtch_00003"].verdict == "FALSE_POSITIVE"
    assert scored["mtch_00003"].silent is False


def test_wrong_match_with_nothing_raised_is_silent(scenario):
    run, truth = scenario
    scored = {s.match_id: s for s in score_all_matches(run, truth)}
    assert scored["mtch_00004"].verdict == "FALSE_POSITIVE"
    assert scored["mtch_00004"].silent is True


def test_validate_no_fabrication_passes_on_a_clean_run(scenario):
    run, truth = scenario
    validate_no_fabrication(run, truth)  # must not raise


def test_validate_no_fabrication_raises_on_an_unknown_record_key(tmp_path):
    from _fixtures import insert_leg, insert_match, insert_run_row, insert_truth_record, make_run_db, make_truth_db

    run_conn = make_run_db(tmp_path / "run.sqlite")
    truth_conn = make_truth_db(tmp_path / "truth.sqlite")
    insert_run_row(run_conn)
    insert_leg(run_conn, "pay_99999")
    insert_match(run_conn, "mtch_00001", ["pay_99999"])  # never appears in any truth_record
    insert_truth_record(truth_conn, "ord_00001", ["pay_00001"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})
    run_conn.commit()
    truth_conn.commit()

    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()

    with pytest.raises(TruthJoinError):
        validate_no_fabrication(run, truth)


def test_a_match_with_a_substituted_leg_still_scores_false_positive(tmp_path):
    """The _is_settlement_identity strip (order + intent + refund/dispute/
    reversal) must not turn a genuinely wrong match into a TRUE_POSITIVE.
    Here mtch_00002 is order 2's group but with order 1's payment key
    swapped in -- the stripped members still carry pay_00001, which no
    single closure contains alongside order 2's other legs -> FALSE_POSITIVE.
    Hand-computed: after the strip, members = {int_00002, pay_00001,
    txfr_00002}; anchor = int_00002 -> closure = {int_00002, pay_00002,
    txfr_00002}; members != closure.
    """
    from _fixtures import (
        insert_leg,
        insert_match,
        insert_order,
        insert_run_row,
        insert_settlement_unit,
        insert_truth_record,
        make_run_db,
        make_truth_db,
    )

    run_conn = make_run_db(tmp_path / "run.sqlite")
    truth_conn = make_truth_db(tmp_path / "truth.sqlite")
    insert_run_row(run_conn)

    for key in ("ord_00001", "int_00001", "pay_00001", "txfr_00001"):
        (insert_order if key == "ord_00001" else insert_leg)(run_conn, key)
    for key in ("ord_00002", "int_00002", "pay_00002", "txfr_00002"):
        (insert_order if key == "ord_00002" else insert_leg)(run_conn, key)

    insert_match(run_conn, "mtch_00002", ["ord_00002", "int_00002", "pay_00001", "txfr_00002"])  # wrong payment
    insert_settlement_unit(run_conn, "unit_00002", "ord_00002", match_id="mtch_00002")
    insert_truth_record(truth_conn, "ord_00001", ["int_00001", "pay_00001", "txfr_00001"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})
    insert_truth_record(truth_conn, "ord_00002", ["int_00002", "pay_00002", "txfr_00002"], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})
    run_conn.commit()
    truth_conn.commit()

    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()

    validate_no_fabrication(run, truth)  # pay_00001 is a real leg -> no fabrication
    scored = {s.match_id: s for s in score_all_matches(run, truth)}
    assert scored["mtch_00002"].verdict == "FALSE_POSITIVE"


def test_validate_no_fabrication_backstops_resolution_evidence(tmp_path):
    """resolution_evidence.record_key has an FK to record_index, so a
    hallucinated L3 evidence key cannot be written to a well-formed
    run.sqlite. validate_no_fabrication is the score-time backstop for a
    run.sqlite that wasn't produced by our writer (FKs off, hand-edited):
    an evidence key absent from record_index fails the run.
    """
    run = RunData(
        run_id="r", started_at_utc="", finished_at_utc=None,
        match_groups=[], settlement_units=[], findings=[], exceptions=[], resolutions=[],
        agent_call_tokens_total=0, agent_call_count=0,
        record_index_keys=frozenset({"pay_00001"}),
        resolution_evidence_keys=frozenset({"pay_00001", "pay_99999"}),  # pay_99999 never ingested
    )
    truth = TruthStore(
        _closure_by_key={"pay_00001": frozenset({"pay_00001"})},
        _order_key_by_member={"pay_00001": "ord_00001"},
        _obligation_by_key={}, _resolvable_by_key={}, _defects_by_key={},
    )
    with pytest.raises(TruthJoinError, match="pay_99999"):
        validate_no_fabrication(run, truth)


@pytest.fixture
def defect_scenario(tmp_path):
    """Four orders covering score_defects' four outcomes: correctly
    detected+classified, detected with the wrong class, not detected at
    all, and a false alarm on a genuinely clean order.
    """
    from _fixtures import (
        insert_finding,
        insert_injected_defect,
        insert_order,
        insert_run_row,
        insert_settlement_unit,
        insert_truth_record,
        make_run_db,
        make_truth_db,
    )

    run_conn = make_run_db(tmp_path / "run.sqlite")
    truth_conn = make_truth_db(tmp_path / "truth.sqlite")
    insert_run_row(run_conn)

    # Order X: D02 injected, correctly detected and classified.
    insert_order(run_conn, "ord_00001")
    insert_settlement_unit(run_conn, "unit_00001", "ord_00001")
    insert_finding(run_conn, "fnd_00001", "unit_00001", "D02", 500, [])
    insert_truth_record(truth_conn, "ord_00001", [], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})
    insert_injected_defect(truth_conn, "inst_00001", "ord_00001", "D02", 500)

    # Order Y: D05 injected, a finding was raised on it but classified D01 -- wrong class.
    insert_order(run_conn, "ord_00002")
    insert_settlement_unit(run_conn, "unit_00002", "ord_00002")
    insert_finding(run_conn, "fnd_00002", "unit_00002", "D01", 300, [])
    insert_truth_record(truth_conn, "ord_00002", [], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})
    insert_injected_defect(truth_conn, "inst_00002", "ord_00002", "D05", 700)

    # Order Z: D06 injected, nothing was ever raised on it -- a recall miss.
    insert_order(run_conn, "ord_00003")
    insert_settlement_unit(run_conn, "unit_00003", "ord_00003")
    insert_truth_record(truth_conn, "ord_00003", [], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})
    insert_injected_defect(truth_conn, "inst_00003", "ord_00003", "D06", 1200)

    # Order W: genuinely clean, but a finding was raised anyway -- a false alarm.
    insert_order(run_conn, "ord_00004")
    insert_settlement_unit(run_conn, "unit_00004", "ord_00004")
    insert_finding(run_conn, "fnd_00003", "unit_00004", "D03", 200, [])
    insert_truth_record(truth_conn, "ord_00004", [], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0})

    run_conn.commit()
    truth_conn.commit()
    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()
    return run, truth


def test_defect_correctly_detected_and_classified(defect_scenario):
    run, truth = defect_scenario
    scored, true_positive_findings = score_defects(run, truth)
    by_id = {s.instance_id: s for s in scored}
    assert by_id["inst_00001"].was_detected is True
    assert by_id["inst_00001"].detected_finding_id == "fnd_00001"
    assert by_id["inst_00001"].class_correct is True
    assert "fnd_00001" in true_positive_findings


def test_defect_detected_with_wrong_class(defect_scenario):
    run, truth = defect_scenario
    scored, true_positive_findings = score_defects(run, truth)
    by_id = {s.instance_id: s for s in scored}
    assert by_id["inst_00002"].was_detected is True
    assert by_id["inst_00002"].detected_finding_id == "fnd_00002"
    assert by_id["inst_00002"].class_correct is False
    assert "fnd_00002" not in true_positive_findings


def test_defect_never_detected(defect_scenario):
    run, truth = defect_scenario
    scored, _ = score_defects(run, truth)
    by_id = {s.instance_id: s for s in scored}
    assert by_id["inst_00003"].was_detected is False
    assert by_id["inst_00003"].detected_finding_id is None
    assert by_id["inst_00003"].class_correct is None


def test_finding_on_a_clean_order_is_not_a_true_positive(defect_scenario):
    run, truth = defect_scenario
    _, true_positive_findings = score_defects(run, truth)
    assert "fnd_00003" not in true_positive_findings


@pytest.fixture
def abstention_scenario(tmp_path):
    """Two escalations: one on a truly unresolvable order (correct
    abstention) and one on a resolvable order (over-abstention).
    """
    from _fixtures import (
        insert_exception_unmatched,
        insert_order,
        insert_resolution,
        insert_run_row,
        insert_truth_record,
        make_run_db,
        make_truth_db,
    )

    run_conn = make_run_db(tmp_path / "run.sqlite")
    truth_conn = make_truth_db(tmp_path / "truth.sqlite")
    insert_run_row(run_conn)

    insert_order(run_conn, "ord_00001")
    insert_exception_unmatched(run_conn, "exc_00001", "ord_00001")
    insert_resolution(run_conn, "exc_00001", "ESCALATED_UNRESOLVED", what_would_resolve_it="a bank statement")
    insert_truth_record(truth_conn, "ord_00001", [], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0}, resolvable=False)

    insert_order(run_conn, "ord_00002")
    insert_exception_unmatched(run_conn, "exc_00002", "ord_00002")
    insert_resolution(run_conn, "exc_00002", "ESCALATED_UNRESOLVED", what_would_resolve_it="nothing, it was resolvable")
    insert_truth_record(truth_conn, "ord_00002", [], {"commission_paise": 0, "tcs_paise": 0, "tds_paise": 0}, resolvable=True)

    run_conn.commit()
    truth_conn.commit()
    run = RunData.from_db(run_conn)
    truth = TruthStore.from_db(truth_conn)
    run_conn.close()
    truth_conn.close()
    return run, truth


def test_escalation_on_an_unresolvable_record_is_correct_abstention(abstention_scenario):
    run, truth = abstention_scenario
    scored = {s.exception_id: s.verdict for s in score_abstentions(run, truth)}
    assert scored["exc_00001"] == "CORRECT_ABSTENTION"


def test_escalation_on_a_resolvable_record_is_over_abstention(abstention_scenario):
    run, truth = abstention_scenario
    scored = {s.exception_id: s.verdict for s in score_abstentions(run, truth)}
    assert scored["exc_00002"] == "OVER_ABSTENTION"
