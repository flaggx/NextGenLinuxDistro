from __future__ import annotations

from typing import Any

from ..permissions import ApprovalRequest, Tier
from ..undo import Snapshots
from .base import Tool, ToolError, schema

MAX_LISTED = 10


class UndoLastChange(Tool):
    name = "undo_last_change"
    description = (
        "Undo the most recent change you made to the user's files, restoring them exactly as they "
        "were before it. Use when the user asks to undo, or when you notice you got something wrong. "
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
        changes = self.snapshots.changes()
        if not changes:
            raise ToolError("there's nothing to undo")
        self._pending = change = changes[-1]
        files = self.snapshots.changed_files(change)
        listed = "\n".join(files[:MAX_LISTED]) + (f"\n... and {len(files) - MAX_LISTED} more" if len(files) > MAX_LISTED else "")
        return ApprovalRequest(
            tool=self.name,
            summary=f"undo \"{change.description}\", putting {len(files)} file(s) back as they were",
            detail=listed or "(no files changed)",
        )

    def run(self, args: dict[str, Any]) -> str:
        change = self._pending or (self.snapshots.changes() or [None])[-1]
        if change is None:
            raise ToolError("there's nothing to undo")
        self._pending = None
        self.snapshots.undo(change)
        return f"Undone: {change.description}"
