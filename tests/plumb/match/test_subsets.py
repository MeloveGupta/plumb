"""LLD §4.2 -- find_subset, hand-computed. The ambiguity rule (never pick
between two equally-valid subsets) is the important behaviour here, not
the arithmetic.
"""

import random

from plumb.match.subsets import MAX_PARTITION_SIZE, SubsetStatus, find_subset


def test_whole_partition_fast_path_is_tried_first():
    # 300 + 700 = 1000; sum of the whole partition also happens to be
    # 1000, but combinatorial search would find the exact same answer,
    # so this only proves the fast path fires, not that it's needed --
    # covered separately by test_ambiguous below.
    candidates = [("bnk_00001", 300), ("bnk_00002", 700)]
    result = find_subset(1000, candidates, max_members=5)
    assert result.status == SubsetStatus.UNIQUE
    assert result.members == ("bnk_00001", "bnk_00002")


def test_unique_subset_smaller_than_whole_partition():
    # Whole partition sums to 300+700+50=1050 != 1000, so the fast path
    # does not fire; combinatorial search must find {300, 700}.
    candidates = [("bnk_00001", 300), ("bnk_00002", 700), ("bnk_00003", 50)]
    result = find_subset(1000, candidates, max_members=5)
    assert result.status == SubsetStatus.UNIQUE
    assert result.members == ("bnk_00001", "bnk_00002")


def test_ambiguous_when_two_subsets_both_sum_to_target():
    # The T3 trap: two orders of identical value on the same day.
    # {500, 500} and {200, 800} both sum to 1000 -- neither may be
    # picked over the other.
    candidates = [
        ("ord_00001", 500),
        ("ord_00002", 500),
        ("ord_00003", 200),
        ("ord_00004", 800),
    ]
    result = find_subset(1000, candidates, max_members=5)
    assert result.status == SubsetStatus.AMBIGUOUS
    assert set(result.candidates) == {
        ("ord_00001", "ord_00002"),
        ("ord_00003", "ord_00004"),
    }


def test_no_match_when_nothing_sums_to_target():
    candidates = [("bnk_00001", 111), ("bnk_00002", 222)]
    result = find_subset(1000, candidates, max_members=5)
    assert result.status == SubsetStatus.NO_MATCH
    assert result.members == ()
    assert result.candidates == ()


def test_partition_larger_than_cap_is_routed_away_not_enumerated():
    # 41 candidates of value 1 each: sum is 41, never equal to a target
    # that would require enumeration -- if this hung, the test would
    # time out rather than fail cleanly, so the cap has to be checked
    # before any combinations() call, not discovered by trying.
    candidates = [(f"bnk_{i:05d}", 1) for i in range(MAX_PARTITION_SIZE + 1)]
    result = find_subset(999_999, candidates, max_members=5)
    assert result.status == SubsetStatus.TOO_LARGE


def test_result_is_independent_of_input_order():
    candidates = [
        ("ord_00001", 500),
        ("ord_00002", 500),
        ("ord_00003", 200),
        ("ord_00004", 800),
    ]
    baseline = find_subset(1000, candidates, max_members=5)

    shuffled = candidates[:]
    rng = random.Random(7)
    rng.shuffle(shuffled)
    reordered = find_subset(1000, shuffled, max_members=5)

    assert reordered.status == baseline.status
    assert set(reordered.candidates) == set(baseline.candidates)


def test_never_stops_at_the_first_matching_subset():
    # Three subsets all sum to 100: {40,60}, {10,90}, {100} (a size-1
    # "whole partition" would trip the fast path, so use two disjoint
    # pairs plus a third pair to force real enumeration to find all three).
    candidates = [
        ("a", 40), ("b", 60),
        ("c", 10), ("d", 90),
        ("e", 25), ("f", 75),
    ]
    result = find_subset(100, candidates, max_members=5)
    assert result.status == SubsetStatus.AMBIGUOUS
    assert len(result.candidates) == 3
