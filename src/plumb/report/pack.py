"""write_report_pack -- the L4 close pack. Reads a finished run.sqlite
and writes close.md, exceptions.md, and the three JSONL projections
into the run directory. Called by pipeline.execute_run.
"""

from pathlib import Path

from plumb.report.jsonl import agent_calls_jsonl, findings_jsonl, resolutions_jsonl
from plumb.report.markdown import render_close, render_exceptions
from plumb.report.reader import load_run_pack


def write_report_pack(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    pack = load_run_pack(run_dir)

    (run_dir / "close.md").write_text(render_close(pack) + "\n")
    (run_dir / "exceptions.md").write_text(render_exceptions(pack) + "\n")
    (run_dir / "findings.jsonl").write_text("".join(line + "\n" for line in findings_jsonl(pack)))
    (run_dir / "resolutions.jsonl").write_text("".join(line + "\n" for line in resolutions_jsonl(pack)))
    (run_dir / "agent_calls.jsonl").write_text("".join(line + "\n" for line in agent_calls_jsonl(pack)))
