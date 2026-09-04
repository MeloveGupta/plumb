"""P3 step 1 -- AgentConfig (LLD §10) and the L3 error classes (LLD §9).

The default threshold values asserted here are the ones chosen in
agent/config.py's docstring, not values derived from any code under
test -- they are constants with a stated rationale, pinned so a silent
change to "what autonomy is granted under" shows up as a test diff.
"""

import pytest
from pydantic import ValidationError

from plumb.agent.config import AgentConfig
from plumb.errors import BudgetExhausted, FabricationError, PlumbError, ToolError


def test_agent_config_defaults():
    cfg = AgentConfig()
    assert cfg.max_iterations == 8
    assert cfg.token_budget == 60_000
    assert cfg.reserve_tokens == 4_000
    assert cfg.auto_resolve_threshold_paise == 10_000
    assert cfg.confidence_threshold_bps == 9_000
    assert cfg.model == "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_agent_config_rejects_unknown_key():
    with pytest.raises(ValidationError):
        AgentConfig(temperature=0.7)  # not a field -- extra="forbid"


def test_agent_config_is_frozen():
    cfg = AgentConfig()
    with pytest.raises(ValidationError):
        cfg.token_budget = 1


def test_agent_config_overrides_take():
    cfg = AgentConfig(token_budget=1_000, confidence_threshold_bps=5_000)
    assert cfg.token_budget == 1_000
    assert cfg.confidence_threshold_bps == 5_000
    assert cfg.max_iterations == 8  # untouched


def test_fabrication_error_carries_the_offending_key():
    err = FabricationError("exc_00007", "pay_99999")
    assert err.exception_id == "exc_00007"
    assert err.record_key == "pay_99999"
    assert "pay_99999" in str(err)
    assert "exc_00007" in str(err)


def test_l3_errors_are_plumb_errors():
    for cls in (ToolError, BudgetExhausted, FabricationError):
        assert issubclass(cls, PlumbError)
