from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Any

from ..permissions import ApprovalRequest, Tier
from .base import Tool, ToolError, schema, truncate

# Commands that only look at things. Run without approval when used plainly.
READ_ONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "pwd", "whoami", "date", "uname", "df",
    "du", "free", "uptime", "grep", "rg", "find", "file", "stat", "which", "echo",
    "ps", "id", "hostname", "lsblk", "tree", "sort",
}
# find flags that delete, execute or write files.
FIND_UNSAFE = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}


def _sort_unsafe(args: list[str]) -> bool:
    """sort writes a file with -o/--output and runs a program with --compress-program.

    GNU accepts abbreviated long options (--out, --comp) and bundled short ones
    (-rno), so match prefixes and any 'o' in a bundle. Errs toward asking: -to
    (tab character 'o') asks too.
    """
    for arg in args:
        if arg.startswith("--"):
            if arg[2:].startswith(("o", "co")):
                return True
        elif arg.startswith("-") and "o" in arg[1:]:
            return True
    return False
# Anything that can chain, redirect or substitute makes a command non-trivial.
# A plain pipe is checked separately: each stage must be read-only on its own.
SHELL_METACHARS = set(";&<>`$(){}\n")
# Redirects that write nowhere: discarding output (2>/dev/null, &>/dev/null) or
# merging streams (2>&1). Each must stand alone as its own word (or end at a pipe).
HARMLESS_REDIRECT = re.compile(r"(?<!\S)(?:(?:\d|&)?>>?\s*/dev/null|\d?>&\d)(?![^\s|])")


def is_read_only(command: str) -> bool:
    command = HARMLESS_REDIRECT.sub(" ", command)
    if any(c in SHELL_METACHARS for c in command):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|")
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return False
    stages: list[list[str]] = [[]]
    for word in words:
        # A quoted "|" also lands here and gets treated as a pipe: the safe direction.
        if word == "|":
            stages.append([])
        elif set(word) == {"|"}:  # ||, which chains rather than pipes
            return False
        else:
            stages[-1].append(word)
    return all(_read_only_stage(stage) for stage in stages)


def _read_only_stage(words: list[str]) -> bool:
    if not words or words[0] not in READ_ONLY_COMMANDS:
        return False
    if words[0] == "find" and FIND_UNSAFE.intersection(words):
        return False
    if words[0] == "sort" and _sort_unsafe(words[1:]):
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
