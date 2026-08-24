"""LLD §8 -- silent-error attribution, transcribed from the given
pseudocode:

    def score_match(group, truth, findings_by_unit, exceptions_by_record):
        members  = {m.record_key for m in group.members}
        expected = truth.counterpart_closure(group.anchor_key)
        if members == expected:
            return ScoredMatch(group.match_id, TRUE_POSITIVE, silent=0)
        flagged = (bool(findings_by_unit.get(group.unit_id))
                   or any(k in exceptions_by_record for k in members))
        return ScoredMatch(group.match_id, FALSE_POSITIVE, silent=0 if flagged else 1)

Two adaptations to the real schema (LLD's MatchGroup is a hypothetical
future matcher type, not run.sql's actual match_group table):

- No anchor_key column exists. TruthStore.counterpart_closure accepts
  any closure member (see truth_store.py's docstring), so the
  lexicographically-first member record_key is used to seed the
  lookup -- deterministic (rule 7), and correctness doesn't depend on
  which member seeds it: either the members set equals the closure or
  it doesn't, regardless of which key found that closure.
- No unit_id column on match_group either -- settlement_unit.match_id
  points the other way. unit_ids_for_match is looked up by the caller
  and passed in.

TRD §8.3's fabrication rule ("a key in engine output absent from the
dataset fails the run") is checked once, up front, across every
record_key run.sqlite references -- not per match_group -- so a
fabricated key anywhere aborts scoring before any metric is computed,
rather than being silently absorbed into whichever match_group happens
to reference it last.
"""

from dataclasses import dataclass

from plumb_eval.errors import TruthJoinError
from plumb_eval.run_reader import Finding, MatchGroup, RunData
from plumb_eval.truth_store import TruthStore

TRUE_POSITIVE = "TRUE_POSITIVE"
FALSE_POSITIVE = "FALSE_POSITIVE"


@dataclass(frozen=True)
class ScoredMatch:
    match_id: str
    verdict: str
    silent: bool


@dataclass(frozen=True)
class ScoredDefect:
    instance_id: str
    was_detected: bool
    detected_finding_id: str | None
    class_correct: bool | None


@dataclass(frozen=True)
class ScoredAbstention:
    exception_id: str
    verdict: str


def validate_no_fabrication(run: RunData, truth: TruthStore) -> None:
    referenced_keys: set[str] = set()
    for group in run.match_groups:
        referenced_keys.update(group.members)
    for finding in run.findings:
        referenced_keys.update(finding.evidence_keys)
    for exc in run.exceptions:
        if exc.record_key is not None:
            referenced_keys.add(exc.record_key)

    for key in sorted(referenced_keys):
        truth.counterpart_closure(key)  # raises TruthJoinError on the first offender


def score_match(
    group: MatchGroup,
    unit_ids_for_match: list[str],
    truth: TruthStore,
    findings_by_unit: dict[str, list[Finding]],
    exceptions_by_record: dict[str, str],
) -> ScoredMatch:
    members = set(group.members)
    if not members:
        raise ValueError(f"match_group {group.match_id!r} has no members")

    anchor_key = sorted(members)[0]
    expected = truth.counterpart_closure(anchor_key)

    if members == expected:
        return ScoredMatch(group.match_id, TRUE_POSITIVE, silent=False)

    flagged = any(findings_by_unit.get(unit_id) for unit_id in unit_ids_for_match) or any(
        key in exceptions_by_record for key in members
    )
    return ScoredMatch(group.match_id, FALSE_POSITIVE, silent=not flagged)


def score_all_matches(run: RunData, truth: TruthStore) -> list[ScoredMatch]:
    units_by_match: dict[str, list[str]] = {}
    for unit in run.settlement_units:
        if unit.match_id is not None:
            units_by_match.setdefault(unit.match_id, []).append(unit.unit_id)

    findings_by_unit: dict[str, list[Finding]] = {}
    for finding in run.findings:
        findings_by_unit.setdefault(finding.unit_id, []).append(finding)

    exceptions_by_record: dict[str, str] = {}
    finding_by_id = {f.finding_id: f for f in run.findings}
    for exc in run.exceptions:
        if exc.origin == "UNMATCHED" and exc.record_key is not None:
            exceptions_by_record[exc.record_key] = exc.exception_id
        elif exc.origin == "FINDING" and exc.finding_id is not None:
            finding = finding_by_id.get(exc.finding_id)
            if finding is not None:
                for key in finding.evidence_keys:
                    exceptions_by_record[key] = exc.exception_id

    return [
        score_match(group, units_by_match.get(group.match_id, []), truth, findings_by_unit, exceptions_by_record)
        for group in run.match_groups  # already ORDER BY match_id from run_reader
    ]


def score_defects(run: RunData, truth: TruthStore) -> tuple[list[ScoredDefect], set[str]]:
    """Returns (per-instance verdicts, finding_ids that are true positives).

    A finding is a "detection" of a given injected defect only if it
    lives on that defect's order (via settlement_unit.order_key). Among
    candidate findings on that order, one whose defect_id matches the
    injected class is preferred; otherwise the lexicographically-first
    finding_id is picked (deterministic, not "some finding was raised
    on this order, of unspecified relevance").
    """
    order_key_by_unit = {u.unit_id: u.order_key for u in run.settlement_units}
    findings_by_order: dict[str, list[Finding]] = {}
    for finding in run.findings:
        order_key = order_key_by_unit.get(finding.unit_id)
        if order_key is not None:
            findings_by_order.setdefault(order_key, []).append(finding)

    scored: list[ScoredDefect] = []
    true_positive_finding_ids: set[str] = set()

    for defect in sorted(truth.all_defects(), key=lambda d: d["instance_id"]):
        candidates = sorted(findings_by_order.get(defect["record_key"], []), key=lambda f: f.finding_id)
        if not candidates:
            scored.append(ScoredDefect(defect["instance_id"], was_detected=False, detected_finding_id=None, class_correct=None))
            continue

        matching = [f for f in candidates if f.defect_id == defect["defect_class"]]
        picked = matching[0] if matching else candidates[0]
        class_correct = picked.defect_id == defect["defect_class"]
        if class_correct:
            true_positive_finding_ids.add(picked.finding_id)
        scored.append(
            ScoredDefect(defect["instance_id"], was_detected=True, detected_finding_id=picked.finding_id, class_correct=class_correct)
        )

    return scored, true_positive_finding_ids


def score_abstentions(run: RunData, truth: TruthStore) -> list[ScoredAbstention]:
    """PRD §7.7 only needs the ESCALATED_UNRESOLVED-vs-not split
    (CORRECT_ABSTENTION / OVER_ABSTENTION). CORRECT_RESOLUTION /
    WRONG_RESOLUTION -- grading whether an AUTO_RESOLVED/PROPOSED
    resolution's numbers were right -- would need a proposed-correction
    amount to compare against true_obligation, and resolution carries
    none; out of scope this session (see plan design decision #4), not
    silently approximated.
    """
    order_key_by_unit = {u.unit_id: u.order_key for u in run.settlement_units}
    unit_by_finding = {f.finding_id: f.unit_id for f in run.findings}
    exception_by_id = {e.exception_id: e for e in run.exceptions}

    scored: list[ScoredAbstention] = []
    for resolution in run.resolutions:  # already ORDER BY exception_id
        if resolution.outcome != "ESCALATED_UNRESOLVED":
            continue
        exc = exception_by_id.get(resolution.exception_id)
        if exc is None:
            continue

        if exc.origin == "FINDING":
            unit_id = unit_by_finding.get(exc.finding_id)
            order_key = order_key_by_unit.get(unit_id) if unit_id else None
        else:
            order_key = truth.order_key_for(exc.record_key)

        if order_key is None:
            continue

        resolvable = truth.is_resolvable(order_key)
        verdict = "OVER_ABSTENTION" if resolvable else "CORRECT_ABSTENTION"
        scored.append(ScoredAbstention(resolution.exception_id, verdict))

    return scored
