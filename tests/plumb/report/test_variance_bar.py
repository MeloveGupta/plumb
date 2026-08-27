"""UIUX_BRIEF §2.5 -- the variance bar. Hand-computed: every expected
string is worked out on paper first. Confirmed reading (not a
transcribed spec formula): solid bar = reconciled amount at full scale;
oxide-red overhang = delta scaled against the tolerance band
(delta/band_paise), sized on its own small fixed-width segment.

width=16, overhang_width=4 (module defaults). Every bar is always
16+4=20 characters total, whether reconciled or short, so rows in a
table stay aligned -- the reconciled case pads with blank space where
the overhang would be, rather than returning a shorter string.
"""

from plumb.report.cli import render_variance_bar, render_variance_row

_GREEN = "\033[38;2;47;95;74m"
_RED = "\033[38;2;168;50;30m"


def test_reconciled_exactly_is_a_full_bar_padded_to_the_same_total_width():
    assert render_variance_bar(0, 830, color=False) == "█" * 16 + " " * 4


def test_overpaid_is_also_a_full_bar_with_no_overhang():
    # delta <= 0 covers both "settled exactly" and "overpaid" -- neither
    # is money at risk.
    assert render_variance_bar(-500, 830, color=False) == "█" * 16 + " " * 4


def test_in_band_shortfall_overhang_proportional_to_the_band():
    # delta=500, band=830 -> fraction = 500/830 ~= 0.60241
    # overhang_chars = round(0.60241 * 4) = round(2.40964) = 2
    bar = render_variance_bar(500, 830, color=False)
    assert bar == "█" * 16 + "▏▏" + "  "  # 2 overhang chars + 2 blank


def test_shortfall_at_exactly_the_band_edge_fills_the_whole_overhang():
    # delta == band -> fraction = 1.0 -> overhang_chars = round(4) = 4
    bar = render_variance_bar(830, 830, color=False)
    assert bar == "█" * 16 + "▏" * 4


def test_shortfall_past_the_band_clamps_to_the_full_overhang():
    # delta=2000 > band=830 -> fraction clamped to 1.0, same as at-edge
    bar = render_variance_bar(2_000, 830, color=False)
    assert bar == "█" * 16 + "▏" * 4


def test_zero_band_treated_as_full_overhang_rather_than_dividing_by_zero():
    bar = render_variance_bar(1, 0, color=False)
    assert bar == "█" * 16 + "▏" * 4


def test_every_bar_is_the_same_total_length_reconciled_or_short():
    reconciled = render_variance_bar(0, 830, color=False)
    short = render_variance_bar(500, 830, color=False)
    assert len(reconciled) == len(short) == 20


def test_overhang_is_coloured_oxide_red_when_enabled():
    bar = render_variance_bar(500, 830, color=True)
    assert _RED in bar


def test_no_overhang_colour_when_reconciled():
    bar = render_variance_bar(0, 830, color=True)
    assert _RED not in bar


def test_variance_row_matches_the_uiux_brief_mockup_shape():
    # 500 paise = Rs 5.00. The row wraps render_variance_bar's own
    # output verbatim between two literal 3-space column separators --
    # built here by concatenation, not by eyeballing a space count.
    bar = "█" * 16 + "▏▏" + "  "  # round(500/830*4)=2 overhang chars + 2-space gap
    expected = "D01" + "  " + "ord_00042" + "   " + bar + "   " + "₹5.00 short"
    assert render_variance_row("D01", "ord_00042", 500, 830, color=False) == expected


def test_variance_row_for_a_clean_record_has_a_blank_defect_label():
    bar = "█" * 16 + " " * 4  # reconciled -- padded, no overhang
    expected = "   " + "  " + "ord_00088" + "   " + bar + "   " + "✓"
    assert render_variance_row("", "ord_00088", 0, 830, color=False) == expected
