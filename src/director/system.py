"""What the director needs to know about the machine it runs on."""

from __future__ import annotations

from pathlib import Path

POWER_SUPPLY = Path("/sys/class/power_supply")
MEMINFO = Path("/proc/meminfo")
OS_RELEASE = Path("/etc/os-release")

# What a model needs to know about the operating system, added to its system prompt.
NIXOS_CONTEXT = """
This computer runs NixOS. There is no apt, dnf, pacman or snap, and pip \
installs are blocked: never use them. For software, use the tools rather than \
writing nix commands: install_program (run=true to start it afterwards), \
run_program to start a program on screen (installed or not), remove_program, \
and find_program only when you don't know a package's name. System-wide \
changes (services, drivers, packages for every user) belong in the NixOS \
configuration and need a rebuild with root: describe the change to the user \
instead of running sudo.
"""


def os_context(os_release: Path = OS_RELEASE) -> str:
    """Instructions for the operating system the director runs on, if it needs any."""
    try:
        fields = dict(line.split("=", 1) for line in os_release.read_text().splitlines() if "=" in line)
    except OSError:
        return ""
    return NIXOS_CONTEXT if fields.get("ID", "").strip('"') == "nixos" else ""


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
