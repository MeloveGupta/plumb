"""Hand-built tiny sqlite fixtures for plumb_eval tests.

Uses plumb.store.ddl.open_run_db and plumb_gen.truth_db.open_truth_db
directly. That's legal here even though production plumb_eval code
can't import plumb.store (TRD §3.1 restricts plumb_eval to plumb.domain
and plumb_gen) -- the import-boundary AST test only walks src/plumb_eval/,
not tests/.
"""

import json
import sqlite3

from plumb.store.ddl import open_run_db
from plumb_gen.truth_db import open_truth_db


def make_run_db(path) -> sqlite3.Connection:
    return open_run_db(path)


def make_truth_db(path) -> sqlite3.Connection:
    return open_truth_db(path)


def insert_truth_record(conn, record_key, true_counterparts, true_obligation, resolvable=True):
    conn.execute(
        "INSERT INTO truth_record (record_key, true_counterparts_json, true_obligation_json, "
        "resolvable_from_available_data) VALUES (?,?,?,?)",
        (record_key, json.dumps(true_counterparts), json.dumps(true_obligation), int(resolvable)),
    )


def insert_injected_defect(conn, instance_id, record_key, defect_class, amount_at_risk_paise, within_tolerance=False, params=None):
    conn.execute(
        "INSERT INTO injected_defect (instance_id, record_key, defect_class, amount_at_risk_paise, "
        "within_tolerance, params_json) VALUES (?,?,?,?,?,?)",
        (instance_id, record_key, defect_class, amount_at_risk_paise, int(within_tolerance), json.dumps(params or {})),
    )


def insert_record_index(conn, record_key, entity_type="synthetic", source_id="test"):
    conn.execute(
        "INSERT INTO record_index (record_key, entity_type, source_id, raw_id) VALUES (?,?,?,NULL)",
        (record_key, entity_type, source_id),
    )


def insert_order(conn, record_key, seller_id="sel_00001"):
    insert_record_index(conn, record_key, entity_type="order", source_id="derived")
    conn.execute(
        """INSERT INTO "order" (record_key, seller_id, gross_paise, category, placed_at_utc, status, is_interstate)
           VALUES (?, ?, 10000, 'general', '2026-01-01T00:00:00Z', 'completed', 0)""",
        (record_key, seller_id),
    )


def insert_leg(conn, record_key, entity_type="payment", source_id="razorpay"):
    insert_record_index(conn, record_key, entity_type=entity_type, source_id=source_id)


def insert_match(conn, match_id, member_keys, rule_id="rule_test", pass_="P0", confidence=1.0):
    conn.execute(
        "INSERT INTO match_group (match_id, rule_id, pass, confidence) VALUES (?,?,?,?)",
        (match_id, rule_id, pass_, confidence),
    )
    sides = ("intent", "razorpay", "bank")
    for i, key in enumerate(member_keys):
        conn.execute(
            "INSERT INTO match_member (match_id, record_key, side) VALUES (?,?,?)",
            (match_id, key, sides[i % 3]),
        )


def insert_settlement_unit(conn, unit_id, order_key, match_id=None, seller_id="sel_00001", period="2026-01"):
    conn.execute(
        "INSERT INTO settlement_unit (unit_id, order_key, match_id, seller_id, period) VALUES (?,?,?,?,?)",
        (unit_id, order_key, match_id, seller_id, period),
    )


def insert_finding(
    conn, finding_id, unit_id, defect_id, amount_at_risk_paise, evidence_keys,
    severity="medium", on_matched_record=False, conclusion="test finding",
):
    conn.execute(
        """INSERT INTO finding (finding_id, unit_id, defect_id, severity, amount_at_risk_paise,
             on_matched_record, conclusion) VALUES (?,?,?,?,?,?,?)""",
        (finding_id, unit_id, defect_id, severity, amount_at_risk_paise, int(on_matched_record), conclusion),
    )
    for key in evidence_keys:
        conn.execute(
            "INSERT INTO finding_evidence (finding_id, record_key, role) VALUES (?,?,?)",
            (finding_id, key, "evidence"),
        )


def insert_exception_unmatched(conn, exception_id, record_key, amount_at_risk_paise=0, queue_rank=1):
    conn.execute(
        "INSERT INTO exception (exception_id, origin, record_key, finding_id, amount_at_risk_paise, queue_rank) "
        "VALUES (?, 'UNMATCHED', ?, NULL, ?, ?)",
        (exception_id, record_key, amount_at_risk_paise, queue_rank),
    )


def insert_exception_finding(conn, exception_id, finding_id, amount_at_risk_paise=0, queue_rank=1):
    conn.execute(
        "INSERT INTO exception (exception_id, origin, record_key, finding_id, amount_at_risk_paise, queue_rank) "
        "VALUES (?, 'FINDING', NULL, ?, ?, ?)",
        (exception_id, finding_id, amount_at_risk_paise, queue_rank),
    )


def insert_resolution(
    conn, exception_id, outcome, confidence=0.9, iterations_used=1, stop_reason="rules_only",
    what_was_tried="checked recompute trace", what_would_resolve_it=None, model_claimed_outcome=None,
):
    conn.execute(
        """INSERT INTO resolution (exception_id, outcome, model_claimed_outcome, was_downgraded,
             downgrade_reason, confidence, chosen_hypothesis_id, iterations_used, stop_reason,
             what_was_tried, what_would_resolve_it) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            exception_id, outcome, model_claimed_outcome or outcome, 0, None,
            confidence, None, iterations_used, stop_reason, what_was_tried, what_would_resolve_it,
        ),
    )


def insert_run_row(
    conn, run_id="run_test", started_at_utc="2026-01-01T00:00:00Z", finished_at_utc="2026-01-01T00:00:10Z",
    batch_id="batch_test", generator_seed=1, sample_label="HELD_OUT", ablation_config="rules_only",
):
    conn.execute(
        """INSERT INTO run (run_id, plumb_version, git_sha, git_dirty, batch_id, generator_seed,
             generator_config_sha256, engine_config_sha256, schema_sha256, tolerance_profile,
             rules_module_version, ablation_config, sample_label, llm_model, llm_temperature,
             started_at_utc, finished_at_utc)
           VALUES (?, 'test', 'deadbeef', 0, ?, ?, 'sha', 'sha', 'sha', 'default_v1', 'v1', ?, ?,
                   NULL, NULL, ?, ?)""",
        (run_id, batch_id, generator_seed, ablation_config, sample_label, started_at_utc, finished_at_utc),
    )
