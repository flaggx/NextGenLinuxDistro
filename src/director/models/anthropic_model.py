"""Claude backend (subscription / API) using the official Anthropic SDK."""

from __future__ import annotations

from typing import Any

import anthropic

from .base import ModelError, ModelSetupError, ToolCall, ToolResult, ToolSpec, Turn

DEFAULT_MODEL = "claude-opus-5-5"

NO_CREDENTIALS = (
    "No Anthropic credentials found. Set ANTHROPIC_API_KEY "
    "(from console.anthropic.com) or run `ant auth login`."
)
NO_CREDITS = (
    "Your Anthropic API account has no credits. Add some under Billing at "
    "console.anthropic.com (API usage is billed separately from a Claude.ai subscription)."
)


def _is_billing_error(e: anthropic.APIStatusError) -> bool:
    # 402 billing_error; older accounts may still see a 400 that names the balance.
    return (
        e.status_code == 402
        or getattr(e, "type", None) == "billing_error"
        or "credit balance" in (e.message or "").lower()
    )
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
        # Transcript length before the current request began; a failed
        # request rolls back to here so the transcript stays valid to resend.
        self._checkpoint = 0

    def send_user(self, text: str) -> Turn:
        self._checkpoint = len(self.messages)
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
        try:
            return self._call_unchecked()
        except ModelError:
            # Drop the whole failed request, including any tool round trips
            # already made for it: a dangling tool_use with no result would
            # make every later request fail.
            del self.messages[self._checkpoint :]
            raise

    def _create(self) -> Any:
        try:
            return self.model.client.beta.messages.create(
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
        except TypeError as e:
            # The SDK raises a bare TypeError when it finds no key, token or profile.
            if "authentication" in str(e):
                raise ModelSetupError(NO_CREDENTIALS) from None
            raise
        except anthropic.CredentialsError as e:
            raise ModelSetupError(f"Your Anthropic login profile couldn't be used: {e}") from None
        except anthropic.AuthenticationError:
            raise ModelSetupError(
                "Anthropic rejected your credentials. Check ANTHROPIC_API_KEY "
                "or run `ant auth login` again."
            ) from None
        except anthropic.PermissionDeniedError as e:
            raise ModelSetupError(f"Your Anthropic account can't make this request: {e.message}") from None
        except anthropic.NotFoundError:
            raise ModelSetupError(
                f"Model {self.model.name!r} wasn't found. Check --model or DIRECTOR_MODEL."
            ) from None
        except anthropic.APIConnectionError:
            raise ModelError(
                "Couldn't reach the Anthropic API. Check your internet connection and try again."
            ) from None
        except anthropic.RateLimitError:
            raise ModelError("Anthropic is rate-limiting requests. Wait a moment and try again.") from None
        except anthropic.APIStatusError as e:
            if _is_billing_error(e):
                raise ModelSetupError(NO_CREDITS) from None
            raise ModelError(f"The Anthropic API returned an error ({e.status_code}): {e.message}") from None

    def _call_unchecked(self) -> Turn:
        while True:
            response = self._create()
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
