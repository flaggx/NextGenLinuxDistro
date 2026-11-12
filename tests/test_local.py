"""Ollama backend, exercised over real HTTP against a fake Ollama server."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from director.agent import Director, invalid_arguments
from director.models.base import ModelError, ModelSetupError, ToolResult
from director.models.local import LocalModel, endpoint_from_env
from director.tools import ReadFile, RunCommand


class FakeOllama:
    """Replies to /api/chat with queued (status, body) pairs; records requests."""

    def __init__(self):
        self.replies: list[tuple[int, dict]] = []
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                fake.requests.append(json.loads(self.rfile.read(length)))
                status, body = fake.replies.pop(0)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reply(self, content="", tool_calls=None, done_reason="stop", status=200, thinking=None):
        message = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        if thinking is not None:
            message["thinking"] = thinking
        self.replies.append((status, {"message": message, "done_reason": done_reason}))

    def error(self, status, text):
        self.replies.append((status, {"error": text}))


@pytest.fixture
def ollama():
    fake = FakeOllama()
    yield fake
    fake.server.shutdown()


def call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


def test_tool_round_trip(ollama, tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("buy milk")
    ollama.reply(tool_calls=[call("read_file", {"path": str(note)})])
    ollama.reply(content="Your note says: buy milk.")

    director = Director(LocalModel(endpoint=ollama.url), [ReadFile()])
    assert director.ask("what's in my note?") == "Your note says: buy milk."

    first, second = ollama.requests
    assert first["model"] == "lfm3:1.7b" and first["stream"] is False
    assert "keep_alive" not in first
    assert first["options"]["num_ctx"] == 16384
    assert first["tools"][0]["function"]["name"] == "read_file"
    assert first["messages"][0]["role"] == "system"
    tool_msg = second["messages"][-1]
    assert tool_msg == {"role": "tool", "tool_name": "read_file", "content": "buy milk"}
    assert second["messages"][-2]["tool_calls"][0]["function"]["name"] == "read_file"


def test_answer_left_in_thinking_is_used(ollama, tmp_path):
    note = tmp_path / "todo.txt"
    note.write_text("1. Renew passport")
    ollama.reply(tool_calls=[call("read_file", {"path": str(note)})], thinking="Let me read the file.")
    ollama.reply(content="", thinking='The first item is "Renew passport".')

    director = Director(LocalModel(endpoint=ollama.url), [ReadFile()])
    assert director.ask("first todo?") == 'The first item is "Renew passport".'
    # Reasoning next to a real reply or a tool call stays private.
    assert ollama.requests[1]["messages"][-2]["content"] == ""


def test_thinking_stays_private_when_there_is_an_answer(ollama):
    ollama.reply(content="Hello.", thinking="The user greeted me.")
    assert Director(LocalModel(endpoint=ollama.url), []).ask("hi") == "Hello."


def test_string_arguments_are_parsed(ollama):
    ollama.reply(tool_calls=[call("read_file", '{"path": "/x"}')])
    turn = LocalModel(endpoint=ollama.url).start("s", []).send_user("hi")
    assert turn.tool_calls[0].input == {"path": "/x"}
    assert turn.stop_reason == "tool_use"


def test_error_results_are_marked(ollama):
    ollama.reply(tool_calls=[call("read_file", {"path": "/x"})])
    ollama.reply(content="ok")
    convo = LocalModel(endpoint=ollama.url).start("s", [])
    turn = convo.send_user("hi")
    convo.send_tool_results([ToolResult(turn.tool_calls[0].id, "no such file", is_error=True)])
    assert ollama.requests[1]["messages"][-1]["content"] == "Error: no such file"


def test_cut_off_reply_reports_max_tokens(ollama):
    ollama.reply(content="partial", done_reason="length")
    assert LocalModel(endpoint=ollama.url).start("s", []).send_user("hi").stop_reason == "max_tokens"


def test_missing_model_says_how_to_pull(ollama):
    ollama.error(404, "model 'lfm3:1.7b' not found")
    with pytest.raises(ModelSetupError, match="ollama pull lfm3:1.7b"):
        LocalModel(endpoint=ollama.url).start("s", []).send_user("hi")


def test_model_without_tools_is_explained(ollama):
    ollama.error(400, "registry.ollama.ai/library/gemma:2b does not support tools")
    with pytest.raises(ModelSetupError, match="can't use tools"):
        LocalModel("gemma:2b", endpoint=ollama.url).start("s", []).send_user("hi")


def test_other_server_errors_are_retryable(ollama):
    ollama.error(500, "out of memory")
    with pytest.raises(ModelError) as caught:
        LocalModel(endpoint=ollama.url).start("s", []).send_user("hi")
    assert not isinstance(caught.value, ModelSetupError)
    assert "out of memory" in str(caught.value)


def test_failed_request_is_rolled_back(ollama):
    ollama.reply(content="first answer")
    ollama.error(500, "boom")
    convo = LocalModel(endpoint=ollama.url).start("s", [])
    convo.send_user("one")
    before = list(convo.messages)
    with pytest.raises(ModelError):
        convo.send_user("two")
    assert convo.messages == before


def closed_port_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


def test_ollama_not_running():
    with pytest.raises(ModelSetupError, match="ollama serve"):
        LocalModel(endpoint=closed_port_url()).start("s", []).send_user("hi")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("", "http://127.0.0.1:11434"),
        ("0.0.0.0", "http://0.0.0.0:11434"),
        ("myhost:9999", "http://myhost:9999"),
        ("https://gpu-box:11434/", "https://gpu-box:11434"),
    ],
)
def test_ollama_host(monkeypatch, value, expected):
    monkeypatch.setenv("OLLAMA_HOST", value)
    assert endpoint_from_env() == expected


# The director's guard against malformed calls (any backend).

def test_invalid_arguments():
    s = RunCommand().input_schema
    assert invalid_arguments(s, {"command": "ls", "purpose": "list"}) is None
    assert "missing purpose" in invalid_arguments(s, {"command": "ls"})
    assert "unexpected sudo" in invalid_arguments(s, {"command": "ls", "purpose": "p", "sudo": True})
    assert "command must be a string" in invalid_arguments(s, {"command": ["rm"], "purpose": "p"})
    assert invalid_arguments(s, "ls") == "arguments must be an object"


def test_malformed_call_never_runs(ollama):
    ran = []

    class Spy(RunCommand):
        def run(self, args):
            ran.append(args)
            return ""

    ollama.reply(tool_calls=[call("run_command", {"command": "rm -rf ~/x"})])  # no purpose
    ollama.reply(content="sorry")
    director = Director(LocalModel(endpoint=ollama.url), [Spy()], approver=lambda r: True)
    director.ask("clean up")
    assert ran == []
    assert "missing purpose" in ollama.requests[1]["messages"][-1]["content"]


def test_permission_check_failure_fails_closed():
    from director.models.base import ToolCall

    class Broken(RunCommand):
        def tier(self, args):
            raise RuntimeError("cannot classify")

        def run(self, args):
            raise AssertionError("must not run")

    class NoModel:
        name = "none"

        def start(self, system, tools):
            return None

    director = Director(NoModel(), [Broken()], approver=lambda r: True)
    result = director._execute(ToolCall("c1", "run_command", {"command": "x", "purpose": "p"}))
    assert result.is_error and "permissions" in result.content


def test_garbled_model_output_is_asked_again(ollama):
    ollama.error(500, "XML syntax error on line 3: unexpected EOF")
    ollama.reply(content="Fine now.")
    assert LocalModel(endpoint=ollama.url).start("s", []).send_user("hi").text == "Fine now."
    assert len(ollama.requests) == 2


def test_garbled_output_gives_up_after_retries(ollama):
    for _ in range(3):
        ollama.error(500, "XML syntax error on line 3: unexpected EOF")
    with pytest.raises(ModelError, match="couldn't read the model's reply"):
        LocalModel(endpoint=ollama.url).start("s", []).send_user("hi")
    assert len(ollama.requests) == 3
