"""PRD §7 -- all nine metric families, implemented exactly as written
there. Every ratio's zero-denominator case is `None` (written to
eval.sqlite as NOT_MEASURED, never 0.0 -- a 0.0 reads as a measured
result, and 0/0 isn't one). A SUM over an empty set is a legitimate 0,
not NOT_MEASURED -- summing nothing is well-defined, dividing by
nothing isn't.

"Record" granularity for §7.1-7.4 (design decision #1 in the plan):
truth_record.record_key is the order; true_counterparts are the
matchable legs (payment/transfer/settlement_recon/bank_credit). One
canonical `correct_auto_matches` count (TRUE_POSITIVE verdicts) is
reused verbatim as the numerator PRD writes it in both 7.2 and 7.3 --
valid because a TRUE_POSITIVE match_group corresponds 1:1 to one
correctly-reconstructed order closure.
"""

from dataclasses import dataclass
from datetime import datetime

from plumb_eval.run_reader import RunData
from plumb_eval.scoring import ScoredAbstention, ScoredDefect, ScoredMatch
from plumb_eval.truth_store import TruthStore

NOT_MEASURED = "NOT_MEASURED"


@dataclass(frozen=True)
class Metric:
    name: str
    unit: str  # 'ratio' | 'paise' | 'count' | 'seconds' | 'tokens'
    value: float | int | None  # None -> NOT_MEASURED


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _auto_matched_order_keys(run: RunData, truth: TruthStore) -> set[str]:
    """An order is "auto-matched" (7.1) if every one of its legs was
    claimed under exactly one shared match_id -- correctness-agnostic,
    just "did the engine make one grouping decision covering it."
    """
    leg_match_id: dict[str, str] = {}
    for group in run.match_groups:
        for key in group.members:
            leg_match_id[key] = group.match_id

    matched: set[str] = set()
    for order_key in truth.order_keys():
        legs = truth.counterpart_closure(order_key)
        if not legs:
            continue
        match_ids = {leg_match_id.get(leg) for leg in legs}
        if len(match_ids) == 1 and None not in match_ids:
            matched.add(order_key)
    return matched


def _wall_clock_seconds(run: RunData) -> float | None:
    if run.started_at_utc is None or run.finished_at_utc is None:
        return None
    start = datetime.fromisoformat(run.started_at_utc.replace("Z", "+00:00"))
    end = datetime.fromisoformat(run.finished_at_utc.replace("Z", "+00:00"))
    return (end - start).total_seconds()


def compute_determinism_score(
    observations: list[tuple[int, str, str]], total_records: int
) -> float | None:
    """PRD §7.9: records_identical_across_all_5_runs / total_records.
    Needs >=2 distinct run_index values to mean anything -- a single
    scored run writes zero determinism_observation rows (that harness
    is P1.10, not this session), so this returns None (NOT_MEASURED)
    from a lone `plumb-eval` invocation, satisfying "the metric row
    still exists" without fabricating a number for data that doesn't
    exist yet.
    """
    if not observations:
        return None
    hashes_by_record: dict[str, set[str]] = {}
    run_indices: set[int] = set()
    for run_index, record_key, resolution_hash in observations:
        hashes_by_record.setdefault(record_key, set()).add(resolution_hash)
        run_indices.add(run_index)
    if len(run_indices) < 2:
        return None
    identical = sum(1 for hashes in hashes_by_record.values() if len(hashes) == 1)
    return _ratio(identical, total_records)


def compute_metrics(
    run: RunData,
    truth: TruthStore,
    scored_matches: list[ScoredMatch],
    scored_defects: list[ScoredDefect],
    true_positive_finding_ids: set[str],
    scored_abstentions: list[ScoredAbstention],
    determinism_observations: list[tuple[int, str, str]] | None = None,
) -> list[Metric]:
    order_keys = truth.order_keys()
    total_records = len(order_keys)

    # 7.1 auto-match rate
    auto_matched_records = len(_auto_matched_order_keys(run, truth))
    auto_match_rate = _ratio(auto_matched_records, total_records)

    # 7.2 / 7.3 match precision / recall
    total_auto_matches = len(scored_matches)
    correct_auto_matches = sum(1 for m in scored_matches if m.verdict == "TRUE_POSITIVE")
    match_precision = _ratio(correct_auto_matches, total_auto_matches)

    records_having_a_true_match = sum(1 for k in order_keys if len(truth.counterpart_closure(k)) >= 1)
    match_recall = _ratio(correct_auto_matches, records_having_a_true_match)

    # 7.4 silent-error rate -- the headline metric
    silent_count = sum(1 for m in scored_matches if m.verdict == "FALSE_POSITIVE" and m.silent)
    silent_error_rate = _ratio(silent_count, total_auto_matches)

    # 7.5 defect detection
    all_defects = truth.all_defects()
    defects_injected = len(all_defects)
    defects_detected = sum(1 for d in scored_defects if d.was_detected)
    defect_recall = _ratio(defects_detected, defects_injected)

    total_flags = len(run.findings)
    defect_precision = _ratio(len(true_positive_finding_ids), total_flags)

    correctly_classified = sum(1 for d in scored_defects if d.class_correct)
    root_cause_accuracy = _ratio(correctly_classified, defects_detected)

    # 7.6 money
    class_correct_by_instance = {d.instance_id: d.class_correct for d in scored_defects}
    detected_by_instance = {d.instance_id: d.was_detected for d in scored_defects}
    leakage_caught_paise = sum(
        d["amount_at_risk_paise"] for d in all_defects if class_correct_by_instance.get(d["instance_id"])
    )
    leakage_missed_paise = sum(
        d["amount_at_risk_paise"] for d in all_defects if not detected_by_instance.get(d["instance_id"], False)
    )
    false_alarm_paise = sum(
        f.amount_at_risk_paise for f in run.findings if f.finding_id not in true_positive_finding_ids
    )

    # 7.7 abstention quality
    total_unresolvable = sum(1 for k in order_keys if not truth.is_resolvable(k))
    total_resolvable = sum(1 for k in order_keys if truth.is_resolvable(k))
    correctly_escalated_unresolvable = sum(1 for a in scored_abstentions if a.verdict == "CORRECT_ABSTENTION")
    escalated_but_resolvable = sum(1 for a in scored_abstentions if a.verdict == "OVER_ABSTENTION")
    correct_abstention_rate = _ratio(correctly_escalated_unresolvable, total_unresolvable)
    over_abstention_rate = _ratio(escalated_but_resolvable, total_resolvable)

    # 7.8 throughput
    wall_clock_seconds_total = _wall_clock_seconds(run)
    records_per_second = (
        total_records / wall_clock_seconds_total
        if wall_clock_seconds_total and wall_clock_seconds_total > 0
        else None
    )
    llm_tokens_per_1000_records = (
        (run.agent_call_tokens_total / total_records) * 1000 if total_records > 0 else None
    )
    # No sourced INR-per-token rate exists anywhere in PRD/TRD/LLD (checked).
    # Rule 4: never fabricate a number -- NOT_MEASURED unconditionally until
    # a real, cited rate exists, not a plausible-looking constant.
    inr_cost_per_1000_records = None

    # 7.9 determinism
    determinism_score = compute_determinism_score(determinism_observations or [], total_records)

    # L3 outcome mix (PRD §9 -- the ablation's residual-resolution comparison).
    # residual_resolution_rate is the GATE P3 supporting number: the share of
    # exceptions L3 moved off ESCALATED_UNRESOLVED. It is 0 for rules_only by
    # construction. It does NOT gate -- a PROPOSED resolution's correctness is
    # not scored (no proposed-correction amount in the schema) -- over_abstention_rate
    # is the gating metric.
    outcomes = [r.outcome for r in run.resolutions]
    exceptions_total = len(run.exceptions)
    n_auto = outcomes.count("AUTO_RESOLVED")
    n_proposed = outcomes.count("PROPOSED")
    n_escalated = outcomes.count("ESCALATED_UNRESOLVED")
    residual_resolution_rate = _ratio(n_auto + n_proposed, len(outcomes))
    escalated_unresolved_rate = _ratio(n_escalated, len(outcomes))

    return [
        Metric("auto_match_rate", "ratio", auto_match_rate),
        Metric("match_precision", "ratio", match_precision),
        Metric("match_recall", "ratio", match_recall),
        Metric("silent_error_rate", "ratio", silent_error_rate),
        Metric("defect_recall", "ratio", defect_recall),
        Metric("defect_precision", "ratio", defect_precision),
        Metric("root_cause_accuracy", "ratio", root_cause_accuracy),
        Metric("leakage_caught_inr", "paise", leakage_caught_paise),
        Metric("leakage_missed_inr", "paise", leakage_missed_paise),
        Metric("false_alarm_inr", "paise", false_alarm_paise),
        Metric("correct_abstention_rate", "ratio", correct_abstention_rate),
        Metric("over_abstention_rate", "ratio", over_abstention_rate),
        Metric("records_per_second", "count", records_per_second),
        Metric("wall_clock_seconds_total", "seconds", wall_clock_seconds_total),
        Metric("llm_tokens_per_1000_records", "tokens", llm_tokens_per_1000_records),
        Metric("inr_cost_per_1000_records", "paise", inr_cost_per_1000_records),
        Metric("determinism_score", "ratio", determinism_score),
        Metric("residual_resolution_rate", "ratio", residual_resolution_rate),
        Metric("escalated_unresolved_rate", "ratio", escalated_unresolved_rate),
        Metric("exceptions_total", "count", exceptions_total),
        Metric("auto_resolved_count", "count", n_auto),
        Metric("proposed_count", "count", n_proposed),
        Metric("escalated_unresolved_count", "count", n_escalated),
    ]
