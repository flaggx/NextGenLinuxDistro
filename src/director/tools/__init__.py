from ..stage import current_stage
from .base import Tool, ToolError
from .files import FindFiles, ReadFile
from .shell import RunCommand
from .stage import stage_tools
from .undo import UndoLastChange


def default_tools(snapshots=None) -> list[Tool]:
    tools: list[Tool] = [RunCommand(), FindFiles(), ReadFile()]
    if stage := current_stage():
        tools += stage_tools(stage)
    if snapshots:
        tools.append(UndoLastChange(snapshots))
    return tools


__all__ = ["Tool", "ToolError", "FindFiles", "ReadFile", "RunCommand", "UndoLastChange", "default_tools", "stage_tools"]
