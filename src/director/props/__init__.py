"""Props (roadmap step 3): existing viewers/editors wrapped as tools.

Draft contract, to be refined:
- The director sends a PropCommand (show this file, highlight these lines,
  present this form) to a named prop.
- The prop reports PropEvents back (user edited, saved, submitted, closed).
  Event payloads come from the user's content and are untrusted data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class PropCommand:
    action: str  # "show", "update", "close", ...
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PropEvent:
    prop: str
    kind: str  # "opened", "edited", "submitted", "closed", ...
    data: dict[str, Any] = field(default_factory=dict)


class Prop(Protocol):
    name: str  # e.g. "text_viewer", "image_viewer", "code_editor"
    actions: list[str]

    def send(self, command: PropCommand) -> None: ...
    def on_event(self, callback: Callable[[PropEvent], None]) -> None: ...
