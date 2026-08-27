"""Hand-computed fixtures for domain/money.py's apply_bps and format_inr.

Every expected value here is computed on paper first, never derived from
the function under test itself.
"""

from plumb.domain.money import apply_bps, format_inr


def test_apply_bps_matches_hand_computed_case_with_no_rounding():
    # 1000 paise (Rs 10.00) at 15 bps (0.15%): 1000*15 = 15000; /10000 = 1.5
    # -> rounds up to 2 (half-up on the magnitude).
    assert apply_bps(1000, 15) == 2


def test_apply_bps_sign_handling_differs_from_naive_floor_division():
    # A Rs 5.00 refund (negative amount) taxed at the real 10 bps TDS rate.
    # Hand-computed: magnitude=500, 500*10=5000, exactly half a paisa;
    # round-half-up on the magnitude -> 1, sign applied -> -1.
    #
    # Naive floor division applied directly to the signed amount instead:
    # (-500*10+5000)//10000 = 0//10000 = 0 -- disagrees by exactly one
    # paisa, because Python's floor division rounds toward negative
    # infinity, which is round-half-DOWN for a negative amount, not
    # round-half-up on the magnitude.
    amount_paise = -500
    rate_bps = 10
    naive = (amount_paise * rate_bps + 5_000) // 10_000
    correct = apply_bps(amount_paise, rate_bps)
    assert correct == -1
    assert naive == 0
    assert correct != naive


def test_format_inr_small_amount():
    assert format_inr(120_000) == "₹1,200.00"


def test_format_inr_under_a_hundred_rupees_no_thousands_separator():
    assert format_inr(3_000) == "₹30.00"
    assert format_inr(418) == "₹4.18"


def test_format_inr_indian_digit_grouping_past_one_lakh():
    # 12,000,000 paise = Rs 1,20,000.00 -- Indian grouping (last 3, then
    # groups of 2): "120000" -> "1" + "20" + "000" -> "1,20,000"
    assert format_inr(12_000_000) == "₹1,20,000.00"


def test_format_inr_matches_the_uiux_brief_mockup_figure():
    # UIUX_BRIEF §3.1's own mockup: "31 findings  ₹47,300 at risk"
    assert format_inr(4_730_000) == "₹47,300.00"


def test_format_inr_negative_amount_is_signed():
    assert format_inr(-500) == "-₹5.00"


def test_format_inr_zero():
    assert format_inr(0) == "₹0.00"
