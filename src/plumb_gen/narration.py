"""LLD §3.2 -- five UTR-extraction patterns, generated here so all five
actually get exercised, plus the unparseable case. If every narration
matched the top pattern, the cascade below it would be dead code no test
ever reaches.

Each template is built so it does not also contain another pattern's
label word -- "first match wins" means a stray "UTR" or "NEFT" substring
in, say, a bare_token narration would silently short-circuit to a
higher-confidence pattern than the one being tested.
"""

import string
from random import Random

ALNUM = string.ascii_uppercase + string.digits
LETTERS = string.ascii_uppercase
DIGITS = string.digits

PATTERNS = ("utr_labelled", "neft_ref", "rtgs_ref", "imps_ref", "bare_token")


def _token(rng: Random, n: int, alphabet: str = ALNUM) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def _utr_labelled(rng: Random) -> tuple[str, str]:
    utr = _token(rng, 15)
    return utr, f"UTR:{utr} PLATFORM SETTLEMENT"


def _neft_ref(rng: Random) -> tuple[str, str]:
    utr = _token(rng, 4, LETTERS) + _token(rng, rng.randint(8, 14))
    return utr, f"NEFT/{utr}/PLATFORM SETTLEMENT"


def _rtgs_ref(rng: Random) -> tuple[str, str]:
    utr = _token(rng, rng.randint(16, 20))
    return utr, f"RTGS-{utr}-SETTLEMENT"


def _imps_ref(rng: Random) -> tuple[str, str]:
    utr = _token(rng, 12, DIGITS)
    return utr, f"IMPS/{utr}/TRANSFER"


def _bare_token(rng: Random) -> tuple[str, str]:
    utr = _token(rng, 4, LETTERS) + _token(rng, rng.randint(12, 18))
    return utr, f"SETTLEMENT REF {utr} THANK YOU"


def _unparseable(rng: Random) -> str:
    # Short generic words only -- no run of 12+ contiguous alnum chars, so
    # this can't accidentally satisfy any of the five patterns above.
    words = ["NEFT", "CR", "REF", "PROCESSING", "FEE", "DEBIT", "TXN", "MISC", "CHG"]
    return " ".join(rng.choice(words) for _ in range(rng.randint(3, 5)))


_GENERATORS = {
    "utr_labelled": _utr_labelled,
    "neft_ref": _neft_ref,
    "rtgs_ref": _rtgs_ref,
    "imps_ref": _imps_ref,
    "bare_token": _bare_token,
}


def generate_settlement_reference(rng: Random, unparseable_rate_bps: int) -> tuple[str, str, str | None]:
    """Returns (true_utr, narration_text, bank_side_utr).

    true_utr is what Razorpay's own settlement report always states
    (settlement_recon.utr, never null -- Razorpay always knows its own
    reference). narration_text is what the bank statement actually shows.
    bank_side_utr is true_utr when the narration reveals it (four of the
    five patterns, or the fifth at low confidence), or None when the
    narration is unparseable -- the bank side genuinely can't recover a
    utr from free text alone, even though the true one still exists.

    Uniform over the five real patterns, not weighted toward real-world
    frequency -- uniform maximises the odds all five actually appear
    across one batch regardless of seed, which is a coverage choice, not
    a realism one.
    """
    if rng.randint(1, 10_000) <= unparseable_rate_bps:
        true_utr = _token(rng, 15)
        narration = _unparseable(rng)
        return true_utr, narration, None

    pattern = PATTERNS[rng.randrange(len(PATTERNS))]
    true_utr, narration = _GENERATORS[pattern](rng)
    return true_utr, narration, true_utr
