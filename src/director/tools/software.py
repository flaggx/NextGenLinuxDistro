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

import configparser
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..permissions import ApprovalRequest, Tier
from .base import Tool, ToolError, schema, truncate
from .shell import RunCommand, is_read_only

# nixpkgs attribute names: fastfetch, python313Packages.requests, gnome.gnome-boxes...
PACKAGE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*")
NAME = {"type": "string", "description": "The program's package name in nixpkgs, e.g. fastfetch, htop, gimp."}

Run = Callable[[list[str], float], subprocess.CompletedProcess]


# The system allows unfree software (nixos/modules/base.nix); nix's own commands
# don't read that setting, so they're told the same thing explicitly.
UNFREE_ENV = {"NIXPKGS_ALLOW_UNFREE": "1"}
UNFREE = ["--impure"]  # lets nix see that environment variable


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          env={**os.environ, **UNFREE_ENV})


class Nix:
    """The few Nix operations the tools need."""

    def __init__(self, run: Run = _run) -> None:
        self.run = run

    @staticmethod
    def available() -> bool:
        return shutil.which("nix") is not None

    def info(self, name: str) -> tuple[str, str] | None:
        """(description, program name) of a package, or None if nixpkgs has no such package.
        The program name can differ from the package's: claude-code's is `claude`."""
        if not PACKAGE.fullmatch(name):
            return None
        proc = self.run(["nix", "eval", "--json", f"nixpkgs#{name}.meta", *UNFREE, "--apply",
                         "m: { d = m.description or \"\"; p = m.mainProgram or null; }"], 120)
        if proc.returncode != 0:
            if "does not provide attribute" in proc.stderr:
                return None
            raise ToolError(f"couldn't look up {name}: {proc.stderr.strip()[-300:]}")
        meta = json.loads(proc.stdout)
        return meta.get("d") or "(no description)", meta.get("p") or name.rsplit(".", 1)[-1]

    def describe(self, name: str) -> str | None:
        found = self.info(name)
        return found[0] if found else None

    def installed(self) -> list[str]:
        proc = self.run(["nix", "profile", "list", "--json"], 60)
        if proc.returncode != 0:
            return []
        return list(json.loads(proc.stdout or "{}").get("elements", {}))

    def outputs(self, name: str) -> list[str]:
        """Fetch the package (without installing it) and return its store paths."""
        proc = self.run(["nix", "build", "--no-link", "--print-out-paths", f"nixpkgs#{name}", *UNFREE], 1800)
        if proc.returncode != 0:
            raise ToolError(f"couldn't fetch {name}: {proc.stderr.strip()[-300:]}")
        return proc.stdout.split()

    def search(self, query: str) -> list[tuple[str, str]]:
        proc = self.run(["nix", "search", "nixpkgs", query, "--json", *UNFREE], 600)
        if proc.returncode != 0:
            raise ToolError(f"search failed: {proc.stderr.strip()[-300:]}")
        found = json.loads(proc.stdout or "{}")
        # Keys look like legacyPackages.x86_64-linux.fastfetch.
        return [(key.split(".", 2)[-1], info.get("description", "")) for key, info in found.items()]


def _known(nix: Nix, name: str) -> tuple[str, str]:
    found = nix.info(name)
    if found is None:
        raise ToolError(f"nixpkgs has no package called {name!r}. Use find_program to look for the right name.")
    return found


def on_this_computer(words: list[str], limit: int = 10) -> list[str]:
    """Programs already on PATH whose names contain one of `words`."""
    words = [w.lower() for w in words if len(w) >= 3]
    found: dict[str, None] = {}
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            if any(w in name.lower() for w in words) and os.access(os.path.join(directory, name), os.X_OK):
                found[name] = None
    return list(found)[:limit]


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
        words = re.findall(r"[\w.+-]+", args["query"].lower())
        out = []
        here = on_this_computer(words)
        if here:
            out.append("Already on this computer (start with run_program): " + ", ".join(here))
        results = self.nix.search(args["query"])

        def score(item: tuple[str, str]) -> int:
            name, description = item[0].lower(), item[1].lower()
            return -(3 * sum(w in name for w in words) + sum(w in description for w in words)
                     + (2 if name.startswith(words[0]) else 0) if words else 0)

        results.sort(key=score)
        lines = [f"{name}: {description}" for name, description in results[:15]]
        if lines:
            out.append("Available to install, best matches first:\n" + "\n".join(lines)
                       + (f"\n... and {len(results) - 15} more" if len(results) > 15 else ""))
        return "\n\n".join(out) or "Nothing found."


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
        description, program = _known(self.nix, name)
        if name in self.nix.installed() or shutil.which(program):
            raise ToolError(f"{name} is already installed (its program is `{program}`). "
                            "Use run_program to start it.")
        then = " and start it" if args.get("run") else ""
        return ApprovalRequest(
            tool=self.name,
            summary=f"install {name}{then} ({description})",
            detail=f"nix profile add nixpkgs#{name}",
        )

    def run(self, args: dict[str, Any]) -> str:
        name = args["name"]
        proc = self.nix.run(["nix", "profile", "add", f"nixpkgs#{name}", *UNFREE], 1800)
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


# Where installed programs' desktop entries are (the user's profile, the system's).
APP_DIRS = [
    Path("~/.nix-profile/share/applications").expanduser(),
    Path(f"/etc/profiles/per-user/{os.environ.get('USER', '')}/share/applications"),
    Path("/run/current-system/sw/share/applications"),
]


@dataclass(frozen=True)
class DesktopEntry:
    exec: list[str]  # without the %U-style placeholders
    terminal: bool


def find_entry(dirs: list[Path], name: str) -> DesktopEntry | None:
    """The desktop entry (what app launchers use) that starts program `name`, if any."""
    candidates = []
    for directory in dirs:
        for path in sorted(directory.glob("*.desktop")) if directory.is_dir() else []:
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path)
                entry = parser["Desktop Entry"]
            except (configparser.Error, KeyError):
                continue
            argv = [t for t in shlex.split(entry.get("Exec", "")) if not t.startswith("%")]
            if not argv:
                continue
            binary = Path(argv[0]).name
            if binary == name or path.stem == name:
                rank = 0
            elif path.stem.startswith(name):  # chromium-browser.desktop
                rank = 1
            else:
                continue
            candidates.append((rank, DesktopEntry(argv, entry.get("Terminal", "false").lower() == "true")))
    return min(candidates, key=lambda c: c[0])[1] if candidates else None


class RunProgram(Tool):
    name = "run_program"
    description = (
        "Start a program on screen: a graphical one (a browser, an editor) in its own window, a "
        "terminal one in the backstage terminal where the user can see and type into it. If it "
        "isn't installed, it's fetched just for this run. Use this when the user wants to run or "
        "see a program, rather than run_command."
    )
    input_schema = schema(
        {
            "name": NAME,
            "args": {"type": "array", "items": {"type": "string"}, "description": "Its arguments, one per item."},
        },
        required=["name"],
    )
    snapshot = False  # what the user then does in it is theirs

    def __init__(
        self,
        nix: Nix,
        shell: RunCommand,
        launch: Callable[[list[str]], None] | None = None,
        app_dirs: list[Path] | None = None,
    ) -> None:
        self.nix = nix
        self.shell = shell  # with backstage and a way to show it
        # Graphical programs get a window of their own (stage.open), not a terminal.
        self.launch = launch
        self.app_dirs = APP_DIRS if app_dirs is None else app_dirs

    def _program(self, name: str) -> tuple[str, bool]:
        """The program to start for `name`, and whether it's already on this computer.
        `name` may be the program (claude) or its package (claude-code)."""
        if not PACKAGE.fullmatch(name):
            raise ToolError(f"{name!r} isn't a program name")
        if shutil.which(name):
            return name, True
        _, program = _known(self.nix, name)
        return program, shutil.which(program) is not None

    def _command(self, name: str, args: list[str]) -> tuple[str, bool]:
        """The command line, and whether it's fetched just for this run."""
        program, here = self._program(name)
        if here:
            return shlex.join([program, *args]), False
        fetch = shlex.join(["nix", "shell", f"nixpkgs#{name}", *UNFREE, "-c", program, *args])
        return f"NIXPKGS_ALLOW_UNFREE=1 {fetch}", True

    def tier(self, args: dict[str, Any]) -> Tier:
        command, _ = self._command(args["name"], args.get("args") or [])
        return Tier.FREE if is_read_only(command) else Tier.APPROVE

    def approval_request(self, args: dict[str, Any]) -> ApprovalRequest:
        command, fetched = self._command(args["name"], args.get("args") or [])
        note = " (not installed: fetched just for this run)" if fetched else ""
        return ApprovalRequest(tool=self.name, summary=f"run {shlex.join([args['name'], *(args.get('args') or [])])} "
                               f"on screen{note}", detail=command)

    def _window_command(self, name: str, args: list[str]) -> list[str] | None:
        """How to start `name` in a window of its own, if it's a graphical program:
        it has a desktop entry that doesn't ask for a terminal."""
        program, installed = self._program(name)
        outputs = [] if installed else self.nix.outputs(name)
        dirs = self.app_dirs if installed else [Path(p) / "share" / "applications" for p in outputs]
        entry = find_entry(dirs, program) or find_entry(dirs, name)
        if entry is None or entry.terminal:
            return None
        argv = list(entry.exec)
        if not installed and not argv[0].startswith("/"):
            # Fetched, not installed: its programs aren't on PATH.
            argv[0] = next((str(Path(p) / "bin" / argv[0]) for p in outputs
                            if (Path(p) / "bin" / argv[0]).exists()), argv[0])
        return argv + args

    def start(self, name: str, args: list[str]) -> str:
        if self.launch:
            window = self._window_command(name, args)
            if window:
                self.launch(window)
                return f"Started {name} in its own window."
        command, _ = self._command(name, args)
        return self.shell.run({"command": command, "purpose": f"run {name}", "show": True})

    def run(self, args: dict[str, Any]) -> str:
        return truncate(self.start(args["name"], args.get("args") or []))


def software_tools(
    shell: RunCommand, nix: Nix | None = None, launch: Callable[[list[str]], None] | None = None
) -> list[Tool]:
    nix = nix or Nix()
    runner = RunProgram(nix, shell, launch)
    return [InstallProgram(nix, runner), runner, RemoveProgram(nix), FindProgram(nix)]
