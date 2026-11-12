from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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
