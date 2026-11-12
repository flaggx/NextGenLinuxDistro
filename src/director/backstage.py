"""Backstage: a real terminal that the director's commands run in.

One tmux session on its own server (so the user's own tmux is untouched).
Window 0 is the user's shell. Each command the director runs gets a window of
its own, named after the command, instead of being typed into the user's
shell, so the two never type over each other. Finished windows stay open so
they can be looked at; the oldest are cleared away.

Nobody has to watch: the director reads a command's output from the window's
scrollback. When the user wants to see (or the program is interactive), the
stage shows the session in a window and focuses the command's tab.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SOCKET = "director"
SESSION = "backstage"
KEEP_WINDOWS = 20
HISTORY_LINES = 50_000

# Runs inside the command's window. The command comes in through the
# environment, so it never has to be quoted into another shell string, and runs
# in a shell of its own, so an `exit` in it can't skip recording the status.
WRAPPER = 'bash -c "$DIRECTOR_CMD"; echo $? > "$DIRECTOR_STATUS"; tmux wait-for -S "$DIRECTOR_DONE"'


@dataclass(frozen=True)
class Finished:
    output: str
    status: int


@dataclass(frozen=True)
class Running:
    window: str  # still going: the user is watching or typing into it


class Backstage:
    def __init__(self, home: str | None = None, socket: str = SOCKET) -> None:
        self.home = home or os.path.expanduser("~")
        self.socket = socket
        self.state = Path(tempfile.mkdtemp(prefix="director-backstage-"))
        self._count = 0
        self._numbers: dict[str, int] = {}  # window id -> command number

    @staticmethod
    def available() -> bool:
        return shutil.which("tmux") is not None

    def _tmux(self, *args: str, check: bool = True, timeout: float | None = 10) -> str:
        proc = subprocess.run(["tmux", "-L", self.socket, *args], capture_output=True, text=True, timeout=timeout)
        if check and proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"tmux {args[0]} failed")
        return proc.stdout

    def attach_command(self) -> list[str]:
        """What a terminal window runs to show backstage (creating it if needed)."""
        return ["tmux", "-L", self.socket, "new-session", "-A", "-s", SESSION, "-c", self.home]

    def ensure(self) -> None:
        """The session exists, set up for the director (also if something else started it,
        like a terminal showing backstage before the director ran anything)."""
        if subprocess.run(["tmux", "-L", self.socket, "has-session", "-t", SESSION],
                          capture_output=True).returncode != 0:
            self._tmux("new-session", "-d", "-s", SESSION, "-c", self.home, "-x", "200", "-y", "50")
        self._tmux("set-option", "-t", SESSION, "history-limit", str(HISTORY_LINES))
        # Command windows stay open after they finish, so their output can be read and
        # seen (a default for every window: this tmux server is the director's alone)...
        self._tmux("set-option", "-g", "-w", "remain-on-exit", "on")
        # ...but the user's own shell closes normally.
        self._tmux("set-option", "-w", "-t", f"{SESSION}:0", "remain-on-exit", "off")

    def start(self, command: str, interactive: bool, cwd: str | None = None) -> str:
        """Run `command` in a new window; returns the window id."""
        self.ensure()
        self._count += 1
        n = self._count
        if not interactive:
            # Nobody can type into it: an interactive program ends instead of waiting.
            command = "{ " + command + "\n} </dev/null"
        window = self._tmux(
            "new-window", "-d", "-P", "-F", "#{window_id}", "-t", SESSION, "-c", cwd or self.home,
            "-n", f"{n}: {command.split(chr(10))[0][:24]}",
            "-e", f"DIRECTOR_CMD={command}",
            "-e", f"DIRECTOR_STATUS={self.state / f'{n}.status'}",
            "-e", f"DIRECTOR_DONE=director-done-{n}",
            "bash", "-c", WRAPPER,
        ).strip()
        self._numbers[window] = n
        self._prune()
        return window

    def wait(self, window: str, timeout: float) -> Finished | Running | None:
        """Finished, or Running if still going after `timeout`; None if it vanished
        without recording how it ended."""
        status_file = self.state / f"{self._numbers[window]}.status"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if status_file.exists() and status_file.read_text().strip():
                return Finished(self._output_if_any(window), int(status_file.read_text()))
            if window not in self._windows():
                return None
            pane = self._tmux("display-message", "-p", "-t", window, "#{pane_dead} #{pane_dead_status}",
                              check=False).split()
            if pane and pane[0] == "1" and not status_file.exists():
                # The wrapper itself died (killed, say) before recording a status.
                return Finished(self._output_if_any(window), int(pane[1]) if len(pane) > 1 else 1)
            time.sleep(0.1)
        return Running(window)

    def _output_if_any(self, window: str) -> str:
        try:
            return self.output(window)
        except RuntimeError:  # the window was closed: the status is still known
            return "(the output is gone: its window was closed)"

    def output(self, window: str) -> str:
        lines = self._tmux("capture-pane", "-p", "-J", "-S", "-", "-E", "-", "-t", window).rstrip().splitlines()
        # tmux's own "Pane is dead (status 0, ...)" notice, and the empty screen rows above it.
        if lines and lines[-1].startswith("Pane is dead"):
            lines.pop()
        return "\n".join(lines).rstrip()

    def stop(self, window: str) -> None:
        self._tmux("kill-window", "-t", window, check=False)

    def select(self, window: str) -> None:
        self._tmux("select-window", "-t", window, check=False)

    def when_done(self, window: str, callback: Callable[[], None]) -> None:
        """Call `callback` (from another thread) once the command in `window` exits."""
        channel = f"director-done-{self._numbers[window]}"

        def wait() -> None:
            subprocess.run(["tmux", "-L", self.socket, "wait-for", channel], capture_output=True)
            callback()

        threading.Thread(target=wait, name=f"backstage-{channel}", daemon=True).start()

    def _windows(self) -> list[str]:
        out = self._tmux("list-windows", "-t", SESSION, "-F", "#{window_id}", check=False)
        return out.split()

    def _prune(self) -> None:
        out = self._tmux("list-windows", "-t", SESSION, "-F", "#{window_index} #{window_id} #{pane_dead}")
        commands = [line.split() for line in out.splitlines() if not line.startswith("0 ")]
        finished = [w for _, w, dead in commands if dead == "1"]
        for window in finished[: max(0, len(commands) - KEEP_WINDOWS)]:
            self.stop(window)
