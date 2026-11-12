"""Local model backend: a model served on this machine by Ollama.

Free to run and private: nothing leaves the computer. Talks to Ollama's
native /api/chat endpoint with the standard library, so it adds no
dependencies. Small local models are less reliable at tool use than Claude;
the director validates every tool call before running it (see agent.py).
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

from .base import ModelError, ModelSetupError, ToolCall, ToolResult, ToolSpec, Turn

# Best of the benchmarked models at director tasks (bench/, 97/99), and small
# enough (1.3 GB) to stay loaded all the time.
DEFAULT_MODEL = "lfm3:1.7b"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
# CPU-only machines can take minutes for one long reply.
TIMEOUT_SECONDS = 600
# Ollama answers 500 when it can't parse what the model generated (a tool call
# cut short, say). Generation is random, so asking again usually works.
GARBLED_RETRIES = 2
GARBLED_SIGNS = ("syntax error", "unexpected eof", "failed to parse", "invalid character")


class GarbledReply(ModelError):
    """Ollama couldn't parse the model's output; worth asking again."""


def endpoint_from_env() -> str:
    """Honor OLLAMA_HOST the way Ollama does: a bare host:port is allowed."""
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if not host:
        return DEFAULT_ENDPOINT
    if "://" not in host:
        host = "http://" + host
    if host.count(":") == 1:  # scheme only, no port
        host += ":11434"
    return host.rstrip("/")


class LocalModel:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        endpoint: str | None = None,
        num_ctx: int = 16384,
        timeout: float = TIMEOUT_SECONDS,
        keep_alive: str | int | None = None,
    ) -> None:
        self.name = model
        self.endpoint = endpoint or endpoint_from_env()
        # Ollama's default context is small; tool output fills it quickly.
        self.num_ctx = num_ctx
        self.timeout = timeout
        # How long Ollama keeps the model loaded after a request: -1 forever,
        # "5m", 0 to unload right away. None leaves Ollama's default (5 minutes).
        self.keep_alive = keep_alive

    def start(self, system: str, tools: list[ToolSpec]) -> "LocalConversation":
        return LocalConversation(self, system, tools)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(GARBLED_RETRIES + 1):
            try:
                return self._post_once(path, body)
            except GarbledReply as e:
                if attempt == GARBLED_RETRIES:
                    raise ModelError(str(e)) from None
        raise AssertionError("unreachable")

    def _post_once(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.endpoint + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            raise self._http_error(e) from None
        except (TimeoutError, socket.timeout):
            raise ModelError(
                f"The local model took longer than {self.timeout:.0f}s to answer. "
                "Try a smaller model with --model."
            ) from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, (TimeoutError, socket.timeout)):
                raise ModelError(
                    f"The local model took longer than {self.timeout:.0f}s to answer."
                ) from None
            raise ModelSetupError(
                f"Can't reach Ollama at {self.endpoint}. Start it with `ollama serve` "
                "(or `systemctl start ollama`), or set OLLAMA_HOST."
            ) from None
        except json.JSONDecodeError:
            raise ModelError("Ollama sent back a reply that wasn't valid JSON.") from None

    def _http_error(self, e: urllib.error.HTTPError) -> ModelError:
        try:
            detail = json.loads(e.read()).get("error", "")
        except (ValueError, AttributeError):
            detail = ""
        lowered = detail.lower()
        if e.code == 500 and any(sign in lowered for sign in GARBLED_SIGNS):
            return GarbledReply(f"Ollama couldn't read the model's reply ({detail}).")
        if e.code == 404 or "not found" in lowered:
            return ModelSetupError(
                f"The model {self.name!r} isn't downloaded. Run `ollama pull {self.name}`."
            )
        if "does not support tools" in lowered:
            return ModelSetupError(
                f"The model {self.name!r} can't use tools, which the director needs. "
                f"Pick a tool-capable model, e.g. `--model {DEFAULT_MODEL}`."
            )
        return ModelError(f"Ollama returned an error ({e.code}): {detail or e.reason}")


class LocalConversation:
    def __init__(self, model: LocalModel, system: str, tools: list[ToolSpec]) -> None:
        self.model = model
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        # Ollama tool calls carry no ids; we mint them and map back to names.
        self._call_names: dict[str, str] = {}
        self._checkpoint = len(self.messages)

    def send_user(self, text: str) -> Turn:
        self._checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": text})
        return self._call()

    def send_tool_results(self, results: list[ToolResult]) -> Turn:
        for r in results:
            content = f"Error: {r.content}" if r.is_error else r.content
            self.messages.append(
                {"role": "tool", "tool_name": self._call_names.get(r.call_id, ""), "content": content}
            )
        return self._call()

    def _call(self) -> Turn:
        body: dict[str, Any] = {
            "model": self.model.name,
            "messages": self.messages,
            "tools": self.tools,
            "stream": False,
            "options": {"num_ctx": self.model.num_ctx},
        }
        if self.model.keep_alive is not None:
            body["keep_alive"] = self.model.keep_alive
        try:
            reply = self.model.post("/api/chat", body)
        except ModelError:
            del self.messages[self._checkpoint :]
            raise

        message = reply.get("message") or {}
        text = message.get("content") or ""
        raw_calls = message.get("tool_calls") or []
        if not text.strip() and not raw_calls:
            # Some thinking models (qwen3.5) put the final answer in the
            # reasoning channel and leave the reply empty. It's all there is.
            text = (message.get("thinking") or "").strip()
        # Replay the assistant turn as sent, minus private reasoning.
        self.messages.append({"role": "assistant", "content": text, "tool_calls": raw_calls})

        calls = []
        for raw in raw_calls:
            fn = raw.get("function") or {}
            call_id = raw.get("id") or f"call_{uuid4().hex[:12]}"
            self._call_names[call_id] = fn.get("name", "")
            calls.append(ToolCall(id=call_id, name=fn.get("name", ""), input=_arguments(fn.get("arguments"))))

        if reply.get("done_reason") == "length":
            stop = "max_tokens"
        elif calls:
            stop = "tool_use"
        else:
            stop = "end_turn"
        return Turn(text=text, tool_calls=calls, stop_reason=stop)


def _arguments(raw: Any) -> dict[str, Any]:
    """Ollama sends a dict; some models emit a JSON string instead."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"__invalid__": raw}
        return parsed if isinstance(parsed, dict) else {"__invalid__": raw}
    return {}
