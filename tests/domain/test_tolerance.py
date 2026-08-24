"""TRD §5.3 -- ToleranceProfile, hand-computed.

default_v1: amount_abs_paise=100, amount_rel_bps=10 (0.1%).
"""

from plumb.domain.tolerance import DEFAULT_V1, ToleranceProfile


def test_band_uses_absolute_floor_for_small_amounts():
    # Rs 10.00 = 1000 paise. 0.1% of that = 1 paise, well under the
    # Rs 1.00 (100 paise) absolute floor -- the floor wins.
    assert DEFAULT_V1.band_paise(1000) == 100


def test_band_uses_relative_share_for_large_amounts():
    # Rs 5,000.00 = 500000 paise. 0.1% of that = 500 paise, above the
    # 100-paise floor -- the relative share wins.
    assert DEFAULT_V1.band_paise(500_000) == 500


def test_within_true_at_exact_band_edge():
    # Inclusive at the edge -- LLD §5.3's own D02 example relies on this
    # not excluding the boundary case.
    assert DEFAULT_V1.within(500_000, 500_000 - 500) is True


def test_within_false_just_outside_band():
    assert DEFAULT_V1.within(500_000, 500_000 - 501) is False


def test_a_narrower_profile_has_a_narrower_band():
    narrow = ToleranceProfile("narrow", amount_abs_paise=1, amount_rel_bps=1, date_window_days=2)
    assert narrow.band_paise(500_000) < DEFAULT_V1.band_paise(500_000)
