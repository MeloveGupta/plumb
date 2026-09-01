"""P3 step 6 -- the ScriptedClient test double (the AnthropicClient live
path is exercised only in a local smoke run, never in CI)."""

import pytest

from plumb.agent.config import AgentConfig
from plumb.agent.model import ModelResponse, ScriptedClient, ToolCall, Usage


def test_scripted_client_returns_responses_in_order():
    r1 = ModelResponse(stop_reason="tool_use", tool_calls=[ToolCall("t1", "fetch_payment", {"payment_id": "pay_00001"})])
    r2 = ModelResponse(stop_reason="end_turn", text="done")
    client = ScriptedClient([r1, r2])
    cfg = AgentConfig()

    assert client.call("sys", [], [], cfg) is r1
    assert client.call("sys", [{"role": "user", "content": "x"}], [], cfg) is r2


def test_scripted_client_records_what_the_loop_asked():
    client = ScriptedClient([ModelResponse(stop_reason="end_turn")])
    client.call("the system prompt", [{"role": "user", "content": "hi"}], [{"name": "fetch_payment"}], AgentConfig())
    assert client.calls[0]["system"] == "the system prompt"
    assert client.calls[0]["tools"] == [{"name": "fetch_payment"}]


def test_scripted_client_raises_when_exhausted():
    client = ScriptedClient([ModelResponse(stop_reason="end_turn")])
    client.call("sys", [], [], AgentConfig())
    with pytest.raises(RuntimeError, match="exhausted"):
        client.call("sys", [], [], AgentConfig())


def test_model_response_defaults():
    r = ModelResponse(stop_reason="end_turn")
    assert r.text == ""
    assert r.tool_calls == []
    assert r.usage == Usage(0, 0)
