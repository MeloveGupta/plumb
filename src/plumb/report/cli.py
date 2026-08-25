"""UIUX_BRIEF.md §3.1 -- CLI run output, v1: L0 (ingest) + L1 (match)
only. L2 (verify) and L3 (investigate) don't exist yet, so their lines
aren't rendered here -- this grows as those layers land.

Pure rendering, not orchestration: takes already-computed counts and a
MatchResult, returns the formatted block as a string. Generating a real
run_id and wiring generate -> ingest -> match -> render together belongs
to a run-orchestration layer that doesn't exist yet (plumb/stub_engine.py's
own docstring says as much -- "no run-orchestration layer exists yet");
LLD §11 lists "CLI argument wiring" as left to judgment, not a design
decision with lasting consequences, so that wiring is deliberately not
built here.

Money paths stay int paise everywhere in the engine (TRD §2.5), but this
file is report/ -- the one layer where a float is allowed, and the match
percentage is exactly that: a display ratio computed from already-final
int counts, never fed back into anything the matcher decides.
"""

import os
import sys

from plumb.match.engine import MatchResult

_VERIFIED = "\033[38;2;47;95;74m"  # UIUX_BRIEF §2.2 --verified, ledger green
_VARIANCE = "\033[38;2;168;50;30m"  # UIUX_BRIEF §2.2 --variance, oxide red
_RESET = "\033[0m"

_VALID_SAMPLE_LABELS = ("HELD_OUT", "IN_SAMPLE")


def _color_enabled() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _colored(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{_RESET}" if enabled else text


def render_run_summary(
    *,
    run_id: str,
    batch_id: str,
    sample_label: str,
    tolerance_profile_name: str,
    total_records: int,
    source_count: int,
    quarantined: int,
    result: MatchResult,
    reports_dir: str,
    color: bool | None = None,
) -> str:
    """sample_label must be HELD_OUT or IN_SAMPLE (CLAUDE.md rule 11 --
    every match rate is printed with its tolerance profile, and every
    metric carries which of the two it is). matched/unmatched are
    derived from `result` directly, never passed separately, so this
    line can never drift from what the matcher actually returned.
    """
    if sample_label not in _VALID_SAMPLE_LABELS:
        raise ValueError(f"sample_label must be one of {_VALID_SAMPLE_LABELS}, got {sample_label!r}")

    enabled = _color_enabled() if color is None else color

    claimed = sum(len(g.members) for g in result.groups)
    unmatched = len(result.unmatched)
    accounted = claimed + unmatched
    match_pct = (claimed / total_records * 100) if total_records else 0.0
    balances = accounted == total_records

    ledger_line = _colored(
        f"  ledger balances    {total_records} in · {accounted} accounted for {'✓' if balances else '✗'}",
        _VERIFIED if balances else _VARIANCE,
        enabled,
    )

    lines = [
        "plumb · settlement assurance",
        f"run {run_id} · {batch_id} · {sample_label} · tolerance {tolerance_profile_name}",
        "",
        f"  L0  ingest         {total_records} records · {source_count} sources"
        f"    {quarantined} quarantined",
        f"  L1  match          {claimed} matched  {match_pct:.1f}%"
        f"    {unmatched} unmatched",
        "",
        ledger_line,
        "",
        f"  reports/{run_id}/",
    ]
    return "\n".join(lines)
