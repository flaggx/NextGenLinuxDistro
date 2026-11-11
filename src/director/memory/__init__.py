"""The director's memory (roadmap step 4).

For now: a bounded log of recent activity. Later this feeds pacing and
presentation decisions (what to show, when, and how much).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    kind: str  # "user", "tool", "approval", "prop", ...
    data: dict[str, Any]
    at: float = field(default_factory=time.time)


class ActivityLog:
    def __init__(self, capacity: int = 500) -> None:
        self._events: deque[Event] = deque(maxlen=capacity)

    def record(self, kind: str, **data: Any) -> Event:
        event = Event(kind, data)
        self._events.append(event)
        return event

    def recent(self, n: int = 20, kind: str | None = None) -> list[Event]:
        events = [e for e in self._events if kind is None or e.kind == kind]
        return events[-n:]

    def __len__(self) -> int:
        return len(self._events)
