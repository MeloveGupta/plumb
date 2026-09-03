"""P3.10 -- the cassette record/replay layer. All offline: RecordingClient
wraps a fake inner client, never the real API. This is what keeps CI
green with no ANTHROPIC_API_KEY (TRD §9.1).
"""

import pytest

from plumb.agent.config import AgentConfig
from plumb.agent.model import (
    CassetteClient,
    ModelResponse,
    RecordingClient,
    ToolCall,
    Usage,
    _request_key,
)
from plumb.errors import CassetteMiss

_CFG = AgentConfig()


class _FakeInner:
    """Stands in for AnthropicClient -- returns a fixed response, records nothing."""

    def __init__(self, response: ModelResponse) -> None:
        self._response = response
        self.calls = 0

    def call(self, system, messages, tools, cfg) -> ModelResponse:
        self.calls += 1
        return self._response


def test_request_key_is_stable_and_discriminating():
    a = _request_key("sys", [{"role": "user", "content": "x"}], [{"name": "t"}], "claude-sonnet-5")
    b = _request_key("sys", [{"role": "user", "content": "x"}], [{"name": "t"}], "claude-sonnet-5")
    assert a == b and len(a) == 64
    assert a != _request_key("SYS", [{"role": "user", "content": "x"}], [{"name": "t"}], "claude-sonnet-5")
    assert a != _request_key("sys", [{"role": "user", "content": "y"}], [{"name": "t"}], "claude-sonnet-5")
    assert a != _request_key("sys", [{"role": "user", "content": "x"}], [{"name": "u"}], "claude-sonnet-5")
    assert a != _request_key("sys", [{"role": "user", "content": "x"}], [{"name": "t"}], "claude-opus-5")


def test_record_then_replay_round_trips(tmp_path):
    response = ModelResponse(
        stop_reason="tool_use",
        text="looking into it",
        tool_calls=[ToolCall(id="tu_1", name="fetch_payment", args={"payment_id": "pay_00001"})],
        usage=Usage(input_tokens=1200, output_tokens=80),
    )
    inner = _FakeInner(response)
    recorder = RecordingClient(inner, tmp_path)

    system, messages, tools = "the system prompt", [{"role": "user", "content": "investigate exc_00001"}], [{"name": "fetch_payment"}]
    recorded = recorder.call(system, messages, tools, _CFG)
    assert recorded == response and inner.calls == 1

    replayer = CassetteClient(tmp_path)
    replayed = replayer.call(system, messages, tools, _CFG)
    assert replayed == response
    # replay does not touch the inner client
    assert inner.calls == 1


def test_cassette_miss_raises_with_the_re_record_instruction(tmp_path):
    replayer = CassetteClient(tmp_path)  # empty dir
    with pytest.raises(CassetteMiss, match="Re-record") as excinfo:
        replayer.call("sys", [], [], _CFG)
    assert "plumb run --ablation hybrid --record" in str(excinfo.value)
    assert "Oops" not in str(excinfo.value) and "!" not in str(excinfo.value)


def test_replay_is_keyed_on_the_request_not_call_order(tmp_path):
    r1 = ModelResponse(stop_reason="tool_use", tool_calls=[ToolCall("a", "fetch_payment", {"payment_id": "pay_00001"})])
    r2 = ModelResponse(stop_reason="end_turn", text="done")
    RecordingClient(_FakeInner(r1), tmp_path).call("s", [{"role": "user", "content": "1"}], [], _CFG)
    RecordingClient(_FakeInner(r2), tmp_path).call("s", [{"role": "user", "content": "2"}], [], _CFG)

    replayer = CassetteClient(tmp_path)
    # ask for the second request first -- still gets r2
    assert replayer.call("s", [{"role": "user", "content": "2"}], [], _CFG) == r2
    assert replayer.call("s", [{"role": "user", "content": "1"}], [], _CFG) == r1
