"""Software on NixOS, as tools: the model names a program; the tools do the Nix.

A small model asked to "install fastfetch and run it" wrote `nix shell
nixpkgs#fastfetch -c install`, `--version` (Nix's own), `--help`... seven
approval prompts and nothing installed. Here it only has to pick the tool and
the name. The approval prompts are written by these tools from the package's
own description, not by the model.

Installs go to the user's Nix profile (no root), and like any approved change
they run between undo snapshots.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from typing import Any, Callable

from ..permissions import ApprovalRequest, Tier
from .base import Tool, ToolError, schema, truncate
from .shell import RunCommand, is_read_only

# nixpkgs attribute names: fastfetch, python313Packages.requests, gnome.gnome-boxes...
PACKAGE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*")
NAME = {"type": "string", "description": "The program's package name in nixpkgs, e.g. fastfetch, htop, gimp."}

Run = Callable[[list[str], float], subprocess.CompletedProcess]


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


class Nix:
    """The few Nix operations the tools need."""

    def __init__(self, run: Run = _run) -> None:
        self.run = run

    @staticmethod
    def available() -> bool:
        return shutil.which("nix") is not None

    def describe(self, name: str) -> str | None:
        """The package's one-line description, or None if nixpkgs has no such package."""
        if not PACKAGE.fullmatch(name):
            return None
        proc = self.run(["nix", "eval", "--raw", f"nixpkgs#{name}.meta.description"], 120)
        if proc.returncode != 0:
            if "does not provide attribute" in proc.stderr:
                return None
            raise ToolError(f"couldn't look up {name}: {proc.stderr.strip()[-300:]}")
        return proc.stdout.strip() or "(no description)"

    def installed(self) -> list[str]:
        proc = self.run(["nix", "profile", "list", "--json"], 60)
        if proc.returncode != 0:
            return []
        return list(json.loads(proc.stdout or "{}").get("elements", {}))

    def search(self, query: str) -> list[tuple[str, str]]:
        proc = self.run(["nix", "search", "nixpkgs", query, "--json"], 600)
        if proc.returncode != 0:
            raise ToolError(f"search failed: {proc.stderr.strip()[-300:]}")
        found = json.loads(proc.stdout or "{}")
        # Keys look like legacyPackages.x86_64-linux.fastfetch.
        return [(key.split(".", 2)[-1], info.get("description", "")) for key, info in found.items()]


def _known(nix: Nix, name: str) -> str:
    description = nix.describe(name)
    if description is None:
        raise ToolError(f"nixpkgs has no package called {name!r}. Use find_program to look for the right name.")
    return description


class FindProgram(Tool):
    name = "find_program"
    description = (
        "Search the software available to install, by words in its name or description. "
        "Slow (up to a minute): only when you don't know a program's package name."
    )
    input_schema = schema({"query": {"type": "string", "description": "Words to look for, e.g. 'pdf editor'."}})
    snapshot = False

    def __init__(self, nix: Nix) -> None:
        self.nix = nix

    def run(self, args: dict[str, Any]) -> str:
        results = self.nix.search(args["query"])
        if not results:
            return "Nothing found."
        lines = [f"{name}: {description}" for name, description in results[:15]]
        more = f"\n... and {len(results) - 15} more" if len(results) > 15 else ""
        return "\n".join(lines) + more


class InstallProgram(Tool):
    name = "install_program"
    description = (
        "Install a program for the user (from nixpkgs, into their own profile: no root). "
        "Set run=true to start it on screen afterwards when they also want to use or see it."
    )
    input_schema = schema(
        {"name": NAME, "run": {"type": "boolean", "description": "Start it on screen once installed."}},
        required=["name"],
    )

    def __init__(self, nix: Nix, runner: RunProgram | None = None) -> None:
        self.nix = nix
        self.runner = runner

    def tier(self, args: dict[str, Any]) -> Tier:
        return Tier.APPROVE

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        name = args["name"]
        description = _known(self.nix, name)
        if name in self.nix.installed():
            raise ToolError(f"{name} is already installed." + (" Use run_program to start it." if args.get("run") else ""))
        then = " and start it" if args.get("run") else ""
        return ApprovalRequest(
            tool=self.name,
            summary=f"install {name}{then} ({description})",
            detail=f"nix profile add nixpkgs#{name}",
        )

    def run(self, args: dict[str, Any]) -> str:
        name = args["name"]
        proc = self.nix.run(["nix", "profile", "add", f"nixpkgs#{name}"], 1800)
        if proc.returncode != 0:
            raise ToolError(f"installing {name} failed: {proc.stderr.strip()[-500:]}")
        result = f"Installed {name}."
        if args.get("run") and self.runner:
            result += "\n" + self.runner.start(name, [])
        return result


class RemoveProgram(Tool):
    name = "remove_program"
    description = "Uninstall a program that was installed for the user."
    input_schema = schema({"name": NAME})

    def __init__(self, nix: Nix) -> None:
        self.nix = nix

    def tier(self, args: dict[str, Any]) -> Tier:
        return Tier.APPROVE

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        installed = self.nix.installed()
        if args["name"] not in installed:
            raise ToolError(f"{args['name']} isn't installed. Installed: {', '.join(installed) or 'nothing'}.")
        return ApprovalRequest(tool=self.name, summary=f"uninstall {args['name']}",
                               detail=f"nix profile remove {args['name']}")

    def run(self, args: dict[str, Any]) -> str:
        proc = self.nix.run(["nix", "profile", "remove", args["name"]], 300)
        if proc.returncode != 0:
            raise ToolError(f"removing {args['name']} failed: {proc.stderr.strip()[-500:]}")
        return f"Removed {args['name']}."


class RunProgram(Tool):
    name = "run_program"
    description = (
        "Start a program on screen, in the backstage terminal, where the user sees it and can "
        "type into it. If it isn't installed, it's fetched just for this run. Use this when "
        "the user wants to run or see a program, rather than run_command."
    )
    input_schema = schema(
        {
            "name": NAME,
            "args": {"type": "array", "items": {"type": "string"}, "description": "Its arguments, one per item."},
        },
        required=["name"],
    )
    snapshot = False  # what the user then does in it is theirs

    def __init__(self, nix: Nix, shell: RunCommand) -> None:
        self.nix = nix
        self.shell = shell  # with backstage and a way to show it

    def _command(self, name: str, args: list[str]) -> tuple[str, bool]:
        """The command line, and whether it's fetched just for this run."""
        if not PACKAGE.fullmatch(name):
            raise ToolError(f"{name!r} isn't a program name")
        if shutil.which(name):
            return shlex.join([name, *args]), False
        _known(self.nix, name)
        return shlex.join(["nix", "shell", f"nixpkgs#{name}", "-c", name.rsplit(".", 1)[-1], *args]), True

    def tier(self, args: dict[str, Any]) -> Tier:
        command, _ = self._command(args["name"], args.get("args") or [])
        return Tier.FREE if is_read_only(command) else Tier.APPROVE

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        command, fetched = self._command(args["name"], args.get("args") or [])
        note = " (not installed: fetched just for this run)" if fetched else ""
        return ApprovalRequest(tool=self.name, summary=f"run {shlex.join([args['name'], *(args.get('args') or [])])} "
                               f"on screen{note}", detail=command)

    def start(self, name: str, args: list[str]) -> str:
        command, _ = self._command(name, args)
        return self.shell.run({"command": command, "purpose": f"run {name}", "show": True})

    def run(self, args: dict[str, Any]) -> str:
        return truncate(self.start(args["name"], args.get("args") or []))


def software_tools(shell: RunCommand, nix: Nix | None = None) -> list[Tool]:
    nix = nix or Nix()
    runner = RunProgram(nix, shell)
    return [InstallProgram(nix, runner), RunProgram(nix, shell), RemoveProgram(nix), FindProgram(nix)]
