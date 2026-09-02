"""BACKEND_SCHEMA.md §3.3/§3.5/§3.6/§3.7 -- the L2/L3 writers, checked
against a real run.sqlite (plumb.store.ddl.open_run_db), FK enforcement
and append-only triggers included. IDs and counts are read off the
inserts in the test, never derived from the writers' own output.
"""

import sqlite3

import pytest

from plumb.domain.keys import IdSequence
from plumb.store.ddl import open_run_db
from plumb.store.writer import (
    write_agent_call,
    write_config_snapshot,
    write_exception,
    write_finding,
    write_finding_evidence,
    write_hypothesis,
    write_order_row,
    write_recompute_step,
    write_record_index,
    write_record_terminal_state,
    write_resolution,
    write_resolution_evidence,
    write_run_row,
    write_settlement_unit,
)


@pytest.fixture
def conn():
    c = open_run_db(":memory:")
    yield c
    c.close()


def _order(conn, key="ord_00001"):
    write_record_index(conn, key, "order", "intent")
    write_order_row(
        conn, record_key=key, seller_id="sel_00001", gross_paise=100_000,
        category="electronics", placed_at_utc="2026-07-01T00:00:00Z", status="captured", is_interstate=False,
    )
    return key


def _unit(conn, order_key="ord_00001", unit_id="unit_00001"):
    write_settlement_unit(conn, unit_id=unit_id, order_key=order_key, match_id=None, seller_id="sel_00001", period="2026-07")
    return unit_id


def test_record_index_and_order_round_trip(conn):
    _order(conn, "ord_00042")
    row = conn.execute('SELECT seller_id, gross_paise, is_interstate FROM "order" WHERE record_key = ?', ("ord_00042",)).fetchone()
    assert row == ("sel_00001", 100_000, 0)
    assert conn.execute("SELECT entity_type FROM record_index WHERE record_key = ?", ("ord_00042",)).fetchone() == ("order",)


def test_settlement_unit_and_finding(conn):
    ids = IdSequence()
    _order(conn)
    unit_id = _unit(conn)
    assert unit_id == "unit_00001"

    finding_id = "fnd_00001"
    write_finding(
        conn, finding_id=finding_id, unit_id=unit_id, defect_id="D01", severity="high",
        amount_at_risk_paise=2_000, on_matched_record=True, conclusion="rate drift",
    )
    row = conn.execute(
        "SELECT defect_id, severity, amount_at_risk_paise, on_matched_record FROM finding WHERE finding_id = ?",
        (finding_id,),
    ).fetchone()
    assert row == ("D01", "high", 2_000, 1)

    write_recompute_step(conn, finding_id, step_no=1, label="delta", formula="a - b", inputs={"a": 5, "b": 2}, output_paise=3)
    assert conn.execute("SELECT inputs_json, output_paise FROM recompute_step WHERE finding_id = ?", (finding_id,)).fetchone() == (
        '{"a": 5, "b": 2}',
        3,
    )

    write_finding_evidence(conn, finding_id, "ord_00001", "order")
    assert conn.execute("SELECT role FROM finding_evidence WHERE finding_id = ?", (finding_id,)).fetchone() == ("order",)


def test_finding_evidence_fk_rejects_an_unknown_record_key(conn):
    ids = IdSequence()
    _order(conn)
    unit_id = _unit(conn)
    finding_id = "fnd_00001"
    write_finding(
        conn, finding_id=finding_id, unit_id=unit_id, defect_id="D02", severity="low",
        amount_at_risk_paise=1, on_matched_record=False, conclusion="x",
    )
    with pytest.raises(sqlite3.IntegrityError):
        write_finding_evidence(conn, finding_id, "pay_99999", "payment")  # not in record_index


def test_exception_paired_checks(conn):
    _order(conn)
    write_record_index(conn, "bank_00001", "bank_credit", "bank")
    # UNMATCHED requires record_key, forbids finding_id
    write_exception(
        conn, exception_id="exc_00001", origin="UNMATCHED", record_key="bank_00001",
        finding_id=None, amount_at_risk_paise=500_000, queue_rank=1,
    )
    assert conn.execute("SELECT origin FROM exception WHERE exception_id = ?", ("exc_00001",)).fetchone() == ("UNMATCHED",)

    with pytest.raises(sqlite3.IntegrityError):
        write_exception(
            conn, exception_id="exc_00002", origin="UNMATCHED", record_key=None,
            finding_id=None, amount_at_risk_paise=1, queue_rank=2,
        )


def test_hypothesis_resolution_and_evidence(conn):
    ids = IdSequence()
    _order(conn)
    write_record_index(conn, "bank_00001", "bank_credit", "bank")
    write_exception(
        conn, exception_id="exc_00001", origin="UNMATCHED", record_key="bank_00001",
        finding_id=None, amount_at_risk_paise=500_000, queue_rank=1,
    )
    hyp_id = write_hypothesis(conn, ids, exception_id="exc_00001", rank=1, statement="in flight", supports=["bank_00001"])
    assert hyp_id == "hyp_00001"

    write_resolution(
        conn, exception_id="exc_00001", outcome="PROPOSED", model_claimed_outcome="AUTO_RESOLVED",
        was_downgraded=True, downgrade_reason="amount_above_threshold", confidence_bps=9_500,
        chosen_hypothesis_id=hyp_id, iterations_used=3, stop_reason="sufficient_evidence",
        what_was_tried="checked the settlement recon", what_would_resolve_it=None,
    )
    row = conn.execute(
        "SELECT outcome, model_claimed_outcome, was_downgraded, confidence, chosen_hypothesis_id "
        "FROM resolution WHERE exception_id = ?",
        ("exc_00001",),
    ).fetchone()
    assert row == ("PROPOSED", "AUTO_RESOLVED", 1, 0.95, "hyp_00001")

    write_resolution_evidence(conn, "exc_00001", "bank_00001", "in_flight_credit")
    assert conn.execute("SELECT role FROM resolution_evidence WHERE exception_id = ?", ("exc_00001",)).fetchone() == (
        "in_flight_credit",
    )


def test_resolution_check_rejects_escalation_without_resolve_hint(conn):
    _order(conn)
    write_record_index(conn, "bank_00001", "bank_credit", "bank")
    write_exception(
        conn, exception_id="exc_00001", origin="UNMATCHED", record_key="bank_00001",
        finding_id=None, amount_at_risk_paise=1, queue_rank=1,
    )
    with pytest.raises(sqlite3.IntegrityError):
        write_resolution(
            conn, exception_id="exc_00001", outcome="ESCALATED_UNRESOLVED", model_claimed_outcome="ESCALATED_UNRESOLVED",
            was_downgraded=False, downgrade_reason=None, confidence_bps=0, chosen_hypothesis_id=None,
            iterations_used=8, stop_reason="iteration_cap", what_was_tried="everything",
            what_would_resolve_it=None,  # the CHECK forbids this
        )


def test_agent_call_round_trips_and_rejects_iteration_out_of_range(conn):
    _order(conn)
    write_record_index(conn, "bank_00001", "bank_credit", "bank")
    write_exception(
        conn, exception_id="exc_00001", origin="UNMATCHED", record_key="bank_00001",
        finding_id=None, amount_at_risk_paise=1, queue_rank=1,
    )
    write_agent_call(
        conn, call_id="call_00001", exception_id="exc_00001", iteration=2, tool="fetch_payment",
        args={"payment_id": "pay_00001"}, result_sha256="a" * 64, result_row_count=1,
        latency_ms=42, tokens_in=1_200, tokens_out=80, called_at_utc="2026-09-02T10:00:00Z",
    )
    assert conn.execute("SELECT tool, tokens_in FROM agent_call WHERE call_id = ?", ("call_00001",)).fetchone() == (
        "fetch_payment",
        1_200,
    )
    with pytest.raises(sqlite3.IntegrityError):
        write_agent_call(
            conn, call_id="call_00002", exception_id="exc_00001", iteration=9, tool="x",
            args={}, result_sha256="b" * 64, result_row_count=0, latency_ms=0,
            tokens_in=0, tokens_out=0, called_at_utc="2026-09-02T10:00:00Z",
        )


def test_append_only_triggers_block_update(conn):
    ids = IdSequence()
    _order(conn)
    unit_id = _unit(conn)
    finding_id = "fnd_00001"
    write_finding(
        conn, finding_id=finding_id, unit_id=unit_id, defect_id="D03", severity="low",
        amount_at_risk_paise=1, on_matched_record=False, conclusion="x",
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE finding SET conclusion = 'y' WHERE finding_id = ?", (finding_id,))


def test_terminal_state_and_conservation(conn):
    _order(conn, "ord_00001")
    write_record_index(conn, "bank_00001", "bank_credit", "bank")
    write_record_terminal_state(conn, "ord_00001", "VERIFIED_CLEAN")
    write_record_terminal_state(conn, "bank_00001", "ESCALATED_UNRESOLVED")
    assert conn.execute("SELECT records_in, accounted_for FROM v_conservation").fetchone() == (2, 2)


def test_run_row_and_config_snapshot(conn):
    write_run_row(
        conn, run_id="2026-09-02T10:00:00Z-abc123", plumb_version="0.1.0", git_sha="0" * 40, git_dirty=False,
        batch_id="batch_main_200", generator_seed=42, generator_config_sha256="c" * 64,
        engine_config_sha256="d" * 64, schema_sha256="e" * 64, tolerance_profile="default_v1",
        rules_module_version="2026-08-28", ablation_config="rules_only", sample_label="HELD_OUT",
        llm_model=None, started_at_utc="2026-09-02T10:00:00Z", finished_at_utc="2026-09-02T10:00:05Z",
        llm_temperature=None,
    )
    assert conn.execute("SELECT ablation_config, sample_label, llm_model FROM run").fetchone() == (
        "rules_only",
        "HELD_OUT",
        None,
    )
    write_config_snapshot(conn, "agent", {"auto_resolve_threshold_paise": 10_000, "confidence_threshold_bps": 9_000})
    assert conn.execute("SELECT value_json FROM config_snapshot WHERE key = 'agent'").fetchone()[0] == (
        '{"auto_resolve_threshold_paise": 10000, "confidence_threshold_bps": 9000}'
    )
