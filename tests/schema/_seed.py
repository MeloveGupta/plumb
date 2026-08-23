"""Minimal valid row chains for schema tests.

Each function seeds only what its target table's FK chain requires, so a
test only has to say what it actually needs (e.g. seed_finding builds
record_index -> order -> settlement_unit -> finding).
"""


def seed_record_index(conn, record_key):
    conn.execute(
        "INSERT INTO record_index (record_key, entity_type, source_id) VALUES (?, 'order', 'intent')",
        (record_key,),
    )
    return record_key


def seed_order(conn, record_key):
    seed_record_index(conn, record_key)
    conn.execute(
        """INSERT INTO "order" (record_key, seller_id, gross_paise, category, placed_at_utc, status, is_interstate)
           VALUES (?, 'sel_00001', 100000, 'electronics', '2026-07-01T00:00:00Z', 'captured', 0)""",
        (record_key,),
    )
    return record_key


def seed_settlement_unit(conn, unit_id, order_key):
    seed_order(conn, order_key)
    conn.execute(
        "INSERT INTO settlement_unit (unit_id, order_key, seller_id, period) VALUES (?, ?, 'sel_00001', '2026-07')",
        (unit_id, order_key),
    )
    return unit_id


def seed_finding(conn, finding_id, unit_id, order_key):
    seed_settlement_unit(conn, unit_id, order_key)
    conn.execute(
        """INSERT INTO finding (finding_id, unit_id, defect_id, severity, amount_at_risk_paise,
                                 on_matched_record, conclusion)
           VALUES (?, ?, 'D02', 'medium', 3000, 0, 'short settlement in tolerance')""",
        (finding_id, unit_id),
    )
    return finding_id


def seed_exception(conn, exception_id, record_key):
    seed_record_index(conn, record_key)
    conn.execute(
        """INSERT INTO exception (exception_id, origin, record_key, amount_at_risk_paise, queue_rank)
           VALUES (?, 'UNMATCHED', ?, 3000, 1)""",
        (exception_id, record_key),
    )
    return exception_id


def seed_resolution(conn, exception_id, record_key):
    seed_exception(conn, exception_id, record_key)
    conn.execute(
        """INSERT INTO resolution (exception_id, outcome, model_claimed_outcome, was_downgraded,
                                    confidence, iterations_used, stop_reason, what_was_tried)
           VALUES (?, 'PROPOSED', 'PROPOSED', 0, 0.8, 1, 'sufficient_evidence', 'checked ledger')""",
        (exception_id,),
    )
    return exception_id


def seed_agent_call(conn, call_id, exception_id, record_key):
    seed_exception(conn, exception_id, record_key)
    conn.execute(
        """INSERT INTO agent_call (call_id, exception_id, iteration, tool, args_json, result_sha256,
                                    result_row_count, latency_ms, tokens_in, tokens_out, called_at_utc)
           VALUES (?, ?, 1, 'fetch_refunds_for_payment', '{}', 'deadbeef', 0, 10, 100, 50,
                    '2026-08-25T00:00:00Z')""",
        (call_id, exception_id),
    )
    return call_id


def seed_match_group(conn, match_id):
    conn.execute(
        "INSERT INTO match_group (match_id, rule_id, pass, confidence) VALUES (?, 'ID_ORDER', 'P0', 1.0)",
        (match_id,),
    )
    return match_id


def seed_match_member(conn, match_id, record_key):
    seed_match_group(conn, match_id)
    seed_record_index(conn, record_key)
    conn.execute(
        "INSERT INTO match_member (match_id, record_key, side) VALUES (?, ?, 'intent')",
        (match_id, record_key),
    )
    return match_id


def seed_record_terminal_state(conn, record_key):
    seed_record_index(conn, record_key)
    conn.execute(
        "INSERT INTO record_terminal_state (record_key, terminal_state) VALUES (?, 'VERIFIED_CLEAN')",
        (record_key,),
    )
    return record_key
