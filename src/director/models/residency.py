"""Keeping the worker model in memory only while it earns its place.

Ollama does the loading and unloading; keep_alive on each request decides how
long a model stays (see LocalModel). This adds the decisions Ollama can't make:
don't load the worker when it won't fit or the laptop is on battery, and push it
out when the machine needs the memory or the power back.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import urllib.request
from typing import Any, Callable

from ..system import memory_available, on_battery
from .local import endpoint_from_env

GiB = 1024**3
# Room the rest of the desktop keeps no matter what.
RESERVE_BYTES = 4 * GiB
# A loaded model needs more than its file: context cache and runtime buffers.
LOAD_OVERHEAD_BYTES = 2 * GiB

Api = Callable[[str, dict[str, Any] | None], dict[str, Any]]


def ollama_api(endpoint: str | None = None) -> Api:
    base = endpoint or endpoint_from_env()

    def call(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data), timeout=30) as r:
            return json.loads(r.read())

    return call


def gpu_memory_free() -> int:
    """Free NVIDIA video memory in bytes; 0 without an NVIDIA GPU."""
    if not shutil.which("nvidia-smi"):
        return 0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return sum(int(line) for line in out.split()) * 1024**2
    except (subprocess.SubprocessError, ValueError):
        return 0


class Residency:
    def __init__(
        self,
        worker: str,
        api: Api | None = None,
        reserve_bytes: int = RESERVE_BYTES,
        battery: Callable[[], bool] = on_battery,
        ram_free: Callable[[], int] = memory_available,
        vram_free: Callable[[], int] = gpu_memory_free,
    ) -> None:
        self.worker = worker
        self.api = api or ollama_api()
        self.reserve_bytes = reserve_bytes
        self.battery = battery
        self.ram_free = ram_free
        self.vram_free = vram_free

    def loaded(self) -> set[str]:
        return {m["name"] for m in self.api("/api/ps", None).get("models", [])}

    def worker_loaded(self) -> bool:
        return self.worker in self.loaded()

    def why_worker_cant_load(self) -> str | None:
        """None if the worker can be used now, else a plain reason."""
        if self.worker_loaded():
            return None
        if self.battery():
            return "the laptop is on battery"
        size = next((m["size"] for m in self.api("/api/tags", None).get("models", [])
                     if m["name"] == self.worker), None)
        if size is None:
            return f"{self.worker} isn't downloaded"
        # What doesn't fit in video memory lands in system memory.
        needed = size + LOAD_OVERHEAD_BYTES - self.vram_free()
        spare = self.ram_free() - self.reserve_bytes
        if needed > spare:
            return f"it needs {needed / 1e9:.0f} GB of memory and only {max(spare, 0) / 1e9:.0f} GB is free"
        return None

    def unload(self, name: str) -> None:
        self.api("/api/generate", {"model": name, "keep_alive": 0})

    def check(self) -> str | None:
        """Unload the worker if the machine needs the power or memory back. Returns why, if it did."""
        if not self.worker_loaded():
            return None
        if self.battery():
            reason = "the laptop went on battery"
        elif self.ram_free() < self.reserve_bytes:
            reason = "memory is running low"
        else:
            return None
        self.unload(self.worker)
        return reason

    def watch(self, interval: float = 30.0, on_unload: Callable[[str], None] | None = None) -> threading.Event:
        """Run check() every `interval` seconds in the background. Set the returned event to stop."""
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(interval):
                try:
                    reason = self.check()
                except Exception:  # Ollama restarting, say: try again next round
                    continue
                if reason and on_unload:
                    on_unload(reason)

        threading.Thread(target=loop, name="residency", daemon=True).start()
        return stop
