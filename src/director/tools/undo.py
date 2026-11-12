from __future__ import annotations

from typing import Any

from ..permissions import ApprovalRequest, Tier
from ..undo import Change, Snapshots, last_request
from .base import Tool, ToolError, schema

MAX_LISTED = 10


class UndoLastChange(Tool):
    name = "undo_last_change"
    description = (
        "Undo everything you changed in the user's files for their most recent request, restoring "
        "them exactly as they were before it. Use when the user asks to undo, or when you notice "
        "you got something wrong. "
        "Doesn't cover system changes or files outside the home folder."
    )
    input_schema = schema({})
    snapshot = False  # undoing an undo would make "undo" mean "redo"

    def __init__(self, snapshots: Snapshots) -> None:
        self.snapshots = snapshots
        self._pending = None

    def tier(self, args: dict[str, Any]) -> Tier:
        return Tier.APPROVE  # undoing is a change too

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        changes = last_request(self.snapshots.changes())
        if not changes:
            raise ToolError("there's nothing to undo")
        self._pending = changes
        files = self.snapshots.changed_files(changes)
        listed = "\n".join(files[:MAX_LISTED]) + (f"\n... and {len(files) - MAX_LISTED} more" if len(files) > MAX_LISTED else "")
        return ApprovalRequest(
            tool=self.name,
            summary=f"undo {_describe(changes)}, putting {len(files)} file(s) back as they were",
            detail=listed or "(no files changed)",
        )

    def run(self, args: dict[str, Any]) -> str:
        changes = self._pending or last_request(self.snapshots.changes())
        if not changes:
            raise ToolError("there's nothing to undo")
        self._pending = None
        self.snapshots.undo(changes)
        return f"Undone: {_describe(changes)}"


def _describe(changes: list[Change]) -> str:
    first = f'"{changes[0].description}"'
    return first if len(changes) == 1 else f"{first} and {len(changes) - 1} more change(s) from the same request"
