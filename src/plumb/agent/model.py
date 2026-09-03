"""TRD §7.1 -- the model client, a hand-rolled Anthropic Messages API
tool loop with no framework between us and the thing we are measuring.

`ModelClient` is the seam. The loop (loop.py) talks only to this
protocol. Four implementations:
- `AnthropicClient` -- live path, needs ANTHROPIC_API_KEY, never in CI.
- `ScriptedClient` -- deterministic in-process double for loop tests.
- `CassetteClient` -- replay from `fixtures/llm/` (TRD §9.1). What CI
  and `plumb run --ablation hybrid` (default) use. A miss is a
  CassetteMiss telling the maintainer to re-record.
- `RecordingClient` -- wraps AnthropicClient, writes cassettes.
  `plumb run --ablation hybrid --record`.
CI runs with no API key and no network -- the loop tests use
ScriptedClient, the cassette test uses a fake inner client, and any
real hybrid replay uses committed fixtures.

`TEMPERATURE` is a constant, not an AgentConfig field -- L3 determinism
is a finding to report, not a knob to turn (non-negotiable 8), and a
`float` field would trip the no-float lint (see config.py's note).
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
        response = self._inner.call(system, messages, tools, cfg)
        self._dir.mkdir(parents=True, exist_ok=True)
        key = _request_key(system, messages, tools, cfg.model)
        (self._dir / f"{key}.json").write_text(
            json.dumps(_response_to_dict(response), indent=2, sort_keys=True) + "\n"
        )
        return response


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
