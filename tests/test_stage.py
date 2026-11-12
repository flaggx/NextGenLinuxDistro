import json

import pytest

from director.permissions import Tier
from director.stage import SwayStage
from director.tools.base import ToolError
from director.tools import default_tools
from director.tools.stage import (
    ArrangeWindow, CloseWindow, FocusWindow, ListWindows, OpenOnStage, OpenShell, ShowTerminal, Zoom, show_backstage,
)

TREE = {
    "type": "root", "nodes": [{
        "type": "output", "nodes": [{
            "type": "workspace", "name": "1", "nodes": [
                {"type": "con", "id": 10, "pid": 100, "app_id": "director", "name": "director", "focused": True},
                {"type": "con", "id": 11, "pid": 101, "app_id": "org.pwmt.zathura", "name": "manual.pdf"},
            ],
            "floating_nodes": [{"type": "floating_con", "id": 12, "pid": 102, "app_id": None,
                                "window_properties": {"class": "Firefox"}, "name": "Mozilla Firefox"}],
        }],
    }],
}


class FakeSway:
    def __init__(self):
        self.commands = []

    def __call__(self, args):
        if args[:2] == ["-t", "get_tree"]:
            return json.dumps(TREE)
        self.commands.append(args)
        return "[{\"success\": true}]"


def test_list_windows():
    out = ListWindows(SwayStage(FakeSway())).run({})
    assert "id 10  workspace 1  director: director  (focused)" in out
    assert "id 11  workspace 1  org.pwmt.zathura: manual.pdf" in out
    assert "id 12  workspace 1  Firefox: Mozilla Firefox" in out


def test_open_local_file_freely_and_quoted(tmp_path):
    (tmp_path / "it's here.pdf").write_text("%PDF")
    sway = FakeSway()
    tool = OpenOnStage(SwayStage(sway), home=str(tmp_path))
    assert tool.tier({"target": "it's here.pdf"}) is Tier.FREE
    tool.run({"target": "it's here.pdf"})
    assert sway.commands == [["exec", "'xdg-open' '" + str(tmp_path) + "/it'\\''s here.pdf'"]]


def test_open_url_needs_approval():
    tool = OpenOnStage(SwayStage(FakeSway()))
    assert tool.tier({"target": "https://example.com"}) is Tier.APPROVE
    assert "browser" in tool.approval_request({"target": "https://example.com"}).summary


def test_open_refuses_programs_and_missing_files(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    tool = OpenOnStage(SwayStage(FakeSway()), home=str(tmp_path))
    with pytest.raises(ToolError, match="is a program"):
        tool.run({"target": "run.sh"})
    with pytest.raises(ToolError, match="not found"):
        tool.run({"target": "nope.pdf"})


def test_focus_arrange_close():
    sway = FakeSway()
    FocusWindow(SwayStage(sway)).run({"window_id": 11})
    ArrangeWindow(SwayStage(sway)).run({"window_id": 11, "layout": "tabbed"})
    CloseWindow(SwayStage(sway)).run({"window_id": 12})
    assert sway.commands == [["[con_id=11]", "focus"], ["[con_id=11]", "layout", "tabbed"], ["[con_id=12]", "kill"]]


def test_director_window_cant_be_closed_and_ids_are_checked():
    with pytest.raises(ToolError, match="director's own window"):
        CloseWindow(SwayStage(FakeSway())).run({"window_id": 10})
    with pytest.raises(ToolError, match="no window with id 99"):
        FocusWindow(SwayStage(FakeSway())).run({"window_id": 99})
    with pytest.raises(ToolError, match="layout must be"):
        ArrangeWindow(SwayStage(FakeSway())).run({"window_id": 11, "layout": "grid"})


def test_open_shell_in_home_or_a_folder(tmp_path):
    (tmp_path / "code").mkdir()
    sway = FakeSway()
    tool = OpenShell(SwayStage(sway), home=str(tmp_path))
    assert tool.tier({}) is Tier.FREE
    tool.run({})
    tool.run({"directory": "code"})
    assert sway.commands == [
        ["exec", f"'foot' '--working-directory' '{tmp_path}'"],
        ["exec", f"'foot' '--working-directory' '{tmp_path}/code'"],
    ]
    with pytest.raises(ToolError, match="not a folder"):
        tool.run({"directory": "nope"})


def test_zoom_scales_every_output_within_limits():
    sway = FakeSway()
    Zoom(SwayStage(sway)).run({"scale": 1.5})
    assert sway.commands == [["output", "*", "scale", "1.5"]]
    with pytest.raises(ToolError, match="between 0.5 and 3"):
        Zoom(SwayStage(sway)).run({"scale": 10})


def test_stage_tools_and_context_only_on_the_stage():
    names = [t.name for t in default_tools(stage=SwayStage(FakeSway()))]
    assert {"open_shell", "zoom", "list_windows"} <= set(names)
    assert "open_shell" not in [t.name for t in default_tools()]
    assert "Wayland" in SwayStage.context and "open_shell" in SwayStage.context


class FakeBackstage:
    def __init__(self):
        self.selected = []

    def attach_command(self):
        return ["tmux", "-L", "director", "new-session", "-A", "-s", "backstage"]

    def select(self, window):
        self.selected.append(window)

    def ensure(self):
        pass


def test_present_opens_or_focuses_by_app():
    sway = FakeSway()
    stage = SwayStage(sway)
    stage.present("org.pwmt.zathura", ["zathura"])  # already open: focus it
    stage.present("backstage", ["tmux", "attach"])  # not open: start it
    assert sway.commands == [['[app_id="org.pwmt.zathura"]', "focus"],
                             ["exec", "'foot' '--app-id' 'backstage' 'tmux' 'attach'"]]


def test_show_terminal_and_shown_commands_select_their_tab():
    sway, backstage = FakeSway(), FakeBackstage()
    stage = SwayStage(sway)
    ShowTerminal(stage, backstage).run({})
    show_backstage(stage, backstage, "@7")
    assert backstage.selected == ["@7"]
    assert all(cmd[0] == "exec" and "'--app-id' 'backstage' '--font=monospace:size=10'" in cmd[1]
               for cmd in sway.commands)


def test_show_terminal_only_with_backstage():
    stage = SwayStage(FakeSway())
    assert "show_terminal" not in [t.name for t in default_tools(stage=stage)]
    assert "show_terminal" in [t.name for t in default_tools(stage=stage, backstage=FakeBackstage())]
