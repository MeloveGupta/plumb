"""NvidiaClient -- the Anthropic->OpenAI translation and the response
parse. Fully offline: a fake stands in for openai.OpenAI, no network,
no NVIDIA_API_KEY.
"""

import json
from types import SimpleNamespace

from plumb.agent.config import AgentConfig
from plumb.agent.model import NvidiaClient, ToolCall, _to_openai_messages, _to_openai_tool

_CFG = AgentConfig()


def test_tool_translation_anthropic_to_openai():
    anthropic_tool = {
        "name": "fetch_payment",
        "description": "a payment by id",
        "input_schema": {"type": "object", "properties": {"payment_id": {"type": "string"}}, "required": ["payment_id"]},
    }
    out = _to_openai_tool(anthropic_tool)
    assert out == {
        "type": "function",
        "function": {
            "name": "fetch_payment",
            "description": "a payment by id",
            "parameters": anthropic_tool["input_schema"],
        },
    }


def test_message_translation():
    messages = [
        {"role": "user", "content": "investigate exc_00001"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "checking the payment"},
                {"type": "tool_use", "id": "tu_1", "name": "fetch_payment", "input": {"payment_id": "pay_00001"}},
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": '{"amount_paise": 100}'}]},
        {"role": "user", "content": "Call one of the tools or submit_resolution."},
    ]
    out = _to_openai_messages(messages)
    assert out[0] == {"role": "user", "content": "investigate exc_00001"}
    assert out[1]["role"] == "assistant"
    assert out[1]["content"] == "checking the payment"
    assert out[1]["tool_calls"] == [
        {"id": "tu_1", "type": "function", "function": {"name": "fetch_payment", "arguments": '{"payment_id": "pay_00001"}'}}
    ]
    assert out[2] == {"role": "tool", "tool_call_id": "tu_1", "content": '{"amount_paise": 100}'}
    assert out[3] == {"role": "user", "content": "Call one of the tools or submit_resolution."}


class _FakeCompletions:
    def __init__(self, raw):
        self._raw = raw
        self.seen = None

    def create(self, **kwargs):
        self.seen = kwargs
        return self._raw


class _FakeOpenAI:
    def __init__(self, raw):
        self.chat = SimpleNamespace(completions=_FakeCompletions(raw))


def _raw_response(*, content, tool_calls, finish_reason):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content, tool_calls=tool_calls),
        )],
        usage=SimpleNamespace(prompt_tokens=640, completion_tokens=93),
    )


def _client_with(raw) -> NvidiaClient:
    c = NvidiaClient.__new__(NvidiaClient)
    c._client = _FakeOpenAI(raw)
    return c


def test_parses_a_tool_call_response():
    tc = SimpleNamespace(id="call-abc", function=SimpleNamespace(name="fetch_payment", arguments='{"payment_id":"pay_00001"}'))
    client = _client_with(_raw_response(content="", tool_calls=[tc], finish_reason="tool_calls"))

    resp = client.call("system prompt", [{"role": "user", "content": "go"}], [], _CFG)
    assert resp.stop_reason == "tool_calls"
    assert resp.tool_calls == [ToolCall(id="call-abc", name="fetch_payment", args={"payment_id": "pay_00001"})]
    assert resp.usage.input_tokens == 640 and resp.usage.output_tokens == 93


def test_parses_a_plain_text_response():
    client = _client_with(_raw_response(content="I need more information.", tool_calls=None, finish_reason="stop"))
    resp = client.call("sys", [{"role": "user", "content": "go"}], [], _CFG)
    assert resp.text == "I need more information."
    assert resp.tool_calls == []


def test_malformed_tool_args_degrade_not_crash():
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="fetch_payment", arguments="{not json"))
    client = _client_with(_raw_response(content="", tool_calls=[tc], finish_reason="tool_calls"))
    resp = client.call("sys", [{"role": "user", "content": "go"}], [], _CFG)
    assert resp.tool_calls[0].args == {"_raw": "{not json"}  # the loop's invoke() will ToolFailure this


def test_the_request_is_built_openai_shaped():
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="submit_resolution", arguments="{}"))
    client = _client_with(_raw_response(content="", tool_calls=[tc], finish_reason="tool_calls"))
    tools = [{"name": "fetch_payment", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    client.call("SYS", [{"role": "user", "content": "hi"}], tools, _CFG)

    sent = client._client.chat.completions.seen
    assert sent["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert sent["temperature"] == 0.0
    assert sent["messages"][0] == {"role": "system", "content": "SYS"}
    assert sent["tools"][0]["type"] == "function"
    assert "seed" not in sent  # non-negotiable 8 -- not engineered around
