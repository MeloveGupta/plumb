"""plumb.store.ddl.open_existing_run_db is the engine's own sanctioned
way to reopen run.sqlite, but it lives at plumb.store, not plumb.domain
-- TRD §3.1 only allows plumb_eval to import plumb.domain and plumb_gen,
so it isn't reachable. This duplicates the same 2-line PRAGMA-only
connect rather than importing it, same reasoning as plumb_gen/rates.py's
deliberate duplication of TDS_BPS/TCS_BPS across the same boundary.

Everything below reads run.sqlite once into plain dataclasses so
scoring.py and metrics.py work on data, not live cursors.
"""

import sqlite3
from dataclasses import dataclass, field


def open_run_db_readonly(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@dataclass(frozen=True)
class MatchGroup:
    match_id: str
    rule_id: str
    pass_: str
    members: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    finding_id: str
    unit_id: str
    defect_id: str
    severity: str
    amount_at_risk_paise: int
    on_matched_record: bool
    conclusion: str
    evidence_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SettlementUnit:
    unit_id: str
    order_key: str
    match_id: str | None
    seller_id: str
    period: str


@dataclass(frozen=True)
class ExceptionRow:
    exception_id: str
    origin: str
    record_key: str | None
    finding_id: str | None
    amount_at_risk_paise: int
    queue_rank: int


@dataclass(frozen=True)
class ResolutionRow:
    exception_id: str
    outcome: str
    stop_reason: str


@dataclass(frozen=True)
class RunData:
    run_id: str
    started_at_utc: str
    finished_at_utc: str | None
    match_groups: list[MatchGroup]
    settlement_units: list[SettlementUnit]
    findings: list[Finding]
    exceptions: list[ExceptionRow]
    resolutions: list[ResolutionRow]
    agent_call_tokens_total: int
    agent_call_count: int

    @classmethod
    def from_db(cls, conn: sqlite3.Connection) -> "RunData":
        run_row = conn.execute(
            "SELECT run_id, started_at_utc, finished_at_utc FROM run"
        ).fetchone()
        run_id, started_at_utc, finished_at_utc = run_row if run_row else (None, None, None)

        members_by_match: dict[str, list[str]] = {}
        for match_id, record_key in conn.execute(
            "SELECT match_id, record_key FROM match_member ORDER BY match_id, record_key"
        ).fetchall():
            members_by_match.setdefault(match_id, []).append(record_key)

        match_groups = [
            MatchGroup(match_id, rule_id, pass_, members_by_match.get(match_id, []))
            for match_id, rule_id, pass_ in conn.execute(
                "SELECT match_id, rule_id, pass FROM match_group ORDER BY match_id"
            ).fetchall()
        ]

        settlement_units = [
            SettlementUnit(unit_id, order_key, match_id, seller_id, period)
            for unit_id, order_key, match_id, seller_id, period in conn.execute(
                "SELECT unit_id, order_key, match_id, seller_id, period FROM settlement_unit ORDER BY unit_id"
            ).fetchall()
        ]

        evidence_by_finding: dict[str, list[str]] = {}
        for finding_id, record_key in conn.execute(
            "SELECT finding_id, record_key FROM finding_evidence ORDER BY finding_id, record_key"
        ).fetchall():
            evidence_by_finding.setdefault(finding_id, []).append(record_key)

        findings = [
            Finding(
                finding_id, unit_id, defect_id, severity, amount_at_risk_paise,
                bool(on_matched_record), conclusion, evidence_by_finding.get(finding_id, []),
            )
            for (
                finding_id, unit_id, defect_id, severity, amount_at_risk_paise,
                on_matched_record, conclusion,
            ) in conn.execute(
                "SELECT finding_id, unit_id, defect_id, severity, amount_at_risk_paise, "
                "on_matched_record, conclusion FROM finding ORDER BY finding_id"
            ).fetchall()
        ]

        exceptions = [
            ExceptionRow(exception_id, origin, record_key, finding_id, amount_at_risk_paise, queue_rank)
            for exception_id, origin, record_key, finding_id, amount_at_risk_paise, queue_rank in conn.execute(
                "SELECT exception_id, origin, record_key, finding_id, amount_at_risk_paise, queue_rank "
                "FROM exception ORDER BY exception_id"
            ).fetchall()
        ]

        resolutions = [
            ResolutionRow(exception_id, outcome, stop_reason)
            for exception_id, outcome, stop_reason in conn.execute(
                "SELECT exception_id, outcome, stop_reason FROM resolution ORDER BY exception_id"
            ).fetchall()
        ]

        agent_call_row = conn.execute(
            "SELECT COALESCE(SUM(tokens_in + tokens_out), 0), COUNT(*) FROM agent_call"
        ).fetchone()
        agent_call_tokens_total, agent_call_count = agent_call_row

        return cls(
            run_id=run_id,
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            match_groups=match_groups,
            settlement_units=settlement_units,
            findings=findings,
            exceptions=exceptions,
            resolutions=resolutions,
            agent_call_tokens_total=agent_call_tokens_total,
            agent_call_count=agent_call_count,
        )
