"""Keeps the director's window docked: full screen when it's alone on the
workspace, a strip along the bottom when anything else is open (the stage's
windows tile above it). It follows the user from workspace to workspace.

Docked, the director floats in the bottom strip and every workspace reserves
that strip with a bottom gap, so tiled windows never cover it. Run by Sway
at startup (`exec director-dock`, nixos/modules/stage.nix).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Iterator

from . import Swaymsg, swaymsg

APP_ID = "director"
DOCK_FRACTION = 0.3  # of the screen's height
MIN_DOCK_PX = 160


def _nodes(tree: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield tree
    for child in tree.get("nodes", []) + tree.get("floating_nodes", []):
        yield from _nodes(child)


def _windows(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in _nodes(node) if n.get("pid") and n.get("type") in ("con", "floating_con")]


def plan(tree: dict[str, Any], workspace: dict[str, Any], screen: dict[str, Any], gap: int) -> list[str]:
    """The sway commands that bring the director to `workspace` in the right shape.

    `workspace` is the focused one (from get_workspaces), `screen` its output's
    rect (unaffected by gaps), `gap` the bottom gap now set. Returns nothing when
    everything is already as it should be.
    """
    director = next((n for n in _windows(tree) if n.get("app_id") == APP_ID), None)
    if director is None:
        return []
    ws_node = next((n for n in _nodes(tree) if n.get("type") == "workspace" and n.get("name") == workspace["name"]), None)
    if ws_node is None:
        return []
    here = {n["id"] for n in _windows(ws_node)}
    others = [n for n in _windows(ws_node) if n["id"] != director["id"]]
    docked = director["type"] == "floating_con"
    target = f'[con_id={director["id"]}]'
    width, height = screen["width"], screen["height"]
    strip = max(MIN_DOCK_PX, int(height * DOCK_FRACTION))

    commands = []
    if director["id"] not in here and not docked:
        commands.append(f"{target} move container to workspace {json.dumps(workspace['name'])}")
    if others:
        if not docked:
            commands.append(f"{target} floating enable, sticky enable")
        if gap != strip:
            commands.append(f"gaps bottom all set {strip}")
        rect = director.get("rect", {})
        if not docked or rect.get("height") != strip or rect.get("width") != width:
            # Absolute: screen coordinates, not the workspace's (inset by gaps).
            commands.append(f"{target} resize set width {width} px height {strip} px, "
                            f"move absolute position {screen.get('x', 0)} px {screen.get('y', 0) + height - strip} px")
    elif docked:
        commands.append(f"{target} sticky disable, floating disable")
        if director["id"] not in here:
            commands.append(f"{target} move container to workspace {json.dumps(workspace['name'])}")
        commands.append("gaps bottom all set 0")
    elif gap:
        commands.append("gaps bottom all set 0")
    return commands


class Dock:
    def __init__(self, run: Swaymsg = swaymsg) -> None:
        self.swaymsg = run
        self.gap = 0

    def arrange(self) -> None:
        tree = json.loads(self.swaymsg(["-t", "get_tree", "-r"]))
        workspace = next((w for w in json.loads(self.swaymsg(["-t", "get_workspaces", "-r"])) if w.get("focused")), None)
        if workspace is None:
            return
        outputs = json.loads(self.swaymsg(["-t", "get_outputs", "-r"]))
        screen = next((o["rect"] for o in outputs if o.get("name") == workspace.get("output")), workspace["rect"])
        for command in plan(tree, workspace, screen, self.gap):
            self.swaymsg([command])
            if command.startswith("gaps bottom all set "):
                self.gap = int(command.rsplit(" ", 1)[1])


def main() -> int:
    dock = Dock()
    dock.arrange()
    events = subprocess.Popen(["swaymsg", "-t", "subscribe", "-m", '["window", "workspace"]'],
                              stdout=subprocess.PIPE, text=True)
    assert events.stdout is not None
    for line in events.stdout:
        event = json.loads(line)
        # Its own moves come back as events too; arrange() changes nothing the second time.
        if event.get("change") in ("new", "close", "move", "floating", "focus", "init", "empty"):
            try:
                dock.arrange()
            except Exception as e:  # sway restarting, a window gone mid-arrange: next event
                print(f"director-dock: {e}", file=sys.stderr)
    return events.wait()


if __name__ == "__main__":
    sys.exit(main())
