"""BACKEND_SCHEMA.md §4 -- truth.sqlite is generator output, scorer only.
Mirrors plumb/store/ddl.py's open_run_db pattern, but deliberately lives
under plumb_gen/, not plumb/ -- the engine must never open this file
(TRD §3.1), and BACKEND_SCHEMA §4 names plumb_gen as the writer.
"""

import json
import sqlite3
from pathlib import Path

from plumb_gen.world import World

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "truth.sql"
SCHEMA_SQL = SCHEMA_PATH.read_text()


def open_truth_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def write_truth(world: World, path: str | Path) -> None:
    conn = open_truth_db(path)
    for record in world.truth_records:
        conn.execute(
            """INSERT INTO truth_record
               (record_key, true_counterparts_json, true_obligation_json, resolvable_from_available_data)
               VALUES (?, ?, ?, ?)""",
            (
                record.record_key,
                json.dumps(record.true_counterparts),
                json.dumps(record.true_obligation),
                int(record.resolvable_from_available_data),
            ),
        )
    for defect in world.injected_defects:
        conn.execute(
            """INSERT INTO injected_defect
               (instance_id, record_key, defect_class, amount_at_risk_paise, within_tolerance, params_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                defect.instance_id,
                defect.record_key,
                defect.defect_class,
                defect.amount_at_risk_paise,
                int(defect.within_tolerance),
                json.dumps(defect.params),
            ),
        )
    conn.commit()
    conn.close()
