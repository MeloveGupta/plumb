"""UIUX_BRIEF.md §3.1 -- CLI run output. L0 (ingest) + L1 (match) v1,
plus L2 (verify)'s summary + on_matched_record sub-line (P2.12). L3
(investigate) doesn't exist yet, so its line isn't rendered here -- this
grows as that layer lands.

Pure rendering, not orchestration: takes already-computed counts, a
MatchResult, and (optionally) verify-layer output, returns the formatted
block as a string. Generating a real run_id and wiring generate ->
ingest -> match -> verify -> render together belongs to a run-
orchestration layer that doesn't exist yet (plumb/stub_engine.py's own
docstring says as much -- "no run-orchestration layer exists yet");
LLD §11 lists "CLI argument wiring" as left to judgment, not a design
decision with lasting consequences, so that wiring is deliberately not
built here.

L2's `on_matched_record` flag is read straight off each Finding, never
re-derived here -- UIUX_BRIEF §3.1: "The L2 sub-line is the product's
argument... Indent it, keep it, never suppress it." Rendered whenever
`l2_unit_count`/`l2_findings` are given, even when there are zero
findings -- "never suppress" means always, not only when there's
something to show.

Money paths stay int paise everywhere in the engine (TRD §2.5), but this
file is report/ -- the one layer where a float is allowed, and the match
percentage is exactly that: a display ratio computed from already-final
int counts, never fed back into anything the matcher decides.
"""

import os
import sys

from plumb.domain.money import format_inr, sum_paise
from plumb.match.engine import MatchResult
from plumb.verify.trace import Finding

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
    l2_unit_count: int | None = None,
    l2_findings: list[Finding] | None = None,
    color: bool | None = None,
) -> str:
    """sample_label must be HELD_OUT or IN_SAMPLE (CLAUDE.md rule 11 --
    every match rate is printed with its tolerance profile, and every
    metric carries which of the two it is). matched/unmatched are
    derived from `result` directly, never passed separately, so this
    line can never drift from what the matcher actually returned.

    `l2_unit_count`/`l2_findings` are both optional and both-or-neither:
    omit both to get the original L0/L1-only output (P1.11); pass both
    to also render L2's summary + on_matched_record sub-line (P2.12).
    `on_matched_record` is read straight off each Finding -- computed
    once, at check time, never re-derived here.
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
    ]

    if l2_unit_count is not None and l2_findings is not None:
        total_at_risk = sum_paise(f.amount_at_risk_paise for f in l2_findings)
        matched_count = sum(1 for f in l2_findings if f.on_matched_record)
        at_risk_text = f"{format_inr(total_at_risk)} at risk"
        l2_line = _colored(
            f"  L2  verify         {l2_unit_count} verified"
            f"                {len(l2_findings)} findings   {at_risk_text}",
            _VARIANCE if total_at_risk > 0 else _VERIFIED,
            enabled,
        )
        lines.append(l2_line)
        lines.append(f"                     └─ {matched_count} findings on MATCHED records")

    lines.extend(
        [
            "",
            ledger_line,
            "",
            f"  reports/{run_id}/",
        ]
    )
    return "\n".join(lines)


_BAR_WIDTH = 16
_OVERHANG_WIDTH = 4


def render_variance_bar(
    delta_paise: int, band_paise: int, width: int = _BAR_WIDTH, overhang_width: int = _OVERHANG_WIDTH,
    color: bool | None = None,
) -> str:
    """UIUX_BRIEF §2.5 -- the variance bar, confirmed reading (not a
    transcribed spec formula; the brief gives no exact character-width
    or overhang-scale number): the solid bar represents the reconciled
    amount at full scale -- a clean record and an in-band shortfall show
    the *same* `width` solid blocks, because the money that did arrive
    is real. The oxide-red overhang is a separately-scaled segment sized
    by `delta_paise / band_paise` -- how deep into the tolerance band
    the shortfall sits, not how big it is relative to the order's own
    gross. `width`/`overhang_width` are implementation choices, easy to
    retune; report/'s no-float exemption covers the ratio arithmetic.

    `delta_paise <= 0` (reconciled exactly, or overpaid) draws a solid
    bar with no overhang -- nothing at risk -- padded with `overhang_width`
    blank spaces so every row's bar is the same total length regardless
    of whether it has a shortfall, keeping a table of rows aligned.
    The checkmark/short-amount annotation is `render_variance_row`'s
    job, not the bar's own -- kept separate so this function is purely
    "the bar," composable into a row or used on its own.
    """
    enabled = _color_enabled() if color is None else color
    if delta_paise <= 0:
        return "█" * width + " " * overhang_width

    fraction = min(1.0, delta_paise / band_paise) if band_paise else 1.0
    overhang_chars = round(fraction * overhang_width)
    overhang = _colored("▏" * overhang_chars, _VARIANCE, enabled)
    gap = " " * (overhang_width - overhang_chars)
    return "█" * width + overhang + gap


def render_variance_row(
    defect_label: str, order_id: str, delta_paise: int, band_paise: int, color: bool | None = None,
) -> str:
    """One row of the variance-bar table -- UIUX_BRIEF §2.5's mockup:
    `D01  ord_00042   <bar>   ₹  30.00 short` / a clean record's
    `     ord_00088   <bar>   ✓` (blank defect_label). One row per
    record, box-drawing characters in the CLI (unicode in reports, SVG
    in The Ledger -- "one idea, three renderings"; only the CLI
    rendering is built here).
    """
    bar = render_variance_bar(delta_paise, band_paise, color=color)
    tail = "✓" if delta_paise <= 0 else f"{format_inr(delta_paise)} short"
    return f"{defect_label:<3}  {order_id}   {bar}   {tail}"
