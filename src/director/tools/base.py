from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from ..models.base import ToolSpec
from ..permissions import ApprovalRequest, Tier

MAX_OUTPUT_CHARS = 20_000


def schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Strict JSON schema: every property listed, no extras."""
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


class Tool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]
    # Approved runs are wrapped in undo snapshots unless this is False.
    snapshot: bool = True

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.input_schema)

    def refusal(self, args: dict[str, Any]) -> str | None:
        """Why this call must never run, even with approval; None if it may."""
        return None

    def tier(self, args: dict[str, Any]) -> Tier:
        return Tier.FREE

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        return ApprovalRequest(tool=self.name, summary=f"use {self.name}", detail=str(args))

    @abstractmethod
    def run(self, args: dict[str, Any]) -> str: ...


class ToolError(Exception):
    """Raised by a tool to report a failure back to the model."""


class StillRunning(Exception):
    """Raised by a tool whose action carries on after it returns (a program the
    user is using in the backstage terminal). `when_done(callback)` arranges for
    callback() to be called once it has finished: the undo snapshot waits for that.
    """

    def __init__(self, message: str, when_done: Callable[[Callable[[], None]], None]) -> None:
        super().__init__(message)
        self.message = message
        self.when_done = when_done
