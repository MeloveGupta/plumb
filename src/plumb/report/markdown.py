"""close.md + exceptions.md -- TRD §10.1/§10.2, UIUX_BRIEF §4.2/§4.3.

report/ is the one layer where a float is allowed, but there are none
here -- money stays int paise, formatted by domain.money.format_inr at
the last moment. "cash position", never "forecast" (PRD §13).
"""

from datetime import date

from plumb.domain.money import format_inr
from plumb.report.reader import RunPack

_MINUS = "−"  # U+2212, not a hyphen (UIUX §4.2)

# close.md is a committed Markdown file, not a terminal stream, so it
# carries no ANSI. UIUX §2.2's ochre for the held bucket is a
# rendered-view concern; here the held line gets its weight from being
# last and from the "← N transfers, oldest N days" annotation the brief
# asks for by name ("give it the arrow, give it the age").


def _amt(paise: int, width: int = 15) -> str:
    return format_inr(abs(paise)).rjust(width)


def _held_age_days(pack: RunPack, order_placed_at: str) -> int:
    as_of = date.fromisoformat(pack.as_of) if pack.as_of else date.today()
    return (as_of - date.fromisoformat(order_placed_at[:10])).days


def render_close(pack: RunPack) -> str:
    order_by_key = {o["record_key"]: o for o in pack.orders}
    payment_order = {p["record_key"]: p["order_key"] for p in pack.payments}
    transfer_order = {t["record_key"]: payment_order.get(t["payment_key"]) for t in pack.transfers}

    gross = sum(o["gross_paise"] for o in pack.orders)
    razorpay_fees = sum(p["fee_paise"] for p in pack.payments)
    gst_on_fees = sum(p["tax_paise"] for p in pack.payments)
    commission = sum(i["expected_commission_paise"] for i in pack.intents)
    tcs = sum(i["expected_tcs_paise"] for i in pack.intents)
    tds = sum(i["expected_tds_paise"] for i in pack.intents)
    rrd = (
        sum(r["amount_paise"] for r in pack.refunds)
        + sum(r["amount_paise"] for r in pack.reversals)
        + sum(d["deducted_amount_paise"] for d in pack.disputes)
    )
    expected_settleable = gross - razorpay_fees - gst_on_fees - commission - tcs - tds - rrd

    settled = in_flight = held = 0
    held_ages: list[int] = []
    for t in pack.transfers:
        if t["on_hold"] == 1 and t["on_hold_until_utc"] is None:
            held += t["amount_paise"]
            ok = transfer_order.get(t["record_key"])
            if ok and ok in order_by_key:
                held_ages.append(_held_age_days(pack, order_by_key[ok]["placed_at_utc"]))
        elif t["settled_at_utc"] is not None:
            settled += t["amount_paise"]
        else:
            in_flight += t["amount_paise"]

    rule = "  " + "─" * 48
    held_tail = ""
    if held_ages:
        held_tail = f"   ← {len(held_ages)} transfers, oldest {max(held_ages)} days"

    def row(label: str, paise: int, deduct: bool = False) -> str:
        marker = f"{_MINUS} " if deduct else "  "
        return f"  {marker}{label:<28}{_amt(paise)}"

    lines = [
        f"# Cash position — run `{pack.run_id}`  ·  `{pack.sample_label}`",
        "",
        "```",
        f"                                  {'₹':>15}",
        row("gross collected", gross),
        row("Razorpay fees", razorpay_fees, deduct=True),
        row("GST on fees", gst_on_fees, deduct=True),
        row("platform commission", commission, deduct=True),
        row("TCS withheld", tcs, deduct=True),
        row("TDS withheld", tds, deduct=True),
        row("refunds, reversals, disputes", rrd, deduct=True),
        rule,
        row("expected settleable", expected_settleable),
        row("    settled", settled),
        row("    in flight  (T+n)", in_flight),
        row("    ON HOLD   no release date", held) + held_tail,
        "```",
        "",
        "The ON HOLD line is money the platform collected and cannot see —"
        " transfers parked with no release date (D06). This is a **cash"
        " position**, not a forecast.",
        "",
    ]
    return "\n".join(lines)


def render_exceptions(pack: RunPack) -> str:
    processed = sum(o["gross_paise"] for o in pack.orders)
    finding_defect = {f["finding_id"]: f["defect_id"] for f in pack.findings}
    finding_steps = pack.recompute_steps

    escalated = [
        e for e in pack.exceptions
        if pack.resolutions.get(e["exception_id"], {}).get("outcome") == "ESCALATED_UNRESOLVED"
    ]
    escalated_amount = sum(e["amount_at_risk_paise"] for e in escalated)
    pct = (escalated_amount / processed * 100) if processed else 0.0

    out = [
        f"# Exceptions — run `{pack.run_id}`  ·  `{pack.sample_label}`",
        "",
        f"**{len(escalated)} escalated** · {format_inr(escalated_amount)} escalated · "
        f"**{pct:.1f}%** of {format_inr(processed)} processed",
        "",
        f"{len(pack.exceptions)} exceptions total, sorted by rupees at risk, no truncation.",
        "",
    ]

    for e in pack.exceptions:  # already ORDER BY amount_at_risk_paise DESC
        exc_id = e["exception_id"]
        res = pack.resolutions.get(exc_id, {})
        defect = finding_defect.get(e["finding_id"], "UNMATCHED") if e["origin"] == "FINDING" else "UNMATCHED"
        out.append("---")
        out.append("")
        out.append(f"### `{exc_id}`  ·  {defect}  ·  {format_inr(e['amount_at_risk_paise'])} at risk")
        out.append("")
        out.append(f"| outcome | `{res.get('outcome', 'NOT_MEASURED')}`"
                   + (f" (model claimed `{res['model_claimed_outcome']}`, downgraded: {res['downgrade_reason']})"
                      if res.get("was_downgraded") else "")
                   + " |")
        out.append("|---|")
        out.append(f"| what was tried | {res.get('what_was_tried', '')} |")
        if res.get("what_would_resolve_it"):
            out.append(f"| what would resolve it | {res['what_would_resolve_it']} |")
        ev = pack.resolution_evidence.get(exc_id) or (
            pack.finding_evidence.get(e["finding_id"], []) if e["origin"] == "FINDING" else []
        )
        if ev:
            out.append("| evidence | " + ", ".join(f"`{r['record_key']}` ({r['role']})" for r in ev) + " |")
        hyps = pack.hypotheses.get(exc_id, [])
        if hyps:
            out.append("| hypotheses | " + " / ".join(f"{h['rank']}. {h['statement']}" for h in hyps) + " |")
        out.append("")
        if e["origin"] == "FINDING" and e["finding_id"] in finding_steps:
            out.append("recompute trace:")
            out.append("")
            out.append("```")
            for s in finding_steps[e["finding_id"]]:
                out.append(f"  {s['step_no']}. {s['label']}")
                out.append(f"       {s['formula']}   over {s['inputs']}")
                out.append(f"       = {s['output_paise']} paise")
            out.append("```")
            out.append("")

    return "\n".join(out)
