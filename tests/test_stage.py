import json

import pytest

from director.permissions import Tier
from director.stage import SwayStage
from director.tools.base import ToolError
from director.tools.stage import ArrangeWindow, CloseWindow, FocusWindow, ListWindows, OpenOnStage

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
