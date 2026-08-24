"""extract_utr() against real plumb-gen output, not hand-written strings
-- P0.7 verified all five patterns plus the unparseable case appear
across seeds, so a real generated batch should hit all five here too.
"""

from plumb.ingest.narration import extract_utr
from plumb_gen.config import GeneratorConfig
from plumb_gen.sources import bank_csv_rows
from plumb_gen.world import build_world


def _real_narrations() -> list[str]:
    config = GeneratorConfig(seed=42, batch_id="batch_test", batch_size=200)
    world = build_world(config)
    return [row["narration"] for row in bank_csv_rows(world)]


def test_all_five_patterns_and_the_unparseable_case_appear_and_resolve_correctly():
    narrations = _real_narrations()
    assert narrations  # not vacuously testing zero rows

    seen_patterns: set[str] = set()
    for narration in narrations:
        utr, confidence, pattern_name = extract_utr(narration)
        seen_patterns.add(pattern_name)

        if pattern_name == "utr_labelled":
            assert confidence == 10_000
            assert utr is not None
        elif pattern_name in ("neft_ref", "rtgs_ref"):
            assert confidence == 9_500
            assert utr is not None
        elif pattern_name == "imps_ref":
            assert confidence == 9_000
            assert utr is not None
            assert utr.isdigit()
        elif pattern_name == "bare_token":
            assert confidence == 6_000
            assert utr is not None
        elif pattern_name == "no_match":
            # the unparseable case -- a valid row with a missing field.
            assert utr is None
            assert confidence == 0
        else:
            raise AssertionError(f"unexpected pattern_name {pattern_name!r} for narration {narration!r}")

    assert seen_patterns == {"utr_labelled", "neft_ref", "rtgs_ref", "imps_ref", "bare_token", "no_match"}


def test_utr_labelled_beats_bare_token_when_both_shapes_are_present():
    # utr_labelled's own token is 15 alnum chars -- long enough to also
    # satisfy bare_token's looser shape if it happened to start with 4
    # letters. "First match wins" means utr_labelled must still win.
    utr, confidence, pattern_name = extract_utr("UTR:ABCDEFGHIJKLMNO PLATFORM SETTLEMENT")
    assert pattern_name == "utr_labelled"
    assert confidence == 10_000
    assert utr == "ABCDEFGHIJKLMNO"


def test_ambiguous_same_tier_matches_return_null_not_a_guess():
    # Two distinct bare_token-shaped strings in one narration -- never
    # guess which one is the real UTR.
    utr, confidence, pattern_name = extract_utr("REF AAAABBBBCCCCDDDD AND REF EEEEFFFFGGGGHHHH")
    assert utr is None
    assert confidence == 0
    assert pattern_name == "ambiguous_narration"


def test_repeated_identical_match_is_not_ambiguous():
    # The same UTR mentioned twice is not a distinct-match conflict.
    utr, confidence, pattern_name = extract_utr("UTR:ABCDEFGHIJKLMNO REF ABCDEFGHIJKLMNO SETTLEMENT")
    assert utr == "ABCDEFGHIJKLMNO"
    assert confidence == 10_000
    assert pattern_name == "utr_labelled"
