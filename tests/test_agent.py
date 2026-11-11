from director.agent import Director
from director.models.base import ToolCall, ToolResult, ToolSpec, Turn
from director.tools import FindFiles, ReadFile, RunCommand


class ScriptedModel:
    """Fake backend: returns pre-scripted turns and records what it was sent."""

    name = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.results: list[list[ToolResult]] = []

    def start(self, system: str, tools: list[ToolSpec]):
        self.tool_names = [t.name for t in tools]
        return self

    def send_user(self, text):
        return self.turns.pop(0)

    def send_tool_results(self, results):
        self.results.append(results)
        return self.turns.pop(0)


def test_plain_answer():
    model = ScriptedModel([Turn(text="hello")])
    assert Director(model, []).ask("hi") == "hello"


def test_read_only_command_runs_without_approval(tmp_path):
    model = ScriptedModel([
        Turn(tool_calls=[ToolCall("1", "run_command", {"command": "echo hi", "purpose": "say hi"})]),
        Turn(text="done"),
    ])
    asked = []
    d = Director(model, [RunCommand(cwd=str(tmp_path))], approver=lambda r: asked.append(r) or True)
    assert d.ask("go") == "done"
    assert asked == []
    assert "hi" in model.results[0][0].content


def test_changing_command_needs_approval_and_can_be_declined(tmp_path):
    target = tmp_path / "keep.txt"
    target.write_text("x")
    model = ScriptedModel([
        Turn(tool_calls=[ToolCall("1", "run_command", {"command": f"rm {target}", "purpose": "delete keep.txt"})]),
        Turn(text="ok, left it"),
    ])
    d = Director(model, [RunCommand(cwd=str(tmp_path))])  # default approver denies
    d.ask("delete it")
    result = model.results[0][0]
    assert result.is_error and "declined" in result.content
    assert target.exists()
    assert d.memory.recent(kind="approval")[0].data["approved"] is False


def test_unknown_tool_and_tool_errors_are_reported(tmp_path):
    model = ScriptedModel([
        Turn(tool_calls=[
            ToolCall("1", "nope", {}),
            ToolCall("2", "read_file", {"path": str(tmp_path / "missing")}),
        ]),
        Turn(text="sorry"),
    ])
    Director(model, [ReadFile(home=str(tmp_path))]).ask("read")
    first, second = model.results[0]
    assert first.is_error and second.is_error


def test_find_files_skips_hidden(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / ".secret").mkdir()
    (tmp_path / ".secret" / "b.txt").write_text("b")
    out = FindFiles(home=str(tmp_path)).run({"pattern": "**/*.txt", "directory": "."})
    assert "a.txt" in out and "b.txt" not in out
