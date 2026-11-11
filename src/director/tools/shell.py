from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any

from ..permissions import ApprovalRequest, Tier
from .base import Tool, ToolError, schema, truncate

# Commands that only look at things. Run without approval when used plainly.
READ_ONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "pwd", "whoami", "date", "uname", "df",
    "du", "free", "uptime", "grep", "rg", "find", "file", "stat", "which", "echo",
    "ps", "id", "hostname", "lsblk", "tree",
}
# find flags that delete, execute or write files.
FIND_UNSAFE = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
# Anything that can chain, redirect or substitute makes a command non-trivial.
SHELL_METACHARS = set(";&|<>`$(){}\n")


def is_read_only(command: str) -> bool:
    if any(c in SHELL_METACHARS for c in command):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if not words or words[0] not in READ_ONLY_COMMANDS:
        return False
    if words[0] == "find" and FIND_UNSAFE.intersection(words):
        return False
    return True


class RunCommand(Tool):
    name = "run_command"
    description = (
        "Run a shell command as the user (never root) and return its output. "
        "Read-only commands run immediately; anything else asks the user first. "
        "Prefer find_files/read_file for simple lookups."
    )
    input_schema = schema(
        {
            "command": {"type": "string", "description": "The bash command to run."},
            "purpose": {
                "type": "string",
                "description": "One plain-language sentence, for the user, describing the outcome.",
            },
        }
    )

    def __init__(self, cwd: str | None = None, timeout: float = 60.0) -> None:
        self.cwd = cwd or os.path.expanduser("~")
        self.timeout = timeout

    def tier(self, args: dict[str, Any]) -> Tier:
        return Tier.FREE if is_read_only(args["command"]) else Tier.APPROVE

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        return ApprovalRequest(tool=self.name, summary=args.get("purpose") or "run a command", detail=args["command"])

    def run(self, args: dict[str, Any]) -> str:
        try:
            proc = subprocess.run(
                ["bash", "-c", args["command"]],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"command timed out after {self.timeout:.0f}s")
        out = proc.stdout
        if proc.stderr:
            out += f"\n[stderr]\n{proc.stderr}"
        out += f"\n[exit {proc.returncode}]"
        return truncate(out.strip())
