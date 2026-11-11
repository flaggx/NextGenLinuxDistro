from .base import Tool, ToolError
from .files import FindFiles, ReadFile
from .shell import RunCommand


def default_tools() -> list[Tool]:
    return [RunCommand(), FindFiles(), ReadFile()]


__all__ = ["Tool", "ToolError", "FindFiles", "ReadFile", "RunCommand", "default_tools"]
