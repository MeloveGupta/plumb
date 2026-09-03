"""Read a finished run.sqlite into the shape the report pack needs.

`report/` may import `plumb.store.ddl` (unlike plumb_eval, TRD §3.1), so
this uses the sanctioned reopen. One pass, plain dataclasses, no live
cursors -- same discipline as plumb_eval/run_reader.py, wider SELECT
set (close.md needs the canonical detail tables; exceptions.md needs
the full resolution row + recompute_step + hypothesis).
"""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from plumb.store.ddl import open_existing_run_db


@dataclass(frozen=True)
class _Row:
    d: dict

    def __getattr__(self, k: str):
        return self.d[k]


@dataclass(frozen=True)
class RunPack:
    run_id: str
    ablation_config: str
    sample_label: str
    as_of: str | None
    orders: list[dict]
    intents: list[dict]
    payments: list[dict]
    transfers: list[dict]
    refunds: list[dict]
    reversals: list[dict]
    disputes: list[dict]
    bank_credits: list[dict]
    settlement_recons: list[dict]
    settlement_units: list[dict]
    findings: list[dict]
    recompute_steps: dict[str, list[dict]]        # finding_id -> steps
    finding_evidence: dict[str, list[dict]]       # finding_id -> [{record_key, role}]
    exceptions: list[dict]
    resolutions: dict[str, dict]                  # exception_id -> full row
    hypotheses: dict[str, list[dict]]             # exception_id -> [{rank, statement, supports}]
    resolution_evidence: dict[str, list[dict]]    # exception_id -> [{record_key, role}]
    agent_calls: list[dict]
    terminal_states: dict[str, str]               # record_key -> terminal_state


def _rows(conn: sqlite3.Connection, sql: str) -> list[dict]:
    cur = conn.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_run_pack(run_dir: Path) -> RunPack:
    conn = open_existing_run_db(Path(run_dir) / "run.sqlite")
    try:
        run = _rows(conn, "SELECT run_id, ablation_config, sample_label FROM run")[0]
        cfg = {r["key"]: json.loads(r["value_json"]) for r in _rows(conn, "SELECT key, value_json FROM config_snapshot")}

        steps: dict[str, list[dict]] = {}
        for s in _rows(conn, "SELECT finding_id, step_no, label, formula, inputs_json, output_paise "
                             "FROM recompute_step ORDER BY finding_id, step_no"):
            s["inputs"] = json.loads(s.pop("inputs_json"))
            steps.setdefault(s["finding_id"], []).append(s)

        fev: dict[str, list[dict]] = {}
        for e in _rows(conn, "SELECT finding_id, record_key, role FROM finding_evidence ORDER BY finding_id, record_key, role"):
            fev.setdefault(e["finding_id"], []).append({"record_key": e["record_key"], "role": e["role"]})

        hyps: dict[str, list[dict]] = {}
        for h in _rows(conn, "SELECT exception_id, rank, statement, supports_json FROM hypothesis ORDER BY exception_id, rank"):
            h["supports"] = json.loads(h.pop("supports_json"))
            hyps.setdefault(h["exception_id"], []).append(h)

        rev: dict[str, list[dict]] = {}
        for e in _rows(conn, "SELECT exception_id, record_key, role FROM resolution_evidence "
                             "ORDER BY exception_id, record_key, role"):
            rev.setdefault(e["exception_id"], []).append({"record_key": e["record_key"], "role": e["role"]})

        resolutions = {
            r["exception_id"]: r
            for r in _rows(conn, "SELECT exception_id, outcome, model_claimed_outcome, was_downgraded, "
                                 "downgrade_reason, confidence, chosen_hypothesis_id, iterations_used, "
                                 "stop_reason, what_was_tried, what_would_resolve_it FROM resolution")
        }

        return RunPack(
            run_id=run["run_id"],
            ablation_config=run["ablation_config"],
            sample_label=run["sample_label"],
            as_of=cfg.get("as_of"),
            orders=_rows(conn, 'SELECT * FROM "order"'),
            intents=_rows(conn, "SELECT * FROM intent"),
            payments=_rows(conn, "SELECT * FROM payment"),
            transfers=_rows(conn, "SELECT * FROM transfer"),
            refunds=_rows(conn, "SELECT * FROM refund"),
            reversals=_rows(conn, "SELECT * FROM reversal"),
            disputes=_rows(conn, "SELECT * FROM dispute"),
            bank_credits=_rows(conn, "SELECT * FROM bank_credit"),
            settlement_recons=_rows(conn, "SELECT * FROM settlement_recon"),
            settlement_units=_rows(conn, "SELECT * FROM settlement_unit"),
            findings=_rows(conn, "SELECT * FROM finding ORDER BY finding_id"),
            recompute_steps=steps,
            finding_evidence=fev,
            exceptions=_rows(conn, "SELECT * FROM exception ORDER BY amount_at_risk_paise DESC, exception_id"),
            resolutions=resolutions,
            hypotheses=hyps,
            resolution_evidence=rev,
            agent_calls=_rows(conn, "SELECT * FROM agent_call ORDER BY exception_id, iteration, call_id"),
            terminal_states={r["record_key"]: r["terminal_state"]
                             for r in _rows(conn, "SELECT record_key, terminal_state FROM record_terminal_state")},
        )
    finally:
        conn.close()
