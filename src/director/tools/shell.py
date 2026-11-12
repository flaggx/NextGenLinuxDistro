from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Any, Callable

from ..backstage import Backstage, Running
from ..permissions import ApprovalRequest, Tier
from .base import StillRunning, Tool, ToolError, schema, truncate

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
# Installing from PyPI as a command (at the start, after ; & | ( `, after a
# wrapper like sudo/env, or inside bash -c '...'):
# pip/pip3/pip3.12, python -m pip, pipx, uv pip / uv tool. Mentioning it in a
# search (`grep "pip install" README`) isn't a command and stays allowed. This
# catches a model's mistakes, not a determined attacker.
_AT_COMMAND = r"(?:^|[;&|(`]\s*|\b(?:sudo|env|exec|command|nohup)\s+(?:-\S+\s+)*|\s-c\s+['\"]\s*)(?:\S*/)?"
PIP_INSTALL = re.compile(
    _AT_COMMAND + r"(?:pip[\d.]*\s+install|pipx\s+install|python[\d.]*\s+-m\s+pip\s+install"
    r"|uv\s+(?:pip|tool)\s+install)\b"
)
PIP_REFUSAL = (
    "pip installs are blocked: packages from PyPI run their authors' code, and a guessed "
    "name can be someone else's (malicious) package. Install programs with Nix instead: "
    "`nix profile install nixpkgs#NAME`, or run one once with `nix shell nixpkgs#NAME -c NAME`."
)
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
        "Prefer find_files/read_file for simple lookups. Set show=true when the user wants to "
        "see the program run (\"run X and show me\") or it's interactive (top, vim, ssh): it "
        "then opens in the backstage terminal, where they can watch and type. Without show, "
        "commands get no keyboard input."
    )
    input_schema = schema(
        {
            "command": {"type": "string", "description": "The bash command to run."},
            "purpose": {
                "type": "string",
                "description": "One plain-language sentence, for the user, describing the outcome.",
            },
            "show": {"type": "boolean", "description": "Run it where the user can see and type into it."},
        },
        required=["command", "purpose"],
    )

    def __init__(
        self,
        cwd: str | None = None,
        timeout: float = 60.0,
        backstage: Backstage | None = None,
        show: Callable[[str], None] | None = None,
        show_wait: float = 30.0,
    ) -> None:
        self.cwd = cwd or os.path.expanduser("~")
        self.timeout = timeout
        # With backstage, commands run in a real terminal the user can look at;
        # `show(window)` puts it on screen. Without, they run as plain subprocesses.
        self.backstage = backstage
        self.show = show
        self.show_wait = show_wait

    def refusal(self, args: dict[str, Any]) -> str | None:
        return PIP_REFUSAL if PIP_INSTALL.search(args["command"]) else None

    def tier(self, args: dict[str, Any]) -> Tier:
        return Tier.FREE if is_read_only(args["command"]) else Tier.APPROVE

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        return ApprovalRequest(tool=self.name, summary=args.get("purpose") or "run a command", detail=args["command"])

    def run(self, args: dict[str, Any]) -> str:
        if self.backstage:
            return self._run_backstage(args["command"], bool(args.get("show")))
        try:
            proc = subprocess.run(
                ["bash", "-c", args["command"]],
                cwd=self.cwd,
                # Nobody can type into it: an interactive program ends at once
                # instead of waiting until the timeout.
                stdin=subprocess.DEVNULL,
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

    def _run_backstage(self, command: str, show: bool) -> str:
        assert self.backstage is not None
        window = self.backstage.start(command, interactive=show, cwd=self.cwd)
        if show and self.show:
            self.show(window)
        result = self.backstage.wait(window, self.show_wait if show else self.timeout)
        if isinstance(result, Running):
            if not show:
                self.backstage.stop(window)
                raise ToolError(f"command timed out after {self.timeout:.0f}s")
            raise StillRunning(
                "It's still running in the backstage terminal, where the user can see and use it.",
                lambda callback: self.backstage.when_done(window, callback),
            )
        if result is None:
            raise ToolError("the command's terminal window was closed before it finished")
        shown = " (shown to the user in the backstage terminal)" if show else ""
        return truncate(f"{result.output}\n[exit {result.status}]{shown}".strip())
