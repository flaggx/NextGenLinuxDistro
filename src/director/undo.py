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

    def before(self, description: str) -> int:
        return int(self._snapper(
            "create", "--type", "pre", "--print-number", "--cleanup-algorithm", "number",
            "--description", description, "--userdata", f"{TAG}=yes",
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
                found.append(Change(int(pre["number"]), int(r["number"]), pre["description"]))
        return found

    def changed_files(self, change: Change) -> list[str]:
        out = self._snapper("status", f"{change.pre}..{change.post}")
        # Lines look like "c..... /home/me/file": a status code, then the path.
        return [line.split(None, 1)[1] for line in out.splitlines() if " " in line.strip()]

    def undo(self, change: Change) -> None:
        self._snapper("undochange", f"{change.pre}..{change.post}")
        self._snapper("modify", "--userdata", f"{TAG}=yes,undone=yes", str(change.pre))
