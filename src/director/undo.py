"""Making the director's mistakes cheap to undo.

Every action the user approves runs between two btrfs snapshots of /home, taken
by snapper (a pre/post pair). Undoing an action reverts exactly what changed
between its two snapshots, and nothing the user did before or after. The
director never needs root: snapperd does the snapshotting, and its config
allows only this user, only on /home (see nixos/modules/undo.nix).

System changes are covered separately, by NixOS generations.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

CONFIG = "home"
TAG = "director"

Run = Callable[[list[str]], subprocess.CompletedProcess]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class Change:
    pre: int
    post: int
    description: str
    request: str = ""  # changes made for the same user request share this


def last_request(changes: list[Change]) -> list[Change]:
    """The changes made for the most recent request: what "undo that" means."""
    if not changes:
        return []
    request = changes[-1].request
    return [c for c in changes if c.request == request] if request else changes[-1:]


class Snapshots:
    def __init__(self, config: str = CONFIG, run: Run = _run) -> None:
        self.config = config
        self._run = run

    def _snapper(self, *args: str) -> str:
        proc = self._run(["snapper", "-c", self.config, *args])
        if proc.returncode != 0:
            raise SnapshotError((proc.stderr or proc.stdout).strip() or f"snapper {args[0]} failed")
        return proc.stdout

    def available(self) -> bool:
        if self._run is _run and not shutil.which("snapper"):
            return False
        try:
            self._snapper("list")
        except (SnapshotError, OSError, subprocess.SubprocessError):
            return False
        return True

    def before(self, description: str, request: str = "") -> int:
        userdata = f"{TAG}=yes" + (f",request={request}" if request else "")
        return int(self._snapper(
            "create", "--type", "pre", "--print-number", "--cleanup-algorithm", "number",
            "--description", description, "--userdata", userdata,
        ).strip())

    def after(self, pre: int) -> int:
        return int(self._snapper(
            "create", "--type", "post", "--pre-number", str(pre), "--print-number",
            "--cleanup-algorithm", "number", "--userdata", f"{TAG}=yes",
        ).strip())

    def changes(self) -> list[Change]:
        """The director's actions that can still be undone, most recent last."""
        out = self._snapper("--csvout", "list", "--columns", "number,type,pre-number,description,userdata")
        rows = list(csv.DictReader(io.StringIO(out)))
        pres = {r["number"]: r for r in rows if r["type"] == "pre" and f"{TAG}=yes" in r["userdata"]}
        found = []
        for r in rows:
            pre = pres.get(r["pre-number"])
            if r["type"] == "post" and pre and "undone=yes" not in pre["userdata"]:
                request = re.search(r"request=([\w-]+)", pre["userdata"])
                found.append(Change(int(pre["number"]), int(r["number"]), pre["description"],
                                    request.group(1) if request else ""))
        return found

    def changed_files(self, changes: list[Change]) -> list[str]:
        files: dict[str, None] = {}
        for change in changes:
            out = self._snapper("status", f"{change.pre}..{change.post}")
            # Lines look like "c..... /home/me/file": a status code, then the path.
            files.update((line.split(None, 1)[1], None) for line in out.splitlines() if " " in line.strip())
        return list(files)

    def undo(self, changes: list[Change]) -> None:
        # Each action within its own pre/post pair, last first: what other programs
        # (or the user) wrote between the actions stays as it is.
        for change in reversed(changes):
            self._snapper("undochange", f"{change.pre}..{change.post}")
            self._snapper("modify", "--userdata", f"{TAG}=yes,undone=yes", str(change.pre))
