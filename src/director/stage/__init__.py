"""The stage (roadmap step 2): programmatic control of the compositor.

The director opens, places and closes panes over compositor IPC. The first
target is Sway (`swaymsg`, i3-compatible IPC); Hyprland (`hyprctl`) could be a
second implementation of the same protocol.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Protocol

LAYOUTS = ("splith", "splitv", "tabbed", "stacking")


class StageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pane:
    id: str
    title: str
    app: str
    workspace: str = ""
    focused: bool = False


class Stage(Protocol):
    def list_panes(self) -> list[Pane]: ...
    def open(self, command: list[str]) -> None: ...
    def focus(self, pane_id: str) -> None: ...
    def close(self, pane_id: str) -> None: ...
    def layout(self, pane_id: str, mode: str) -> None: ...  # one of LAYOUTS


Swaymsg = Callable[[list[str]], str]


def swaymsg(args: list[str]) -> str:
    proc = subprocess.run(["swaymsg", *args], capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        raise StageError((proc.stderr or proc.stdout).strip() or "swaymsg failed")
    return proc.stdout


def _windows(tree: dict[str, Any], workspace: str = "") -> Iterator[tuple[dict[str, Any], str]]:
    if tree.get("type") == "workspace":
        workspace = tree.get("name", "")
    if tree.get("pid") and tree.get("type") in ("con", "floating_con"):
        yield tree, workspace
    for child in tree.get("nodes", []) + tree.get("floating_nodes", []):
        yield from _windows(child, workspace)


def _quote(word: str) -> str:
    return "'" + word.replace("'", "'\\''") + "'"


class SwayStage:
    def __init__(self, run: Swaymsg = swaymsg) -> None:
        self.swaymsg = run

    def list_panes(self) -> list[Pane]:
        tree = json.loads(self.swaymsg(["-t", "get_tree", "-r"]))
        return [
            Pane(
                id=str(node["id"]),
                title=node.get("name") or "",
                app=node.get("app_id") or (node.get("window_properties") or {}).get("class") or "?",
                workspace=workspace,
                focused=bool(node.get("focused")),
            )
            for node, workspace in _windows(tree)
        ]

    def open(self, command: list[str]) -> None:
        # swaymsg exec takes one shell string.
        self.swaymsg(["exec", " ".join(_quote(w) for w in command)])

    def focus(self, pane_id: str) -> None:
        self.swaymsg([f"[con_id={int(pane_id)}]", "focus"])

    def close(self, pane_id: str) -> None:
        self.swaymsg([f"[con_id={int(pane_id)}]", "kill"])

    def layout(self, pane_id: str, mode: str) -> None:
        if mode not in LAYOUTS:
            raise StageError(f"layout must be one of {', '.join(LAYOUTS)}")
        self.swaymsg([f"[con_id={int(pane_id)}]", "layout", mode])


def current_stage() -> Stage | None:
    """The compositor the director is running under, if it can control it."""
    return SwayStage() if os.environ.get("SWAYSOCK") else None
