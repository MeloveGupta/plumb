"""LLD §3.2 -- UTR extraction from bank narration. Five patterns, most
specific first; ordering is semantic and must never be reordered or
sorted -- "first match wins."

# TRD-DEVIATION: LLD §3.2's own pseudocode types confidence as `float`
# (UTR_PATTERNS: list[tuple[str, re.Pattern, float]]). This is inside
# plumb/ (the engine), not plumb_eval/ -- unlike the scorer's read-only,
# downstream ratio metrics, a float here sits inside L1/L2's own
# determinism-critical path, and TRD §2's no-float lint doesn't exempt
# ingest/. Represented as confidence_bps (int, basis points) instead --
# TRD §2 rule 3's own established convention for exactly this kind of
# fractional-but-bounded score (0.95 -> 9500), matching how
# match_group.confidence/resolution.confidence are the only other
# confidence-shaped values in this codebase, both already REAL-column
# exceptions rather than a precedent to extend. Every value below is
# still a fixed constant, never computed or divided at runtime.

Verified by hand against src/plumb_gen/narration.py's real generated
templates before committing to these patterns: UTR:{15} matches
utr_labelled, NEFT/{12-18}/... matches neft_ref, RTGS-{16-20}-...
matches rtgs_ref, IMPS/{12 digits}/... matches imps_ref, and
"SETTLEMENT REF {16-22} THANK YOU" matches bare_token. Each template is
built so it can't also satisfy an earlier, higher-priority pattern
(confirmed: none of the literal label words UTR/NEFT/RTGS/IMPS appear
inside another pattern's own generated text).
"""

import re

UTR_PATTERNS: list[tuple[str, re.Pattern, int]] = [
    ("utr_labelled", re.compile(r"\bUTR[:\s-]*([A-Z0-9]{12,22})\b"), 10_000),  # 1.00
    ("neft_ref", re.compile(r"\bNEFT[/\s-]*([A-Z]{4}[A-Z0-9]{8,18})\b"), 9_500),  # 0.95
    ("rtgs_ref", re.compile(r"\bRTGS[/\s-]*([A-Z0-9]{16,22})\b"), 9_500),  # 0.95
    ("imps_ref", re.compile(r"\bIMPS[/\s-]*(\d{12})\b"), 9_000),  # 0.90
    ("bare_token", re.compile(r"\b([A-Z]{4}[A-Z0-9]{12,18})\b"), 6_000),  # 0.60
]


def extract_utr(narration: str) -> tuple[str | None, int, str]:
    """Returns (utr, confidence_bps, pattern_name). First match wins --
    patterns are tried in specificity order, never reordered.

    Confidence-below-0.60 (6000 bps) is not a separate branch here: the
    five listed confidences bottom out at exactly 6000 bps (bare_token),
    so there is no live "matched, but under 6000 bps" case -- the only
    way to reach utr=NULL with confidence 0 is no pattern matching at
    all ("no_match") or a same-tier ambiguous match
    ("ambiguous_narration"). Both are valid rows with a missing field,
    never a quarantine reason.
    """
    for pattern_name, pattern, confidence_bps in UTR_PATTERNS:
        matches = pattern.findall(narration)
        if not matches:
            continue
        distinct = list(dict.fromkeys(matches))  # order-preserving dedup, rule 7
        if len(distinct) > 1:
            return None, 0, "ambiguous_narration"
        return matches[0], confidence_bps, pattern_name
    return None, 0, "no_match"
