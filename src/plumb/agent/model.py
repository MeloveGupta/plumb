"""TRD §7.1 -- the model client, a hand-rolled Anthropic Messages API
tool loop with no framework between us and the thing we are measuring.

`ModelClient` is the seam. The loop (loop.py) talks only to this
protocol; `AnthropicClient` is the live path, `ScriptedClient` is the
deterministic in-process double every loop test uses so CI runs with no
API key and no network (TRD §9.1). The cassette record/replay client
(TRD §9.1, `fixtures/llm/`) is a later task (P3.10) and slots in here as
a third implementation.

`TEMPERATURE` is a constant, not an AgentConfig field -- L3 determinism
is a finding to report, not a knob to turn (non-negotiable 8), and a
`float` field would trip the no-float lint (see config.py's note).
"""

import os
from dataclasses import dataclass, field
from typing import Protocol

from plumb.agent.config import AgentConfig

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
