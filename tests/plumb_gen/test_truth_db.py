"""BACKEND_SCHEMA.md §4 -- truth.sqlite, written by plumb_gen, never
opened by the engine. Same FK-enforcement standard as P0.3/P0.4's schema
tests, now exercised through the real production writer.
"""

import json
import sqlite3

from plumb_gen.config import GeneratorConfig
from plumb_gen.injection_config import DefectSpec, InjectionConfig
from plumb_gen.truth_db import write_truth
from plumb_gen.world import build_world


def test_write_truth_round_trips_every_record(tmp_path):
    config = GeneratorConfig(
        seed=1,
        batch_id="batch_test",
        defects=InjectionConfig(defects={"D01": DefectSpec(count=6), "D02": DefectSpec(count=8)}),
    )
    world = build_world(config)
    db_path = tmp_path / "truth.sqlite"
    write_truth(world, db_path)

    conn = sqlite3.connect(db_path)
    truth_count = conn.execute("SELECT COUNT(*) FROM truth_record").fetchone()[0]
    defect_count = conn.execute("SELECT COUNT(*) FROM injected_defect").fetchone()[0]
    assert truth_count == len(world.truth_records) == 200
    assert defect_count == len(world.injected_defects) == 14

    row = conn.execute(
        "SELECT record_key, true_obligation_json, resolvable_from_available_data FROM truth_record LIMIT 1"
    ).fetchone()
    record_key, true_obligation_json, resolvable = row
    obligation = json.loads(true_obligation_json)
    assert set(obligation) == {"commission_paise", "tcs_paise", "tds_paise"}
    assert resolvable == 1

    for defect in world.injected_defects:
        stored = conn.execute(
            "SELECT amount_at_risk_paise, within_tolerance, defect_class FROM injected_defect WHERE instance_id = ?",
            (defect.instance_id,),
        ).fetchone()
        assert stored == (defect.amount_at_risk_paise, int(defect.within_tolerance), defect.defect_class)
    conn.close()


def test_injected_defect_record_key_always_resolves_to_a_truth_record(tmp_path):
    # FK enforcement -- same standard as P0.3/P0.4's schema tests. If
    # write_truth ever inserted a defect for a record it didn't also
    # write a truth_record for, this raises rather than silently
    # producing an orphaned row.
    config = GeneratorConfig(
        seed=1,
        batch_id="batch_test",
        defects=InjectionConfig(defects={"D06": DefectSpec(count=5)}),
    )
    world = build_world(config)
    db_path = tmp_path / "truth.sqlite"
    write_truth(world, db_path)  # would raise sqlite3.IntegrityError if FK violated

    conn = sqlite3.connect(db_path)
    orphans = conn.execute(
        """SELECT COUNT(*) FROM injected_defect
           WHERE record_key NOT IN (SELECT record_key FROM truth_record)"""
    ).fetchone()[0]
    assert orphans == 0
    conn.close()
