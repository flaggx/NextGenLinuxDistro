from .base import Tool, ToolError
from .files import FindFiles, ReadFile
from .shell import RunCommand
from .stage import show_backstage, stage_tools
from .undo import UndoLastChange


def default_tools(snapshots=None, stage=None, backstage=None) -> list[Tool]:
    # On the stage, commands run in the backstage terminal, which is shown on request.
    show = (lambda window: show_backstage(stage, backstage, window)) if stage and backstage else None
    tools: list[Tool] = [RunCommand(backstage=backstage, show=show), FindFiles(), ReadFile()]
    if stage:
        tools += stage_tools(stage, backstage)
    if snapshots:
        tools.append(UndoLastChange(snapshots))
    return tools


__all__ = ["Tool", "ToolError", "FindFiles", "ReadFile", "RunCommand", "UndoLastChange", "default_tools", "stage_tools"]
