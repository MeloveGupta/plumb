"""BACKEND_SCHEMA §5 -- eval.sqlite, written only by plumb_eval. Mirrors
plumb_gen/truth_db.py's open/write pattern.
"""

import sqlite3
from pathlib import Path

from plumb_eval.metrics import NOT_MEASURED, Metric
from plumb_eval.scoring import ScoredAbstention, ScoredDefect, ScoredMatch

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "eval.sql"
SCHEMA_SQL = SCHEMA_PATH.read_text()


def open_eval_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def write_eval_result(
    path: str | Path,
    metrics: list[Metric],
    scored_matches: list[ScoredMatch],
    scored_defects: list[ScoredDefect],
    scored_abstentions: list[ScoredAbstention],
    sample_label: str,
) -> None:
    conn = open_eval_db(path)

    for metric in metrics:
        if metric.value is None:
            conn.execute(
                "INSERT INTO metric (name, value_num, value_text, unit, sample_label) VALUES (?, NULL, ?, ?, ?)",
                (metric.name, NOT_MEASURED, metric.unit, sample_label),
            )
        else:
            conn.execute(
                "INSERT INTO metric (name, value_num, value_text, unit, sample_label) VALUES (?, ?, NULL, ?, ?)",
                (metric.name, float(metric.value), metric.unit, sample_label),
            )

    for m in scored_matches:
        conn.execute(
            "INSERT INTO scored_match (match_id, verdict, silent) VALUES (?, ?, ?)",
            (m.match_id, m.verdict, int(m.silent)),
        )

    for d in scored_defects:
        conn.execute(
            "INSERT INTO scored_defect (instance_id, was_detected, detected_finding_id, class_correct) "
            "VALUES (?, ?, ?, ?)",
            (
                d.instance_id,
                int(d.was_detected),
                d.detected_finding_id,
                None if d.class_correct is None else int(d.class_correct),
            ),
        )

    for a in scored_abstentions:
        conn.execute(
            "INSERT INTO scored_abstention (exception_id, verdict) VALUES (?, ?)",
            (a.exception_id, a.verdict),
        )

    conn.commit()
    conn.close()
