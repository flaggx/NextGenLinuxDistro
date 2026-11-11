"""Claude backend (subscription / API) using the official Anthropic SDK."""

from __future__ import annotations

from typing import Any

import anthropic

from .base import ToolCall, ToolResult, ToolSpec, Turn

DEFAULT_MODEL = "claude-opus-5-5"
# Server-side refusal fallback: the API re-runs a declined request on a
# recommended model, routed by refusal category.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicModel:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str = "high",
        max_tokens: int = 16000,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.name = model
        self.effort = effort
        self.max_tokens = max_tokens
        # Zero-arg client resolves ANTHROPIC_API_KEY or an `ant auth login` profile.
        self.client = client or anthropic.Anthropic()

    def start(self, system: str, tools: list[ToolSpec]) -> "AnthropicConversation":
        return AnthropicConversation(self, system, tools)


class AnthropicConversation:
    def __init__(self, model: AnthropicModel, system: str, tools: list[ToolSpec]) -> None:
        self.model = model
        self.system = system
        self.tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "strict": True,
            }
            for t in tools
        ]
        self.messages: list[dict[str, Any]] = []

    def send_user(self, text: str) -> Turn:
        self.messages.append({"role": "user", "content": text})
        return self._call()

    def send_tool_results(self, results: list[ToolResult]) -> Turn:
        # All results for one assistant turn go back in a single user message.
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in results
                ],
            }
        )
        return self._call()

    def _call(self) -> Turn:
        while True:
            response = self.model.client.beta.messages.create(
                model=self.model.name,
                max_tokens=self.model.max_tokens,
                system=self.system,
                tools=self.tools,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.model.effort},
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            )
            # Append the full content (thinking blocks included), never just text.
            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            break

        if response.stop_reason == "refusal":
            return Turn(text="(The model declined this request.)", stop_reason="refusal")

        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in response.content
            if b.type == "tool_use"
        ]
        return Turn(text=text, tool_calls=calls, stop_reason=response.stop_reason or "end_turn")
