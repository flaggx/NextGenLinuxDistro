from .base import (
    Conversation,
    Model,
    ModelError,
    ModelSetupError,
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
)


def load_model(backend: str, model: str | None = None, **kwargs) -> Model:
    """Build a model backend by name. Imports lazily so unused SDKs aren't required."""
    if backend == "anthropic":
        from .anthropic_model import DEFAULT_MODEL, AnthropicModel

        return AnthropicModel(model or DEFAULT_MODEL, **kwargs)
    if backend == "local":
        from .local import LocalModel

        return LocalModel(model or "llama3.1")
    raise ValueError(f"unknown model backend: {backend!r}")


__all__ = [
    "Conversation",
    "Model",
    "ModelError",
    "ModelSetupError",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Turn",
    "load_model",
]
