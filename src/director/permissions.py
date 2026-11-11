"""Permission model.

- Everyday actions (reading, finding, arranging windows) run without approval.
- System changes and anything irreversible (deleting, sending data out) need
  the user's approval, asked in plain language about the outcome.
- The agent never runs as root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol


class Tier(Enum):
    FREE = "free"  # no approval needed
    APPROVE = "approve"  # user must approve the outcome first


@dataclass(frozen=True)
class ApprovalRequest:
    tool: str
    summary: str  # plain-language description of the outcome
    detail: str = ""  # the raw command/config, for users who want to look backstage


class Approver(Protocol):
    def __call__(self, request: ApprovalRequest) -> bool: ...


def deny_all(request: ApprovalRequest) -> bool:
    return False


def make_terminal_approver(
    ask: Callable[[str], str] = input, show: Callable[[str], None] = print
) -> Approver:
    def approve(request: ApprovalRequest) -> bool:
        show(f"\n  The director wants to: {request.summary}")
        if request.detail:
            show(f"  (backstage: {request.detail})")
        return ask("  Allow? [y/N] ").strip().lower() in {"y", "yes"}

    return approve


class RunningAsRootError(RuntimeError):
    pass


def ensure_not_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise RunningAsRootError("The director must never run as root.")
