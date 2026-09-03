"""BACKEND_SCHEMA.md §3 -- every run.sqlite writer.

Originally just the §3.2 provenance chain (source_file, raw_record,
transform_log, quarantine) + §3.4 matching. The L3 persistence bridge
adds §3.3 record_index, §3.5 verification (settlement_unit, finding,
recompute_step, finding_evidence), §3.6 exceptions & agent (exception,
hypothesis, agent_call, resolution, resolution_evidence), §3.7 terminal
states, and §3.1 provenance (run, config_snapshot).

Every writer here persists what an upstream layer already computed --
ingest/verify/agent stay pure, writing is this module's job. Takes
plain scalars/tuples rather than importing those layers' dataclasses:
`store <- all layers` means store sits beneath every layer, never
depends on one -- importing ingest's or verify's types here would be a
real circular import, not just an untidy one. Callers unpack the
dataclasses into plain arguments at the call site (store/run_writer.py
is the one orchestrator that does that unpacking for L2/L3).

The one float in this file -- `confidence_bps / 10_000` in
write_match_group and write_resolution -- is a bare expression right at
the REAL-column boundary, never a named value the engine could pick up
(TRD §2.5). match_group.confidence and resolution.confidence are the
schema's only non-money REAL columns.
"""

import json
import sqlite3

from plumb.domain.keys import IdSequence


def write_source_file(
    conn: sqlite3.Connection,
    ids: IdSequence,
    *,
    source_id: str,
    path: str,
    sha256: str,
    byte_size: int,
    row_count: int,
    file_format: str,
) -> str:
    source_file_id = ids.next("srcf")
    conn.execute(
        "INSERT INTO source_file (source_file_id, source_id, path, sha256, byte_size, row_count, format) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source_file_id, source_id, path, sha256, byte_size, row_count, file_format),
    )
    return source_file_id


def write_raw_record(
    conn: sqlite3.Connection, raw_id: str, source_file_id: str, line_no: int, raw_payload: dict
) -> None:
    conn.execute(
        "INSERT INTO raw_record (raw_id, source_file_id, line_no, raw_payload_json) VALUES (?, ?, ?, ?)",
        (raw_id, source_file_id, line_no, json.dumps(raw_payload)),
    )


def write_transform_log(
    conn: sqlite3.Connection,
    ids: IdSequence,
    raw_id: str,
    transforms: list[tuple[str, str | None, str | None, str]],
) -> None:
    """transforms: (field, before_text, after_text, rule_id) tuples, in order."""
    for field, before_text, after_text, rule_id in transforms:
        transform_id = ids.next("xfm")
        conn.execute(
            "INSERT INTO transform_log (transform_id, raw_id, field, before_text, after_text, rule_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (transform_id, raw_id, field, before_text, after_text, rule_id),
        )


def write_quarantine(conn: sqlite3.Connection, raw_id: str, reason_code: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO quarantine (raw_id, reason_code, detail) VALUES (?, ?, ?)",
        (raw_id, reason_code, detail),
    )


def write_match_group_row(
    conn: sqlite3.Connection, *, match_id: str, rule_id: str, pass_: str, confidence_bps: int
) -> None:
    """confidence_bps arrives as an int (TRD §2.5 -- no float anywhere in
    the engine's own path); match_group.confidence is REAL in the schema
    and CHECK(confidence > 0 AND confidence <= 1), so the /10000 division
    happens here, right at the DB boundary, as a bare expression rather
    than a named float value the rest of the engine could pick up.

    Takes a pre-assigned match_id -- store/run_writer.py synthesises the
    {group index: match_id} dict before build_units consumes it, then
    writes the rows with those same ids.
    """
    conn.execute(
        "INSERT INTO match_group (match_id, rule_id, pass, confidence) VALUES (?, ?, ?, ?)",
        (match_id, rule_id, pass_, confidence_bps / 10_000),
    )


def write_match_group(conn: sqlite3.Connection, ids: IdSequence, *, rule_id: str, pass_: str, confidence_bps: int) -> str:
    """Generates the match_id and writes the row -- match.engine.persist()'s path."""
    match_id = ids.next("mtch")
    write_match_group_row(conn, match_id=match_id, rule_id=rule_id, pass_=pass_, confidence_bps=confidence_bps)
    return match_id


def write_match_member(conn: sqlite3.Connection, match_id: str, record_key: str, side: str) -> None:
    """ix_member_claimed_once (BACKEND_SCHEMA.md §3.4) enforces "claimed
    exactly once" at the DB level: a record_key already written under a
    different match_id raises sqlite3.IntegrityError here rather than
    silently double-counting. Callers do not need to check this
    themselves -- the constraint is the check."""
    conn.execute(
        "INSERT INTO match_member (match_id, record_key, side) VALUES (?, ?, ?)",
        (match_id, record_key, side),
    )


# --- §3.3 record_index -- the FK hub -------------------------------------------
# Every record_key referenced by a domain table, match_member,
# finding_evidence, exception, resolution_evidence, or
# record_terminal_state must have a row here first.


def write_record_index(
    conn: sqlite3.Connection, record_key: str, entity_type: str, source_id: str, raw_id: str | None = None
) -> None:
    conn.execute(
        "INSERT INTO record_index (record_key, entity_type, source_id, raw_id) VALUES (?, ?, ?, ?)",
        (record_key, entity_type, source_id, raw_id),
    )


def write_order_row(
    conn: sqlite3.Connection,
    *,
    record_key: str,
    seller_id: str,
    gross_paise: int,
    category: str,
    placed_at_utc: str,
    status: str,
    is_interstate: bool,
) -> None:
    """The only canonical detail table the bridge persists: settlement_unit.order_key
    FKs "order". The other detail tables (payment/transfer/...) are not FK'd by
    anything the bridge writes and the scorer never reads them -- deferred to P4's
    close pack (# PRD-DEVIATION noted in store/run_writer.py)."""
    conn.execute(
        'INSERT INTO "order" '
        "(record_key, seller_id, gross_paise, category, placed_at_utc, status, is_interstate) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (record_key, seller_id, gross_paise, category, placed_at_utc, status, int(is_interstate)),
    )


def _insert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))


def write_intent_row(conn, *, record_key, order_key, seller_id, expected_seller_paise,
                     expected_commission_paise, commission_bps_applied, expected_tcs_paise,
                     expected_tds_paise, rate_card_version) -> None:
    _insert(conn, "intent", dict(
        record_key=record_key, order_key=order_key, seller_id=seller_id,
        expected_seller_paise=expected_seller_paise, expected_commission_paise=expected_commission_paise,
        commission_bps_applied=commission_bps_applied, expected_tcs_paise=expected_tcs_paise,
        expected_tds_paise=expected_tds_paise, rate_card_version=rate_card_version,
    ))


def write_payment_row(conn, *, record_key, order_key, amount_paise, method, status,
                      captured_at_utc, fee_paise, tax_paise) -> None:
    _insert(conn, "payment", dict(
        record_key=record_key, order_key=order_key, amount_paise=amount_paise, method=method,
        status=status, captured_at_utc=captured_at_utc, fee_paise=fee_paise, tax_paise=tax_paise,
    ))


def write_refund_row(conn, *, record_key, payment_key, amount_paise, created_at_utc) -> None:
    _insert(conn, "refund", dict(
        record_key=record_key, payment_key=payment_key, amount_paise=amount_paise, created_at_utc=created_at_utc,
    ))


def write_transfer_row(conn, *, record_key, payment_key, linked_account_id, amount_paise,
                       on_hold, on_hold_until_utc, settled_at_utc) -> None:
    _insert(conn, "transfer", dict(
        record_key=record_key, payment_key=payment_key, linked_account_id=linked_account_id,
        amount_paise=amount_paise, on_hold=int(on_hold), on_hold_until_utc=on_hold_until_utc,
        settled_at_utc=settled_at_utc,
    ))


def write_reversal_row(conn, *, record_key, transfer_key, amount_paise, created_at_utc) -> None:
    _insert(conn, "reversal", dict(
        record_key=record_key, transfer_key=transfer_key, amount_paise=amount_paise, created_at_utc=created_at_utc,
    ))


def write_dispute_row(conn, *, record_key, payment_key, amount_paise, status, deducted_amount_paise) -> None:
    _insert(conn, "dispute", dict(
        record_key=record_key, payment_key=payment_key, amount_paise=amount_paise, status=status,
        deducted_amount_paise=deducted_amount_paise,
    ))


def write_settlement_recon_row(conn, *, record_key, entity_key, entity_type, settlement_id, utr,
                               amount_paise, fee_paise, tax_paise, debit_paise, credit_paise,
                               settled_at_utc, dispute_key) -> None:
    _insert(conn, "settlement_recon", dict(
        record_key=record_key, entity_key=entity_key, entity_type=entity_type, settlement_id=settlement_id,
        utr=utr, amount_paise=amount_paise, fee_paise=fee_paise, tax_paise=tax_paise,
        debit_paise=debit_paise, credit_paise=credit_paise, settled_at_utc=settled_at_utc, dispute_key=dispute_key,
    ))


def write_bank_credit_row(conn, *, record_key, bank_ref, utr, amount_paise, credited_on, narration) -> None:
    _insert(conn, "bank_credit", dict(
        record_key=record_key, bank_ref=bank_ref, utr=utr, amount_paise=amount_paise,
        credited_on=credited_on, narration=narration,
    ))


# --- §3.5 verification --------------------------------------------------------


def write_settlement_unit(
    conn: sqlite3.Connection,
    *,
    unit_id: str,
    order_key: str,
    match_id: str | None,
    seller_id: str,
    period: str,
) -> None:
    """unit_id is pre-assigned by verify.unit.build_units (it already
    calls ids.next("unit")) -- the bridge writes it as given, it does not
    re-generate."""
    conn.execute(
        "INSERT INTO settlement_unit (unit_id, order_key, match_id, seller_id, period) VALUES (?, ?, ?, ?, ?)",
        (unit_id, order_key, match_id, seller_id, period),
    )


def write_finding(
    conn: sqlite3.Connection,
    *,
    finding_id: str,
    unit_id: str,
    defect_id: str,
    severity: str,
    amount_at_risk_paise: int,
    on_matched_record: bool,
    conclusion: str,
) -> None:
    """finding_id is pre-assigned by the orchestrator, because
    agent.queue.build_exception_queue needs (finding_id, Finding) pairs
    before L3 runs -- the same id must reach the row here. severity
    arrives as the plain string (Severity.value). finding is append-only
    -- write it in final form."""
    conn.execute(
        "INSERT INTO finding "
        "(finding_id, unit_id, defect_id, severity, amount_at_risk_paise, on_matched_record, conclusion) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (finding_id, unit_id, defect_id, severity, amount_at_risk_paise, int(on_matched_record), conclusion),
    )


def write_recompute_step(
    conn: sqlite3.Connection,
    finding_id: str,
    *,
    step_no: int,
    label: str,
    formula: str,
    inputs: dict,
    output_paise: int,
) -> None:
    conn.execute(
        "INSERT INTO recompute_step (finding_id, step_no, label, formula, inputs_json, output_paise) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (finding_id, step_no, label, formula, json.dumps(inputs, sort_keys=True), output_paise),
    )


def write_finding_evidence(conn: sqlite3.Connection, finding_id: str, record_key: str, role: str) -> None:
    conn.execute(
        "INSERT INTO finding_evidence (finding_id, record_key, role) VALUES (?, ?, ?)",
        (finding_id, record_key, role),
    )


# --- §3.6 exceptions & agent -------------------------------------------------


def write_exception(
    conn: sqlite3.Connection,
    *,
    exception_id: str,
    origin: str,
    record_key: str | None,
    finding_id: str | None,
    amount_at_risk_paise: int,
    queue_rank: int,
) -> None:
    """The paired CHECKs (BACKEND_SCHEMA §3.6) bind record_key to
    origin='UNMATCHED' and finding_id to origin='FINDING' -- the caller
    passes exactly one non-null and the constraint enforces it."""
    conn.execute(
        "INSERT INTO exception "
        "(exception_id, origin, record_key, finding_id, amount_at_risk_paise, queue_rank) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (exception_id, origin, record_key, finding_id, amount_at_risk_paise, queue_rank),
    )


def write_hypothesis(
    conn: sqlite3.Connection,
    ids: IdSequence,
    *,
    exception_id: str,
    rank: int,
    statement: str,
    supports: list[str],
) -> str:
    hypothesis_id = ids.next("hyp")
    conn.execute(
        "INSERT INTO hypothesis (hypothesis_id, exception_id, rank, statement, supports_json) VALUES (?, ?, ?, ?, ?)",
        (hypothesis_id, exception_id, rank, statement, json.dumps(supports)),
    )
    return hypothesis_id


def write_agent_call(
    conn: sqlite3.Connection,
    *,
    call_id: str,
    exception_id: str,
    iteration: int,
    tool: str,
    args: dict,
    result_sha256: str,
    result_row_count: int,
    latency_ms: int,
    tokens_in: int,
    tokens_out: int,
    called_at_utc: str,
) -> None:
    """agent_call.iteration has CHECK(iteration BETWEEN 1 AND 8) -- the loop's
    own 8-iteration cap (loop.py) keeps every row inside that. append-only."""
    conn.execute(
        "INSERT INTO agent_call "
        "(call_id, exception_id, iteration, tool, args_json, result_sha256, result_row_count, "
        " latency_ms, tokens_in, tokens_out, called_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            call_id, exception_id, iteration, tool, json.dumps(args), result_sha256,
            result_row_count, latency_ms, tokens_in, tokens_out, called_at_utc,
        ),
    )


def write_resolution(
    conn: sqlite3.Connection,
    *,
    exception_id: str,
    outcome: str,
    model_claimed_outcome: str,
    was_downgraded: bool,
    downgrade_reason: str | None,
    confidence_bps: int,
    chosen_hypothesis_id: str | None,
    iterations_used: int,
    stop_reason: str,
    what_was_tried: str,
    what_would_resolve_it: str | None,
) -> None:
    """confidence_bps (int, 0..10000) -> resolution.confidence REAL (0..1)
    at this boundary, same as write_match_group. The final CHECK
    (outcome != 'ESCALATED_UNRESOLVED' OR what_would_resolve_it IS NOT NULL)
    turns a malformed escalation into an insert failure. append-only."""
    conn.execute(
        "INSERT INTO resolution "
        "(exception_id, outcome, model_claimed_outcome, was_downgraded, downgrade_reason, confidence, "
        " chosen_hypothesis_id, iterations_used, stop_reason, what_was_tried, what_would_resolve_it) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            exception_id, outcome, model_claimed_outcome, int(was_downgraded), downgrade_reason,
            confidence_bps / 10_000, chosen_hypothesis_id, iterations_used, stop_reason,
            what_was_tried, what_would_resolve_it,
        ),
    )


def write_resolution_evidence(conn: sqlite3.Connection, exception_id: str, record_key: str, role: str) -> None:
    conn.execute(
        "INSERT INTO resolution_evidence (exception_id, record_key, role) VALUES (?, ?, ?)",
        (exception_id, record_key, role),
    )


# --- §3.7 terminal states & §3.1 provenance ---------------------------------


def write_record_terminal_state(conn: sqlite3.Connection, record_key: str, terminal_state: str) -> None:
    """One row per record_index key -- v_conservation asserts the counts
    match. append-only."""
    conn.execute(
        "INSERT INTO record_terminal_state (record_key, terminal_state) VALUES (?, ?)",
        (record_key, terminal_state),
    )


def write_run_row(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    plumb_version: str,
    git_sha: str,
    git_dirty: bool,
    batch_id: str,
    generator_seed: int,
    generator_config_sha256: str,
    engine_config_sha256: str,
    schema_sha256: str,
    tolerance_profile: str,
    rules_module_version: str,
    ablation_config: str,
    sample_label: str,
    llm_model: str | None,
    started_at_utc: str,
    finished_at_utc: str | None,
    llm_temperature=None,  # unannotated on purpose: the no-float lint (TRD §2.5) covers store/,
    #                        and this is model.TEMPERATURE (0.0) for hybrid or None for rules_only --
    #                        run.llm_temperature is REAL, one of the schema's 3 non-money REAL columns.
) -> None:
    conn.execute(
        "INSERT INTO run "
        "(run_id, plumb_version, git_sha, git_dirty, batch_id, generator_seed, generator_config_sha256, "
        " engine_config_sha256, schema_sha256, tolerance_profile, rules_module_version, ablation_config, "
        " sample_label, llm_model, llm_temperature, started_at_utc, finished_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id, plumb_version, git_sha, int(git_dirty), batch_id, generator_seed,
            generator_config_sha256, engine_config_sha256, schema_sha256, tolerance_profile,
            rules_module_version, ablation_config, sample_label, llm_model, llm_temperature,
            started_at_utc, finished_at_utc,
        ),
    )


def write_config_snapshot(conn: sqlite3.Connection, key: str, value: object) -> None:
    """value is JSON-serialised here; config_snapshot.value_json has
    CHECK(json_valid(value_json))."""
    conn.execute(
        "INSERT INTO config_snapshot (key, value_json) VALUES (?, ?)",
        (key, json.dumps(value, sort_keys=True)),
    )
