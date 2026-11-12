"""Tools that let the director arrange the stage (see director/stage).

Everyday stage actions need no approval: opening the user's own files, focusing,
arranging and closing windows. Opening a web address sends data out, so it asks.
There is deliberately no "run any program" tool here: that would sidestep
run_command's permission checks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..backstage import Backstage
from ..permissions import ApprovalRequest, Tier
from ..stage import LAYOUTS, Pane, Stage, StageError
from .base import Tool, ToolError, schema

# The director's own conversation window, and the backstage terminal's
# (see nixos/modules/stage.nix).
DIRECTOR_APP_ID = "director"
BACKSTAGE_APP_ID = "backstage"

WINDOW_ID = {"type": "integer", "description": "Window id from list_windows."}


class StageTool(Tool):
    snapshot = False  # arranging windows doesn't touch files

    def __init__(self, stage: Stage) -> None:
        self.stage = stage

    def pane(self, window_id: int) -> Pane:
        for pane in self.stage.list_panes():
            if pane.id == str(window_id):
                return pane
        raise ToolError(f"no window with id {window_id}; list_windows shows what's open")

    def run(self, args: dict[str, Any]) -> str:
        try:
            return self.act(args)
        except StageError as e:
            raise ToolError(str(e)) from None

    def act(self, args: dict[str, Any]) -> str:
        raise NotImplementedError


class ListWindows(StageTool):
    name = "list_windows"
    description = "List the open windows: id, workspace, app and title, and which one has focus."
    input_schema = schema({})

    def act(self, args: dict[str, Any]) -> str:
        lines = [f"id {p.id}  workspace {p.workspace}  {p.app}: {p.title}" + ("  (focused)" if p.focused else "")
                 for p in self.stage.list_panes()]
        return "\n".join(lines) or "no windows open"


class OpenOnStage(StageTool):
    name = "open"
    description = (
        "Show a file or web page to the user in a new window, with their default app "
        "(a PDF viewer, an image viewer, the browser...). Local files open freely; "
        "web addresses ask the user first."
    )
    input_schema = schema({"target": {"type": "string", "description": "A file path ('~' allowed) or an http(s) URL."}})

    def __init__(self, stage: Stage, home: str | None = None) -> None:
        super().__init__(stage)
        self.home = Path(home or os.path.expanduser("~"))

    @staticmethod
    def _is_url(target: str) -> bool:
        return target.startswith(("http://", "https://"))

    def tier(self, args: dict[str, Any]) -> Tier:
        return Tier.APPROVE if self._is_url(args["target"]) else Tier.FREE

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        return ApprovalRequest(tool=self.name, summary=f"open {args['target']} in the browser", detail=args["target"])

    def act(self, args: dict[str, Any]) -> str:
        target = args["target"]
        if not self._is_url(target):
            path = Path(os.path.expanduser(target))
            path = path if path.is_absolute() else self.home / path
            if not path.exists():
                raise ToolError(f"not found: {path}")
            if path.is_file() and os.access(path, os.X_OK):
                raise ToolError(f"{path} is a program; opening it would run it. Use run_command instead.")
            target = str(path)
        self.stage.open(["xdg-open", target])
        return f"Opened {target}"


class FocusWindow(StageTool):
    name = "focus_window"
    description = "Bring a window to the front. Get ids from list_windows."
    input_schema = schema({"window_id": WINDOW_ID})

    def act(self, args: dict[str, Any]) -> str:
        self.stage.focus(self.pane(args["window_id"]).id)
        return "Focused."


class CloseWindow(StageTool):
    name = "close_window"
    description = "Close a window, as if the user clicked its close button (the app can still ask to save)."
    input_schema = schema({"window_id": WINDOW_ID})

    def act(self, args: dict[str, Any]) -> str:
        pane = self.pane(args["window_id"])
        if pane.app == DIRECTOR_APP_ID:
            raise ToolError("that's the director's own window; it stays open")
        self.stage.close(pane.id)
        return "Closed."


class ArrangeWindow(StageTool):
    name = "arrange_window"
    description = (
        "Change how a window shares the screen with its neighbours: side by side (splith), "
        "stacked top to bottom (splitv), as tabs (tabbed), or as a stack of title bars (stacking)."
    )
    input_schema = schema({
        "window_id": WINDOW_ID,
        "layout": {"type": "string", "enum": list(LAYOUTS), "description": "splith, splitv, tabbed or stacking."},
    })

    def act(self, args: dict[str, Any]) -> str:
        self.stage.layout(self.pane(args["window_id"]).id, args["layout"])
        return f"Arranged as {args['layout']}."


class OpenShell(StageTool):
    name = "open_shell"
    description = (
        "Open a terminal window for the user to type in (backstage). Use when they ask for "
        "a shell or terminal, or want to run something interactive themselves."
    )
    input_schema = schema({"directory": {"type": "string", "description": "Folder to start in (default: home)."}},
                          required=[])

    def __init__(self, stage: Stage, home: str | None = None) -> None:
        super().__init__(stage)
        self.home = Path(home or os.path.expanduser("~"))

    def act(self, args: dict[str, Any]) -> str:
        path = Path(os.path.expanduser(args.get("directory") or str(self.home)))
        path = path if path.is_absolute() else self.home / path
        if not path.is_dir():
            raise ToolError(f"not a folder: {path}")
        self.stage.open_shell(str(path))
        return f"Opened a terminal in {path}."


class Zoom(StageTool):
    name = "zoom"
    description = (
        "Make everything on screen bigger or smaller, text included: 1.0 is normal, "
        "1.5 is half again as big, up to 3. Use when the user finds things too small or too big."
    )
    input_schema = schema({"scale": {"type": "number", "description": "1.0 normal; e.g. 1.25, 1.5, 2."}})

    def act(self, args: dict[str, Any]) -> str:
        self.stage.scale(float(args["scale"]))
        return f"Everything is now shown at {args['scale']:g}x."


class ShowTerminal(StageTool):
    name = "show_terminal"
    description = (
        "Show the backstage terminal: where your commands run, one tab each, and the user's "
        "own shell. Use when the user asks to see the terminal or what you ran."
    )
    input_schema = schema({})

    def __init__(self, stage: Stage, backstage: Backstage) -> None:
        super().__init__(stage)
        self.backstage = backstage

    def act(self, args: dict[str, Any]) -> str:
        show_backstage(self.stage, self.backstage)
        return "The backstage terminal is on screen."


def show_backstage(stage: Stage, backstage: Backstage, window: str | None = None) -> None:
    """Put the backstage terminal on screen, on `window`'s tab if given."""
    backstage.ensure()  # set up by the director, not by the terminal attaching to it
    if window:
        backstage.select(window)
    stage.present(BACKSTAGE_APP_ID, backstage.attach_command())


def stage_tools(stage: Stage, backstage: Backstage | None = None) -> list[Tool]:
    tools: list[Tool] = [ListWindows(stage), OpenOnStage(stage), OpenShell(stage), Zoom(stage),
                         FocusWindow(stage), CloseWindow(stage), ArrangeWindow(stage)]
    if backstage:
        tools.append(ShowTerminal(stage, backstage))
    return tools
