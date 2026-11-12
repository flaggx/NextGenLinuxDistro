"""Backstage against a real tmux, each test on its own tmux server."""

import subprocess
import threading
import uuid

import pytest

from director.agent import Director
from director.backstage import Backstage, Finished, Running
from director.models.base import ToolCall, Turn
from director.tools import RunCommand
from director.tools.base import ToolError
from director.undo import Snapshots

from test_agent import ScriptedModel
from test_undo import FakeSnapper

pytestmark = pytest.mark.skipif(not Backstage.available(), reason="needs tmux")


@pytest.fixture
def backstage(tmp_path):
    b = Backstage(home=str(tmp_path), socket=f"director-test-{uuid.uuid4().hex[:8]}")
    yield b
    subprocess.run(["tmux", "-L", b.socket, "kill-server"], capture_output=True)


def run(backstage, command, show=False, **kw):
    return RunCommand(cwd=backstage.home, backstage=backstage, **kw).run(
        {"command": command, "purpose": "test", "show": show})


def test_output_and_exit_status(backstage):
    assert run(backstage, "echo hello; echo world") == "hello\nworld\n[exit 0]"
    assert run(backstage, "echo oops >&2; exit 3").endswith("oops\n[exit 3]")


def test_quotes_and_variables_survive(backstage):
    out = run(backstage, """x='a "b" c'; echo "$x" 'it'"'"'s' $((2 + 2))""")
    assert out.startswith('a "b" c it\'s 4')


def test_hidden_commands_get_no_keyboard(backstage):
    # cat would wait for typing forever; with no input it ends at once.
    assert run(backstage, "cat; echo done", timeout=5) == "done\n[exit 0]"


def test_a_killed_command_reports_instead_of_hanging(backstage):
    window = backstage.start("sleep 30", interactive=False)
    subprocess.run(["tmux", "-L", backstage.socket, "send-keys", "-t", window, "C-c"], check=True)
    result = backstage.wait(window, 5)
    assert isinstance(result, Finished) and result.status != 0


def test_hidden_timeout_stops_the_command(backstage):
    with pytest.raises(ToolError, match="timed out"):
        run(backstage, "sleep 30", timeout=0.5)
    out = subprocess.run(["tmux", "-L", backstage.socket, "list-windows", "-t", "backstage", "-F", "#{window_name}"],
                         capture_output=True, text=True).stdout
    assert "sleep 30" not in out


def test_runs_in_the_working_directory(backstage, tmp_path):
    (tmp_path / "marker").write_text("x")
    assert "marker" in run(backstage, "ls")


def test_shown_interactive_command_keeps_running_and_can_be_typed_into(backstage):
    window = backstage.start("read -r x; echo got $x", interactive=True)
    assert isinstance(backstage.wait(window, 0.5), Running)
    done = threading.Event()
    backstage.when_done(window, done.set)
    subprocess.run(["tmux", "-L", backstage.socket, "send-keys", "-t", window, "hi", "Enter"], check=True)
    assert done.wait(5)
    result = backstage.wait(window, 5)
    assert isinstance(result, Finished) and result.output.endswith("got hi") and result.status == 0


def test_undo_snapshot_waits_for_a_program_the_user_is_using(backstage):
    snapper = FakeSnapper()
    shown = []
    tool = RunCommand(cwd=backstage.home, backstage=backstage, show=shown.append, show_wait=0.5)
    model = ScriptedModel([
        Turn(tool_calls=[ToolCall("1", "run_command", {"command": "read -r x; touch made", "purpose": "edit",
                                                       "show": True})]),
        Turn(text="it's open for you"),
    ])
    d = Director(model, [tool], approver=lambda r: True, snapshots=Snapshots(run=snapper))
    assert d.ask("open it so I can type") == "it's open for you"
    assert len(shown) == 1 and "still running" in model.results[0][0].content
    assert [r[1] for r in snapper.rows] == ["pre"]  # no "after" yet: the user is still typing

    subprocess.run(["tmux", "-L", backstage.socket, "send-keys", "-t", shown[0], "ok", "Enter"], check=True)
    for _ in range(50):
        if len(snapper.rows) == 2:
            break
        threading.Event().wait(0.1)
    assert [r[1] for r in snapper.rows] == ["pre", "post"]


def test_old_finished_windows_are_cleared(backstage):
    for i in range(23):
        run(backstage, f"echo {i}")
    names = subprocess.run(["tmux", "-L", backstage.socket, "list-windows", "-t", "backstage", "-F", "#{window_index}"],
                           capture_output=True, text=True).stdout.split()
    assert len(names) == 21  # the user's shell plus the last 20 commands


def test_works_when_something_else_started_the_session(backstage):
    # A terminal showing backstage (Super+Enter, show_terminal) can create the session
    # before the director runs anything, without the director's settings.
    subprocess.run(["tmux", "-L", backstage.socket, "new-session", "-d", "-s", "backstage"], check=True)
    assert run(backstage, "echo still read") == "still read\n[exit 0]"


def test_status_survives_a_closed_window(backstage):
    window = backstage.start("echo hi", interactive=False)
    backstage.wait(window, 5)
    backstage.stop(window)
    assert backstage.wait(window, 1) is not None  # the recorded status, not "vanished"


def test_tabs_are_named_after_the_command(backstage):
    run(backstage, "echo a fairly long command name that keeps going and going")
    names = subprocess.run(["tmux", "-L", backstage.socket, "list-windows", "-t", "backstage", "-F", "#{window_name}"],
                           capture_output=True, text=True).stdout.splitlines()
    assert names[-1] == "1: echo a fairly long command name that kee"  # the first 40 characters


def test_finished_windows_say_so_plainly(backstage):
    window = backstage.start("true", interactive=False)
    backstage.wait(window, 5)
    screen = subprocess.run(["tmux", "-L", backstage.socket, "capture-pane", "-p", "-t", window],
                            capture_output=True, text=True).stdout
    assert "── finished ──" in screen and "Pane is dead" not in screen
    window = backstage.start("exit 3", interactive=False)
    backstage.wait(window, 5)
    screen = subprocess.run(["tmux", "-L", backstage.socket, "capture-pane", "-p", "-t", window],
                            capture_output=True, text=True).stdout
    assert "── finished (exit 3) ──" in screen
