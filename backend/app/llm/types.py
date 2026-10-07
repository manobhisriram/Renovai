"""Provider-neutral message / tool types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Tier = Literal["simple", "medium", "complex"]
ToolChoice = Literal["auto", "any"] | str  # or a specific tool name


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class AssistantTurn:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None
    model: str = ""

    def blocks(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.text:
            out.append({"type": "text", "text": self.text})
        for tc in self.tool_calls:
            out.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
        return out


# Neutral message: {"role": "user"|"assistant", "content": str | list[block]}
# blocks: {"type":"text","text"} | {"type":"image","media_type","data"(base64)} |
#         {"type":"tool_use","id","name","input"} | {"type":"tool_result","tool_use_id","content","is_error"}
Message = dict[str, Any]


class LLMProvider(Protocol):
    name: str

    def chat_turn(
        self, *, model: str, system: str, messages: list[Message], tools: list[ToolSpec] | None = None,
        tool_choice: ToolChoice = "auto", max_tokens: int = 4096, task: str = "",
    ) -> AssistantTurn: ...
