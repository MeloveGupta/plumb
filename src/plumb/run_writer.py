"""The L3 persistence bridge: one function that takes a run's fully
computed in-memory L0-L3 results and writes every run.sqlite row in
FK-safe order.

Lives at `plumb/` top level, next to `stub_engine.py`, not under
`store/`: it is the orchestrator, above every layer, so it may import
match/verify/agent freely and unpack their `SettlementUnit` / `Finding`
/ `Exception_` / `Resolution` / `InvestigationState` into the
plain-argument writers in `store/writer.py`. `store/` itself never
depends on a layer.

Nothing here recomputes anything. ingest already wrote its provenance
chain into the same connection; match / verify / agent already ran in
memory. This is the write-down, in the order the foreign keys demand:

    run -> config_snapshot -> record_index -> "order" -> match_group /
    match_member -> settlement_unit -> finding (+ recompute_step +
    finding_evidence) -> exception -> hypothesis -> resolution (+
    resolution_evidence + agent_call) -> record_terminal_state

The six append-only tables (finding, resolution, agent_call,
match_group, match_member, record_terminal_state) are written once, in
final form -- no UPDATE pass exists.

# PRD-DEVIATION: of the canonical detail tables (payment, transfer,
# refund, ...) only "order" is persisted -- settlement_unit.order_key
# FKs it. Nothing the bridge writes FKs the others and the scorer never
# reads them (plumb_eval/run_reader.py). The full close-pack detail
# tables are P4 work.
"""

import sqlite3

from plumb.agent.queue import Exception_
from plumb.agent.schema import Resolution
from plumb.domain.keys import IdSequence
from plumb.domain.models import (
    BankCredit,
    Dispute,
    Intent,
    Order,
    OrderLine,
    Payment,
    Refund,
    Reversal,
    Seller,
    SellerRateCard,
    SettlementRecon,
    Transfer,
)
from plumb.match.engine import MatchResult
from plumb.store.writer import (
    write_agent_call,
    write_config_snapshot,
    write_exception,
    write_finding,
    write_finding_evidence,
    write_hypothesis,
    write_match_group_row,
    write_match_member,
    write_bank_credit_row,
    write_dispute_row,
    write_intent_row,
    write_order_row,
    write_payment_row,
    write_refund_row,
    write_reversal_row,
    write_settlement_recon_row,
    write_transfer_row,
    write_recompute_step,
    write_record_index,
    write_record_terminal_state,
    write_resolution,
    write_resolution_evidence,
    write_run_row,
    write_settlement_unit,
)

_KEY_FIELD: dict[type, str] = {
    Order: "order_id",
    OrderLine: "line_id",
    Intent: "intent_id",
    Payment: "payment_id",
    Refund: "refund_id",
    Transfer: "transfer_id",
    Reversal: "reversal_id",
    Dispute: "dispute_id",
    SettlementRecon: "settlement_recon_id",
    BankCredit: "bank_credit_id",
    SellerRateCard: "rate_card_id",
    Seller: "seller_id",
}

_SIDES = ("intent", "razorpay", "bank", "sellers")

_TERMINAL_RANK = {
    "VERIFIED_CLEAN": 0,
    "AUTO_RESOLVED": 1,
    "PROPOSED": 2,
    "ESCALATED_UNRESOLVED": 3,
}


def _canonical_records(ingest_result: dict) -> list[tuple[object, str]]:
    """(record, source_id) for every normalised canonical record, fixed
    side order -- never dict iteration (rule 7)."""
    out: list[tuple[object, str]] = []
    for side in _SIDES:
        for record in ingest_result[side]["records"]:
            out.append((record, side))
    return out


def _record_key(record: object) -> str:
    return getattr(record, _KEY_FIELD[type(record)])


def _entity_type(record: object) -> str:
    return type(record).__name__


def write_full_run(
    conn: sqlite3.Connection,
    ids: IdSequence,
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
    llm_temperature,
    started_at_utc: str,
    finished_at_utc: str | None,
    config_snapshot: dict,
    ingest_result: dict,
    match_result: MatchResult,
    match_ids: dict[int, str],
    units: list,
    findings_with_ids: list,
    resolved: list[tuple[Exception_, Resolution, object]],
) -> None:
    write_run_row(
        conn,
        run_id=run_id,
        plumb_version=plumb_version,
        git_sha=git_sha,
        git_dirty=git_dirty,
        batch_id=batch_id,
        generator_seed=generator_seed,
        generator_config_sha256=generator_config_sha256,
        engine_config_sha256=engine_config_sha256,
        schema_sha256=schema_sha256,
        tolerance_profile=tolerance_profile,
        rules_module_version=rules_module_version,
        ablation_config=ablation_config,
        sample_label=sample_label,
        llm_model=llm_model,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        llm_temperature=llm_temperature,
    )

    for key, value in config_snapshot.items():
        write_config_snapshot(conn, key, value)

    # -- record_index: the FK hub. Every canonical key, before anything references it.
    canonical = _canonical_records(ingest_result)
    all_keys: list[str] = []
    for record, source_id in canonical:
        key = _record_key(record)
        all_keys.append(key)
        write_record_index(conn, key, _entity_type(record), source_id)

    # -- canonical detail tables, in FK order (order -> intent/payment ->
    #    refund/transfer/dispute -> reversal -> settlement_recon -> bank_credit).
    #    The report pack (close.md waterfall) reads these; the scorer does not.
    by_type: dict[type, list] = {}
    for record, _side in canonical:
        by_type.setdefault(type(record), []).append(record)

    for o in by_type.get(Order, []):
        write_order_row(
            conn, record_key=o.order_id, seller_id=o.seller_id, gross_paise=o.gross_paise,
            category=o.category, placed_at_utc=o.placed_at_utc, status=o.status, is_interstate=o.is_interstate,
        )
    for it in by_type.get(Intent, []):
        write_intent_row(
            conn, record_key=it.intent_id, order_key=it.order_id, seller_id=it.seller_id,
            expected_seller_paise=it.expected_seller_amount_paise,
            expected_commission_paise=it.expected_commission_paise,
            commission_bps_applied=it.commission_rate_applied_bps,
            expected_tcs_paise=it.expected_tcs_paise, expected_tds_paise=it.expected_tds_paise,
            rate_card_version=it.rate_card_version,
        )
    for p in by_type.get(Payment, []):
        write_payment_row(
            conn, record_key=p.payment_id, order_key=p.order_id, amount_paise=p.amount_paise,
            method=p.method, status=p.status, captured_at_utc=p.captured_at_utc,
            fee_paise=p.fee_paise, tax_paise=p.tax_paise,
        )
    for r in by_type.get(Refund, []):
        write_refund_row(conn, record_key=r.refund_id, payment_key=r.payment_id,
                         amount_paise=r.amount_paise, created_at_utc=r.created_at_utc)
    for t in by_type.get(Transfer, []):
        write_transfer_row(
            conn, record_key=t.transfer_id, payment_key=t.payment_id, linked_account_id=t.linked_account_id,
            amount_paise=t.amount_paise, on_hold=t.on_hold, on_hold_until_utc=t.on_hold_until_utc,
            settled_at_utc=t.settled_at_utc,
        )
    for d in by_type.get(Dispute, []):
        write_dispute_row(conn, record_key=d.dispute_id, payment_key=d.payment_id, amount_paise=d.amount_paise,
                          status=d.status, deducted_amount_paise=d.deducted_amount_paise)
    for rv in by_type.get(Reversal, []):
        write_reversal_row(conn, record_key=rv.reversal_id, transfer_key=rv.transfer_id,
                           amount_paise=rv.amount_paise, created_at_utc=rv.created_at_utc)
    for sr in by_type.get(SettlementRecon, []):
        write_settlement_recon_row(
            conn, record_key=sr.settlement_recon_id, entity_key=sr.entity_key, entity_type=sr.entity_type,
            settlement_id=sr.settlement_id, utr=sr.utr, amount_paise=sr.amount_paise, fee_paise=sr.fee_paise,
            tax_paise=sr.tax_paise, debit_paise=sr.debit_paise, credit_paise=sr.credit_paise,
            settled_at_utc=sr.settled_at_utc, dispute_key=sr.dispute_key,
        )
    for bc in by_type.get(BankCredit, []):
        write_bank_credit_row(conn, record_key=bc.bank_credit_id, bank_ref=bc.bank_ref, utr=bc.utr,
                              amount_paise=bc.amount_paise, credited_on=bc.credited_on, narration=bc.narration)

    # -- match_group / match_member (settlement_unit.match_id FKs match_group)
    for index, group in enumerate(match_result.groups):
        match_id = match_ids[index]
        write_match_group_row(
            conn, match_id=match_id, rule_id=group.rule_id, pass_=group.pass_, confidence_bps=group.confidence_bps
        )
        for record_key, side in group.members:
            write_match_member(conn, match_id, record_key, side)

    # -- settlement_unit (unit_id already assigned by build_units)
    for unit in units:
        write_settlement_unit(
            conn,
            unit_id=unit.unit_id,
            order_key=unit.order.order_id,
            match_id=unit.match_id,
            seller_id=unit.order.seller_id,
            period=unit.order.placed_at_utc[:7],  # YYYY-MM; verify's SettlementUnit carries no period
        )

    # -- finding (+ recompute_step + finding_evidence)
    for finding_id, finding in findings_with_ids:
        write_finding(
            conn,
            finding_id=finding_id,
            unit_id=finding.unit_id,
            defect_id=finding.defect_id,
            severity=finding.severity.value,
            amount_at_risk_paise=finding.amount_at_risk_paise,
            on_matched_record=finding.on_matched_record,
            conclusion=finding.conclusion,
        )
        for step in finding.trace.steps:
            write_recompute_step(
                conn,
                finding_id,
                step_no=step.step_no,
                label=step.label,
                formula=step.formula,
                inputs=step.inputs,
                output_paise=step.output_paise,
            )
        seen_evidence: set[tuple[str, str]] = set()
        for ref in finding.evidence:
            if (ref.record_key, ref.role) not in seen_evidence:
                seen_evidence.add((ref.record_key, ref.role))
                write_finding_evidence(conn, finding_id, ref.record_key, ref.role)

    # -- exception rows (all of them, before any resolution FK)
    for exc, _resolution, _state in resolved:
        write_exception(
            conn,
            exception_id=exc.exception_id,
            origin=exc.origin,
            record_key=exc.record_key,
            finding_id=exc.finding_id,
            amount_at_risk_paise=exc.amount_at_risk_paise,
            queue_rank=exc.queue_rank,
        )

    # -- per exception: hypotheses -> resolution -> resolution_evidence -> agent_call
    unit_order_key = {u.unit_id: u.order.order_id for u in units}
    finding_unit = {fid: f.unit_id for fid, f in findings_with_ids}
    terminal: dict[str, str] = {key: "VERIFIED_CLEAN" for key in all_keys}

    for exc, resolution, state in resolved:
        hyp_ids: list[str] = []
        for hypothesis in resolution.hypotheses:
            hyp_ids.append(
                write_hypothesis(
                    conn,
                    ids,
                    exception_id=exc.exception_id,
                    rank=hypothesis.rank,
                    statement=hypothesis.statement,
                    supports=list(hypothesis.supports),
                )
            )
        chosen_id = (
            hyp_ids[resolution.chosen_hypothesis_index]
            if resolution.chosen_hypothesis_index is not None
            else None
        )
        write_resolution(
            conn,
            exception_id=exc.exception_id,
            outcome=resolution.outcome,
            model_claimed_outcome=resolution.model_claimed_outcome or resolution.outcome,
            was_downgraded=resolution.was_downgraded,
            downgrade_reason=resolution.downgrade_reason,
            confidence_bps=resolution.confidence_bps,
            chosen_hypothesis_id=chosen_id,
            iterations_used=resolution.iterations_used,
            stop_reason=resolution.stop_reason.value,
            what_was_tried=resolution.what_was_tried,
            what_would_resolve_it=resolution.what_would_resolve_it,
        )
        seen_ev: set[tuple[str, str]] = set()
        for ref in resolution.evidence_chain:
            if (ref.record_key, ref.role) not in seen_ev:
                seen_ev.add((ref.record_key, ref.role))
                write_resolution_evidence(conn, exc.exception_id, ref.record_key, ref.role)
        if state is not None:
            for call in state.agent_calls:
                write_agent_call(
                    conn,
                    call_id=call.call_id,
                    exception_id=exc.exception_id,
                    iteration=call.iteration,
                    tool=call.tool,
                    args=call.args,
                    result_sha256=call.result_sha256,
                    result_row_count=call.result_row_count,
                    latency_ms=call.latency_ms,
                    tokens_in=call.tokens_in,
                    tokens_out=call.tokens_out,
                    called_at_utc=call.called_at_utc,
                )

        # terminal state: the exception's subject record(s) take the outcome,
        # worst-outcome-wins if a record is touched by more than one exception.
        subject_keys: list[str] = []
        if exc.origin == "UNMATCHED" and exc.record_key is not None:
            subject_keys.append(exc.record_key)
        elif exc.origin == "FINDING" and exc.finding_id is not None:
            order_key = unit_order_key.get(finding_unit.get(exc.finding_id, ""), None)
            if order_key is not None:
                subject_keys.append(order_key)
        for key in subject_keys:
            if key in terminal and _TERMINAL_RANK[resolution.outcome] > _TERMINAL_RANK[terminal[key]]:
                terminal[key] = resolution.outcome

    # -- record_terminal_state: one row per record_index key (v_conservation)
    for key in all_keys:
        write_record_terminal_state(conn, key, terminal[key])

    conn.commit()
