from .base import Tool, ToolError
from .files import FindFiles, ReadFile
from .shell import RunCommand
from .software import software_tools
from .stage import show_backstage, stage_tools
from .undo import UndoLastChange


def default_tools(snapshots=None, stage=None, backstage=None, software=False) -> list[Tool]:
    # On the stage, commands run in the backstage terminal, which is shown on request.
    show = (lambda window: show_backstage(stage, backstage, window)) if stage and backstage else None
    shell = RunCommand(backstage=backstage, show=show)
    tools: list[Tool] = [shell, FindFiles(), ReadFile()]
    if software:  # NixOS: installing and running programs by name
        tools += software_tools(shell)
    if stage:
        tools += stage_tools(stage, backstage)
    if snapshots:
        tools.append(UndoLastChange(snapshots))
    return tools


__all__ = ["Tool", "ToolError", "FindFiles", "ReadFile", "RunCommand", "UndoLastChange", "default_tools", "stage_tools"]
