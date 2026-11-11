"""The stage (roadmap step 2): programmatic control of the compositor.

The director opens, places and closes panes over compositor IPC. The first
target is Sway (`swaymsg`, i3-compatible IPC); Hyprland (`hyprctl`) could be a
second implementation of the same protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Pane:
    id: str
    title: str
    app: str


class Stage(Protocol):
    def list_panes(self) -> list[Pane]: ...
    def open(self, command: list[str]) -> Pane: ...
    def focus(self, pane_id: str) -> None: ...
    def close(self, pane_id: str) -> None: ...
    def layout(self, mode: str) -> None: ...  # e.g. "splith", "splitv", "tabbed"


class SwayStage:
    """Not implemented yet. Plan: wrap `swaymsg -t get_tree` / `swaymsg '[con_id=N] focus'`."""

    def __init__(self) -> None:
        raise NotImplementedError("Stage control lands in roadmap step 2.")
