"""TRD §7.1 -- the model client, a hand-rolled tool loop with no
framework between us and the thing we are measuring.

`ModelClient` is the seam. The loop (loop.py) talks only to this
protocol and builds Anthropic-shaped messages. Five implementations:
- `NvidiaClient` -- live path. build.nvidia.com, OpenAI-compatible
  chat/completions; translates the loop's Anthropic-shaped messages/
  tools on the way out. Needs `NVIDIA_API_KEY`. Never in CI.
- `AnthropicClient` -- the original live path, kept as the "swap back
  with an Anthropic key" route (TRD §14). Needs `ANTHROPIC_API_KEY`.
- `ScriptedClient` -- deterministic in-process double for loop tests.
- `CassetteClient` -- replay from `fixtures/llm/` (TRD §9.1). What CI
  and `plumb run --ablation hybrid` (default) use. A miss is a
  CassetteMiss telling the maintainer to re-record.
- `RecordingClient` -- wraps a live client, writes cassettes; skips the
  call when a cassette already exists (so `--record` resumes).
CI runs with no API key and no network -- the loop tests use
ScriptedClient, the cassette test uses a fake inner client, and any
real hybrid replay uses committed fixtures.

# TRD-DEVIATION: TRD §7.1 / LLD §7 specify the Anthropic Messages API,
# default `claude-sonnet-5`. Built against build.nvidia.com
# (`nvidia/nemotron-3.5-lightning-30b-a3b`, OpenAI-compatible) instead --
# the Anthropic key was unavailable at build time; the NVIDIA one was.
# Only the client changed: the loop, the gates, the tools, and the
# structured `submit_resolution` output are all provider-neutral. See
# ARCHITECTURE.md. `AnthropicClient` stays for the swap-back.

`TEMPERATURE` is a constant, not an AgentConfig field -- L3 determinism
is a finding to report, not a knob to turn (non-negotiable 8), and a
`float` field would trip the no-float lint (see config.py's note). No
`seed` is passed even though NVIDIA NIM accepts one -- forcing
bit-reproducibility would be engineering around the finding.
"""

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from plumb.agent.config import AgentConfig
from plumb.errors import CassetteMiss

TEMPERATURE = 0.0


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass(frozen=True)
class ModelResponse:
    """One assistant turn. `stop_reason` is Anthropic's own string
    ("tool_use", "end_turn", "max_tokens", ...). `tool_calls` is every
    tool_use block in the turn; `text` is the concatenated prose."""

    stop_reason: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=lambda: Usage(0, 0))


class ModelClient(Protocol):
    def call(
        self, system: str, messages: list[dict], tools: list[dict], cfg: AgentConfig
    ) -> ModelResponse: ...


class ScriptedClient:
    """Returns pre-built responses in order. Ignores its inputs. The
    test double for the loop -- deterministic, offline."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[dict] = []  # what the loop asked, for assertions

    def call(
        self, system: str, messages: list[dict], tools: list[dict], cfg: AgentConfig
    ) -> ModelResponse:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if self._index >= len(self._responses):
            raise RuntimeError(
                f"ScriptedClient exhausted after {self._index} responses -- "
                f"the loop asked for one more"
            )
        response = self._responses[self._index]
        self._index += 1
        return response


def _request_key(system: str, messages: list[dict], tools: list[dict], model: str) -> str:
    """sha256 over the request that determines the response. TEMPERATURE
    is a module constant (always 0.0), so it isn't part of the key --
    the same (system, messages, tools, model) always replays the same
    cassette. `default=str` handles anything non-JSON in a tool result
    that ended up in messages."""
    payload = json.dumps([system, messages, tools, model], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _response_to_dict(r: ModelResponse) -> dict:
    return {
        "stop_reason": r.stop_reason,
        "text": r.text,
        "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in r.tool_calls],
        "usage": {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens},
    }


def _response_from_dict(d: dict) -> ModelResponse:
    return ModelResponse(
        stop_reason=d["stop_reason"],
        text=d.get("text", ""),
        tool_calls=[ToolCall(id=c["id"], name=c["name"], args=c["args"]) for c in d.get("tool_calls", [])],
        usage=Usage(d["usage"]["input_tokens"], d["usage"]["output_tokens"]),
    )


class CassetteClient:
    """Replay path -- TRD §9.1. Looks up a recorded ModelResponse by
    request key under `cassette_dir`. A miss raises CassetteMiss: CI
    runs in replay, so a miss means the committed cassettes are stale.
    This is the third ModelClient implementation (TRD §14's "no
    abstraction with one implementation" is satisfied by Scripted +
    Anthropic already)."""

    def __init__(self, cassette_dir: Path) -> None:
        self._dir = Path(cassette_dir)

    def call(
        self, system: str, messages: list[dict], tools: list[dict], cfg: AgentConfig
    ) -> ModelResponse:
        key = _request_key(system, messages, tools, cfg.model)
        path = self._dir / f"{key}.json"
        if not path.exists():
            raise CassetteMiss(key)
        return _response_from_dict(json.loads(path.read_text()))


class RecordingClient:
    """Record path -- wraps a live client (AnthropicClient), returns its
    response, and writes it to `cassette_dir` keyed by request. Used by
    `plumb run --ablation hybrid --record`."""

    def __init__(self, inner: "ModelClient", cassette_dir: Path) -> None:
        self._inner = inner
        self._dir = Path(cassette_dir)

    def call(
        self, system: str, messages: list[dict], tools: list[dict], cfg: AgentConfig
    ) -> ModelResponse:
        key = _request_key(system, messages, tools, cfg.model)
        path = self._dir / f"{key}.json"
        if path.exists():  # resume: a cassette already recorded is not re-paid for
            return _response_from_dict(json.loads(path.read_text()))
        response = self._inner.call(system, messages, tools, cfg)
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_response_to_dict(response), indent=2, sort_keys=True) + "\n")
        return response


# --- Anthropic <-> OpenAI translation (the loop speaks Anthropic) --------------


def _to_openai_tool(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": msg["role"], "content": content})
            continue
        # list content: either an assistant turn (text + tool_use) or a
        # user turn carrying tool_result blocks.
        if msg["role"] == "assistant":
            text = "".join(b["text"] for b in content if b.get("type") == "text")
            tool_calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                }
                for b in content
                if b.get("type") == "tool_use"
            ]
            entry: dict = {"role": "assistant", "content": text or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
        else:
            for b in content:
                if b.get("type") == "tool_result":
                    out.append(
                        {"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]}
                    )
    return out


class NvidiaClient:
    """Live path against build.nvidia.com's OpenAI-compatible
    chat/completions. `openai` is imported lazily so this module stays
    importable offline. Retries (429 / 5xx / connection) are the SDK's
    own -- `max_retries`."""

    def __init__(self, *, api_key: str | None = None, base_url: str = "https://integrate.api.nvidia.com/v1") -> None:
        import openai

        self._client = openai.OpenAI(
            api_key=api_key or os.environ["NVIDIA_API_KEY"], base_url=base_url, max_retries=4
        )

    def call(
        self, system: str, messages: list[dict], tools: list[dict], cfg: AgentConfig
    ) -> ModelResponse:
        raw = self._client.chat.completions.create(
            model=cfg.model,
            temperature=TEMPERATURE,
            max_tokens=cfg.max_output_tokens,
            messages=[{"role": "system", "content": system}, *_to_openai_messages(messages)],
            tools=[_to_openai_tool(t) for t in tools],
            tool_choice="auto",
        )
        choice = raw.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}  # malformed -> the loop degrades it
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
        return ModelResponse(
            stop_reason=choice.finish_reason or "stop",
            text=message.content or "",  # nemotron's reasoning_content is deliberately dropped
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=raw.usage.prompt_tokens if raw.usage else 0,
                output_tokens=raw.usage.completion_tokens if raw.usage else 0,
            ),
        )


class AnthropicClient:
    """The live path. Constructed only when ANTHROPIC_API_KEY is set;
    never in CI. `anthropic` is imported lazily so this module stays
    importable and the offline guarantee stays structural."""

    def __init__(self, *, api_key: str | None = None) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])

    def call(
        self, system: str, messages: list[dict], tools: list[dict], cfg: AgentConfig
    ) -> ModelResponse:
        raw = self._client.messages.create(
            model=cfg.model,
            max_tokens=cfg.max_output_tokens,
            temperature=TEMPERATURE,
            system=system,
            messages=messages,
            tools=tools,
        )
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in raw.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input)))
        return ModelResponse(
            stop_reason=raw.stop_reason or "end_turn",
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=Usage(input_tokens=raw.usage.input_tokens, output_tokens=raw.usage.output_tokens),
        )
