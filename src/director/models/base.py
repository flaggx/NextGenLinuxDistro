"""Backend-neutral model interface.

Each backend owns its own conversation transcript in its native format, so
provider-specific state (e.g. thinking blocks that must be replayed verbatim)
never has to survive a round trip through a lowest-common-denominator format.
The agent loop only sees Turns and ToolCalls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ModelError(Exception):
    """A backend failure worth showing the user as one plain sentence.

    The request can be retried (network hiccup, rate limit, server error).
    """


class ModelSetupError(ModelError):
    """The backend can't work until the user fixes something (key, model name)."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Turn:
    """One model response."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # "end_turn", "tool_use", "max_tokens", "refusal", ...
    stop_reason: str = "end_turn"

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Conversation(Protocol):
    def send_user(self, text: str) -> Turn: ...
    def send_tool_results(self, results: list[ToolResult]) -> Turn: ...


class Model(Protocol):
    name: str

    def start(self, system: str, tools: list[ToolSpec]) -> Conversation: ...
