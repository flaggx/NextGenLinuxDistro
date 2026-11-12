"""Two model tiers: a small resident model, and a larger worker loaded on demand.

The resident stays loaded and answers most requests: conversation and lookups.
A request moves to the worker when the resident proposes anything that needs
the user's approval (so the small model never writes an approval prompt), or
when it asks for help with the escalate tool. If the worker can't be loaded
(on battery, short of memory), the resident carries on and says so.

Each request starts a fresh conversation on whichever model handles it, with
the recent questions and answers included, so either tier can pick up.
"""

from __future__ import annotations

from typing import Any, Callable

from .agent import SYSTEM_PROMPT, Director, Handoff
from .memory import ActivityLog
from .models.base import Model, ToolCall
from .models.residency import Residency
from .permissions import ApprovalRequest, Approver, deny_all
from .tools.base import Tool, schema
from .undo import Snapshots

RESIDENT_PROMPT = SYSTEM_PROMPT + """
You are the quick, small model. A larger model is available: if a request needs \
several careful steps, writing code, or you are unsure how to do it, call \
`escalate` instead of guessing.
"""

HISTORY_TURNS = 6


class Escalate(Tool):
    name = "escalate"
    description = "Hand this request to a larger, more capable model. Use it instead of guessing."
    input_schema = schema({"reason": {"type": "string", "description": "Why, in a few words."}})

    def run(self, args: dict[str, Any]) -> str:
        raise Handoff(args["reason"])


def _hand_off(request: ApprovalRequest) -> bool:
    raise Handoff(f"needs approval: {request.summary}")


class TieredDirector:
    def __init__(
        self,
        resident: Model,
        worker: Model,
        tools: list[Tool],
        approver: Approver = deny_all,
        residency: Residency | None = None,
        memory: ActivityLog | None = None,
        on_tool: Callable[[ToolCall], None] | None = None,
        on_handoff: Callable[[str], None] | None = None,
        snapshots: Snapshots | None = None,
        context: str = "",
    ) -> None:
        self.resident = resident
        self.worker = worker
        self.tools = tools
        self.approver = approver
        self.residency = residency
        self.memory = memory or ActivityLog()
        self.on_tool = on_tool
        self.on_handoff = on_handoff
        self.snapshots = snapshots
        self.context = context  # e.g. what the stage is (stage.SWAY_CONTEXT)
        self.history: list[tuple[str, str]] = []

    def ask(self, text: str) -> str:
        prompt = self._with_history(text)
        resident = Director(self.resident, self.tools + [Escalate()], approver=_hand_off,
                            memory=self.memory, system=RESIDENT_PROMPT + self.context, on_tool=self.on_tool)
        try:
            answer = resident.ask(prompt)
        except Handoff as handoff:
            answer = self._escalate(prompt, handoff.reason)
        self.history = (self.history + [(text, answer)])[-HISTORY_TURNS:]
        return answer

    def _escalate(self, prompt: str, reason: str) -> str:
        blocked = self.residency.why_worker_cant_load() if self.residency else None
        self.memory.record("handoff", reason=reason, blocked=blocked)
        if blocked:
            # The resident does it after all, asking the user for approval itself.
            fallback = Director(self.resident, self.tools, approver=self.approver, memory=self.memory,
                                system=SYSTEM_PROMPT + self.context, on_tool=self.on_tool, snapshots=self.snapshots)
            note = f"(Using the small model: the larger one isn't available because {blocked}.)"
            return f"{note}\n\n{fallback.ask(prompt)}"
        if self.on_handoff:
            self.on_handoff(reason)
        worker = Director(self.worker, self.tools, approver=self.approver, memory=self.memory,
                          system=SYSTEM_PROMPT + self.context, on_tool=self.on_tool, snapshots=self.snapshots)
        return worker.ask(prompt)

    def _with_history(self, text: str) -> str:
        if not self.history:
            return text
        earlier = "\n".join(f"User: {q}\nYou: {a}" for q, a in self.history)
        return f"Earlier in this conversation:\n{earlier}\n\nNow the user says: {text}"
