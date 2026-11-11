"""What the director needs to know about the machine it runs on."""

from __future__ import annotations

from pathlib import Path

POWER_SUPPLY = Path("/sys/class/power_supply")
MEMINFO = Path("/proc/meminfo")


def on_battery(supplies: Path = POWER_SUPPLY) -> bool:
    """True on a laptop running from its battery; False when plugged in, or on a desktop."""
    if not supplies.is_dir():
        return False
    kinds = {s: (s / "type").read_text().strip() for s in supplies.iterdir() if (s / "type").exists()}
    if "Battery" not in kinds.values():
        return False
    return not any(
        kind in ("Mains", "USB") and (s / "online").exists() and (s / "online").read_text().strip() == "1"
        for s, kind in kinds.items()
    )


def memory_available(meminfo: Path = MEMINFO) -> int:
    """Bytes the kernel could hand out without swapping (MemAvailable)."""
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("MemAvailable missing from /proc/meminfo")
