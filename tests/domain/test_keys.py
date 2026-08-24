"""BACKEND_SCHEMA.md §1.2 -- IdSequence, the engine's own id counter."""

from plumb.domain.keys import IdSequence


def test_ids_are_sequential_and_zero_padded_per_prefix():
    ids = IdSequence()
    assert ids.next("raw") == "raw_00001"
    assert ids.next("raw") == "raw_00002"
    assert ids.next("raw") == "raw_00003"


def test_counters_are_independent_per_prefix():
    ids = IdSequence()
    assert ids.next("raw") == "raw_00001"
    assert ids.next("xfm") == "xfm_00001"
    assert ids.next("raw") == "raw_00002"
