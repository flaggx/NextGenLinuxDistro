import subprocess

from director.agent import Director
from director.models.base import ToolCall, Turn
from director.tools import RunCommand, UndoLastChange
from director.undo import SnapshotError, Snapshots

from test_agent import ScriptedModel


class FakeSnapper:
    """Just enough of snapper's CLI: numbered pre/post snapshots, status, undochange."""

    def __init__(self, fail=False):
        self.rows = []  # number, type, pre-number, description, userdata
        self.undone = []
        self.fail = fail

    def __call__(self, argv):
        assert argv[:3] == ["snapper", "-c", "home"]
        args = argv[3:]
        if self.fail:
            return subprocess.CompletedProcess(argv, 1, "", "snapperd unavailable")
        out = ""
        if args[0] == "create":
            n = len(self.rows) + 1
            opt = lambda flag, default="": args[args.index(flag) + 1] if flag in args else default
            self.rows.append([str(n), opt("--type"), opt("--pre-number"), opt("--description"), opt("--userdata")])
            out = f"{n}\n"
        elif args[:2] == ["--csvout", "list"]:
            out = "number,type,pre-number,description,userdata\n" + "".join(
                ",".join(f'"{v}"' for v in r) + "\n" for r in self.rows)
        elif args[0] == "list":
            out = "ok"
        elif args[0] == "status":
            out = "c..... /home/me/todo.txt\n+..... /home/me/new.txt\n"
        elif args[0] == "undochange":
            self.undone.append(args[1])
        elif args[0] == "modify":
            self.rows[int(args[-1]) - 1][4] = args[args.index("--userdata") + 1]
        return subprocess.CompletedProcess(argv, 0, out, "")


def run_cmd(cmd, purpose="change it"):
    return Turn(tool_calls=[ToolCall("1", "run_command", {"command": cmd, "purpose": purpose})])


def test_approved_changes_run_between_snapshots(tmp_path):
    snapper = FakeSnapper()
    model = ScriptedModel([run_cmd("touch new.txt", "create new.txt"), Turn(text="done")])
    d = Director(model, [RunCommand(cwd=str(tmp_path))], approver=lambda r: True, snapshots=Snapshots(run=snapper))
    d.ask("make a file")
    assert [r[1] for r in snapper.rows] == ["pre", "post"]
    assert snapper.rows[0][3] == "create new.txt" and snapper.rows[1][2] == "1"
    assert Snapshots(run=snapper).changes()[0].description == "create new.txt"


def test_free_and_declined_actions_take_no_snapshots(tmp_path):
    snapper = FakeSnapper()
    model = ScriptedModel([run_cmd("echo hi"), run_cmd("touch x"), Turn(text="ok")])
    d = Director(model, [RunCommand(cwd=str(tmp_path))], approver=lambda r: False, snapshots=Snapshots(run=snapper))
    d.ask("go")
    assert snapper.rows == []


def test_failed_snapshot_still_runs_and_says_so(tmp_path):
    model = ScriptedModel([run_cmd("touch x"), Turn(text="ok")])
    d = Director(model, [RunCommand(cwd=str(tmp_path))], approver=lambda r: True,
                 snapshots=Snapshots(run=FakeSnapper(fail=True)))
    d.ask("go")
    assert (tmp_path / "x").exists()
    assert "No undo snapshot" in model.results[0][0].content
    assert d.memory.recent(kind="snapshot_failed")


def test_undo_reverts_the_last_change_and_lists_files():
    snapper = FakeSnapper()
    snaps = Snapshots(run=snapper)
    first = snaps.before("rename report")
    snaps.after(first)
    second = snaps.before("add buy milk")
    snaps.after(second)

    tool = UndoLastChange(snaps)
    request = tool.approval_request({})
    assert request.summary == 'undo "add buy milk", putting 2 file(s) back as they were'
    assert "/home/me/todo.txt" in request.detail
    assert tool.run({}) == 'Undone: "add buy milk"'
    assert snapper.undone == ["3..4"]
    # The undone change is gone from the list; the one before is next.
    assert [c.description for c in snaps.changes()] == ["rename report"]


def test_undo_goes_through_approval_without_its_own_snapshot():
    snapper = FakeSnapper()
    snaps = Snapshots(run=snapper)
    snaps.after(snaps.before("delete tmp files"))
    model = ScriptedModel([Turn(tool_calls=[ToolCall("1", "undo_last_change", {})]), Turn(text="undone")])
    asked = []
    d = Director(model, [UndoLastChange(snaps)], approver=lambda r: asked.append(r) or True, snapshots=snaps)
    d.ask("undo that")
    assert len(asked) == 1 and snapper.undone == ["1..2"]
    assert len(snapper.rows) == 2  # no snapshot pair around the undo itself


def test_nothing_to_undo_is_reported_not_asked():
    model = ScriptedModel([Turn(tool_calls=[ToolCall("1", "undo_last_change", {})]), Turn(text="nothing")])
    asked = []
    d = Director(model, [UndoLastChange(Snapshots(run=FakeSnapper()))], approver=lambda r: asked.append(r) or True)
    d.ask("undo")
    assert asked == [] and "nothing to undo" in model.results[0][0].content


def test_snapshots_unavailable_without_snapper():
    assert not Snapshots(run=FakeSnapper(fail=True)).available()
    try:
        Snapshots(run=FakeSnapper(fail=True)).before("x")
    except SnapshotError as e:
        assert "snapperd unavailable" in str(e)
    else:
        raise AssertionError("expected SnapshotError")


def test_undo_covers_every_change_of_the_last_request(tmp_path):
    snapper = FakeSnapper()
    snaps = Snapshots(run=snapper)
    model = ScriptedModel([
        run_cmd("touch a", "create a"), run_cmd("touch b", "create b"), Turn(text="made both"),
        Turn(tool_calls=[ToolCall("1", "undo_last_change", {})]), Turn(text="undone"),
    ])
    asked = []
    d = Director(model, [RunCommand(cwd=str(tmp_path)), UndoLastChange(snaps)],
                 approver=lambda r: asked.append(r) or True, snapshots=snaps)
    d.ask("make a and b")
    d.ask("undo that")
    assert snapper.undone == ["1..4"]  # before the first change to after the last
    assert 'undo "create a" and 1 more change(s) from the same request' in asked[-1].summary
    assert snaps.changes() == []


def test_an_earlier_request_stays_when_the_last_is_undone():
    snapper = FakeSnapper()
    snaps = Snapshots(run=snapper)
    snaps.after(snaps.before("earlier", "req1"))
    snaps.after(snaps.before("later one", "req2"))
    snaps.after(snaps.before("later two", "req2"))
    UndoLastChange(snaps).run({})
    assert snapper.undone == ["3..6"]
    assert [c.description for c in snaps.changes()] == ["earlier"]
