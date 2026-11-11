from director.models.base import ToolCall, Turn
from director.models.residency import GiB, Residency
from director.tiers import TieredDirector
from director.tools import RunCommand

from test_agent import ScriptedModel


def rm(target):
    return Turn(tool_calls=[ToolCall("1", "run_command", {"command": f"rm {target}", "purpose": "delete it"})])


class FakeOllama:
    """Stands in for Ollama's API: which models exist, which are loaded."""

    def __init__(self, downloaded=None, loaded=()):
        self.downloaded = {"big": 20 * GiB} if downloaded is None else downloaded
        self.loaded = set(loaded)
        self.unloaded = []

    def __call__(self, path, body):
        if path == "/api/ps":
            return {"models": [{"name": n} for n in self.loaded]}
        if path == "/api/tags":
            return {"models": [{"name": n, "size": s} for n, s in self.downloaded.items()]}
        if path == "/api/generate" and body.get("keep_alive") == 0:
            self.loaded.discard(body["model"])
            self.unloaded.append(body["model"])
            return {}
        raise AssertionError(path)


def residency(api, battery=False, ram=28 * GiB, vram=7 * GiB):
    return Residency("big", api=api, battery=lambda: battery, ram_free=lambda: ram, vram_free=lambda: vram)


def test_resident_answers_lookups_alone(tmp_path):
    resident = ScriptedModel([
        Turn(tool_calls=[ToolCall("1", "run_command", {"command": "echo hi", "purpose": "look"})]),
        Turn(text="hi"),
    ])
    worker = ScriptedModel([])
    d = TieredDirector(resident, worker, [RunCommand(cwd=str(tmp_path))])
    assert d.ask("say hi") == "hi"
    assert "escalate" in resident.tool_names
    assert not hasattr(worker, "tool_names")  # never started


def test_changes_go_to_the_worker_and_only_it_asks_the_user(tmp_path):
    target = tmp_path / "x.txt"
    target.write_text("x")
    resident = ScriptedModel([rm(target)])
    worker = ScriptedModel([rm(target), Turn(text="deleted")])
    asked = []
    d = TieredDirector(resident, worker, [RunCommand(cwd=str(tmp_path))],
                       approver=lambda r: asked.append(r) or True)
    assert d.ask("delete x.txt") == "deleted"
    assert len(asked) == 1  # the worker's prompt; the resident's never reached the user
    assert not target.exists()
    assert "escalate" not in worker.tool_names
    assert d.memory.recent(kind="handoff")[0].data["reason"].startswith("needs approval")


def test_resident_can_ask_for_the_worker():
    resident = ScriptedModel([Turn(tool_calls=[ToolCall("1", "escalate", {"reason": "needs code"})])])
    worker = ScriptedModel([Turn(text="here's your script")])
    handoffs = []
    d = TieredDirector(resident, worker, [], on_handoff=handoffs.append)
    assert d.ask("write a script") == "here's your script"
    assert handoffs == ["needs code"]


def test_recent_turns_carry_over_to_either_model():
    resident = ScriptedModel([Turn(text="It's Tuesday."), Turn(text="Yes.")])
    seen = []
    resident.send_user = lambda text, turns=resident.turns: seen.append(text) or turns.pop(0)
    d = TieredDirector(resident, ScriptedModel([]), [])
    d.ask("what day is it?")
    d.ask("are you sure?")
    assert seen[0] == "what day is it?"
    assert "User: what day is it?\nYou: It's Tuesday." in seen[1] and seen[1].endswith("are you sure?")


def test_resident_carries_on_when_the_worker_cant_load(tmp_path):
    target = tmp_path / "x.txt"
    target.write_text("x")
    resident = ScriptedModel([rm(target), rm(target), Turn(text="deleted")])
    asked = []
    d = TieredDirector(resident, ScriptedModel([]), [RunCommand(cwd=str(tmp_path))],
                       approver=lambda r: asked.append(r) or True,
                       residency=residency(FakeOllama(), battery=True))
    answer = d.ask("delete x.txt")
    assert answer.startswith("(Using the small model: the larger one isn't available because the laptop is on battery.)")
    assert len(asked) == 1 and not target.exists()


def test_worker_fit_accounts_for_video_memory():
    api = FakeOllama({"big": 20 * GiB})
    # 20 GB file + 2 GB overhead - 7 GB on the GPU = 15 GB of system memory, plus the 4 GB reserve.
    assert residency(api, ram=20 * GiB).why_worker_cant_load() is None
    assert "only 14 GB is free" in residency(api, ram=17 * GiB).why_worker_cant_load()
    assert "isn't downloaded" in residency(FakeOllama({})).why_worker_cant_load()
    assert residency(FakeOllama(loaded={"big"}), battery=True).why_worker_cant_load() is None


def test_worker_is_pushed_out_on_battery_or_low_memory():
    api = FakeOllama(loaded={"big", "small"})
    assert residency(api).check() is None and api.unloaded == []
    assert residency(api, battery=True).check() == "the laptop went on battery"
    assert api.unloaded == ["big"] and api.loaded == {"small"}  # the resident stays

    api = FakeOllama(loaded={"big"})
    assert residency(api, ram=3 * GiB).check() == "memory is running low"
    assert residency(api, ram=3 * GiB).check() is None  # already gone
