"""LLD §5.4 -- the re-evaluation mechanism itself. Hand-computed: every
expected value here is worked on paper first, never derived by calling
the evaluator and trusting its own output.
"""

import pytest

from plumb.verify.trace import RecomputeStep, RecomputeTrace, reevaluate_step, reevaluate_trace


def test_simple_subtraction_reevaluates():
    step = RecomputeStep(1, "delta", "expected - actual", {"expected": 830_000, "actual": 829_500}, 500)
    assert reevaluate_step(step) == 500


def test_bps_application_reevaluates():
    # (200_000 * 1500 + 5000) // 10000 = (300_000_000 + 5000) // 10000 = 30_000
    step = RecomputeStep(1, "commission", "(gross_paise * rate_bps + 5000) // 10000", {"gross_paise": 200_000, "rate_bps": 1500}, 30_000)
    assert reevaluate_step(step) == 30_000


def test_abs_min_max_reevaluate():
    assert reevaluate_step(RecomputeStep(1, "x", "abs(a - b)", {"a": 5, "b": 12}, 7)) == 7
    assert reevaluate_step(RecomputeStep(1, "x", "min(a, b)", {"a": 5, "b": 12}, 5)) == 5
    assert reevaluate_step(RecomputeStep(1, "x", "max(a, b)", {"a": 5, "b": 12}, 12)) == 12


def test_a_step_whose_output_does_not_match_its_own_formula_fails():
    """The standing rule: demonstrated failing on a real violation, not
    just asserted correct by reading the code."""
    lying_step = RecomputeStep(1, "delta", "expected - actual", {"expected": 830_000, "actual": 829_500}, 999_999)
    with pytest.raises(AssertionError, match="evaluates to 500"):
        reevaluate_trace(RecomputeTrace(steps=(lying_step,), conclusion="test"))


def test_a_name_missing_from_inputs_raises_rather_than_defaulting():
    step = RecomputeStep(1, "x", "a + b", {"a": 5}, 5)
    with pytest.raises(KeyError):
        reevaluate_step(step)


def test_an_unsupported_expression_shape_raises():
    step = RecomputeStep(1, "x", "a ** b", {"a": 2, "b": 3}, 8)
    with pytest.raises(ValueError, match="unsupported expression"):
        reevaluate_step(step)


def test_reevaluate_trace_passes_on_a_chain_of_correct_steps():
    steps = (
        RecomputeStep(1, "commission", "(gross_paise * rate_bps + 5000) // 10000", {"gross_paise": 200_000, "rate_bps": 1500}, 30_000),
        RecomputeStep(2, "expected_transfer", "gross_paise - commission", {"gross_paise": 200_000, "commission": 30_000}, 170_000),
    )
    reevaluate_trace(RecomputeTrace(steps=steps, conclusion="test"))  # must not raise
