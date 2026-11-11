"""Tools that run inside a throwaway fake home, so benchmarked models can't touch the real one.

Shell commands run under bubblewrap: the whole filesystem read-only, the real
home hidden, no network, and only the fake home writable.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from director.tools import FindFiles, ReadFile, RunCommand
from director.tools.base import ToolError, truncate

REAL_HOME = Path(os.path.expanduser("~")).resolve()


def bwrap_argv(home: Path, command: str) -> list[str]:
    return [
        "bwrap",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--tmpfs", str(REAL_HOME),
        "--bind", str(home), str(home),
        "--unshare-net",
        "--die-with-parent",
        "--chdir", str(home),
        "--setenv", "HOME", str(home),
        "bash", "-c", command,
    ]


class SandboxedRunCommand(RunCommand):
    def __init__(self, home: Path, timeout: float = 60.0) -> None:
        super().__init__(cwd=str(home), timeout=timeout)
        self.home = home

    def run(self, args: dict[str, Any]) -> str:
        try:
            proc = subprocess.run(
                bwrap_argv(self.home, args["command"]), capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"command timed out after {self.timeout:.0f}s")
        out = proc.stdout
        if proc.stderr:
            out += f"\n[stderr]\n{proc.stderr}"
        out += f"\n[exit {proc.returncode}]"
        return truncate(out.strip())


def _into_fake_home(path: str, home: Path) -> str:
    """Point '~' and the real home at the fake one; refuse anything still under the real home."""
    if path == "~" or path.startswith("~/"):
        path = str(home) + path[1:]
    elif path == str(REAL_HOME) or path.startswith(str(REAL_HOME) + "/"):
        path = str(home) + path[len(str(REAL_HOME)):]
    p = Path(path)
    if (p if p.is_absolute() else home / p).resolve().is_relative_to(REAL_HOME):
        raise ToolError(f"not found: {path}")
    return path


class SandboxedFindFiles(FindFiles):
    def run(self, args: dict[str, Any]) -> str:
        return super().run({**args, "directory": _into_fake_home(args["directory"], self.home)})


class SandboxedReadFile(ReadFile):
    def run(self, args: dict[str, Any]) -> str:
        return super().run({**args, "path": _into_fake_home(args["path"], self.home)})


def sandboxed_tools(home: Path) -> list:
    return [SandboxedRunCommand(home), SandboxedFindFiles(str(home)), SandboxedReadFile(str(home))]
