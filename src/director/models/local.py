"""Local model backend (placeholder).

Intended target: a model served on this machine (e.g. Ollama or llama.cpp),
implementing the same Model/Conversation protocol as AnthropicModel.
"""

from __future__ import annotations

from .base import ToolSpec


class LocalModel:
    def __init__(self, model: str, endpoint: str = "http://localhost:11434") -> None:
        self.name = model
        self.endpoint = endpoint

    def start(self, system: str, tools: list[ToolSpec]):
        raise NotImplementedError(
            "Local model backend is not implemented yet; use DIRECTOR_BACKEND=anthropic."
        )
