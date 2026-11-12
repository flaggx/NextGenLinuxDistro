import subprocess

import pytest

from director.permissions import Tier
from director.tools.base import ToolError
from director.tools.shell import RunCommand
from director.tools.software import FindProgram, InstallProgram, Nix, RemoveProgram, RunProgram


class FakeNix:
    """Answers the nix commands the tools use; records the rest."""

    def __init__(self, packages=None, installed=()):
        self.packages = packages or {"fastfetch": "neofetch-like system information tool"}
        self.installed = list(installed)
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        ok = lambda out="": subprocess.CompletedProcess(argv, 0, out, "")
        if argv[:3] == ["nix", "eval", "--raw"]:
            name = argv[3].removeprefix("nixpkgs#").removesuffix(".meta.description")
            if name in self.packages:
                return ok(self.packages[name])
            return subprocess.CompletedProcess(argv, 1, "", "error: flake 'flake:nixpkgs' does not provide attribute")
        if argv[:3] == ["nix", "profile", "list"]:
            import json
            return ok(json.dumps({"elements": {n: {} for n in self.installed}, "version": 3}))
        if argv[:3] == ["nix", "profile", "add"]:
            self.installed.append(argv[3].removeprefix("nixpkgs#"))
            return ok()
        if argv[:3] == ["nix", "profile", "remove"]:
            self.installed.remove(argv[3])
            return ok()
        if argv[:2] == ["nix", "search"]:
            return ok('{"legacyPackages.x86_64-linux.fastfetch": {"description": "system info"}}')
        raise AssertionError(argv)


class RecordingShell(RunCommand):
    def __init__(self):
        super().__init__()
        self.ran = []

    def run(self, args):
        self.ran.append(args)
        return f"ran {args['command']}\n[exit 0]"


def test_install_asks_with_the_packages_own_description():
    nix = FakeNix()
    tool = InstallProgram(Nix(run=nix))
    assert tool.tier({"name": "fastfetch"}) is Tier.APPROVE
    request = tool.approval_request({"name": "fastfetch"})
    assert request.summary == "install fastfetch (neofetch-like system information tool)"
    assert request.detail == "nix profile add nixpkgs#fastfetch"
    assert tool.run({"name": "fastfetch"}) == "Installed fastfetch."
    assert nix.installed == ["fastfetch"]


def test_install_and_run_is_one_approval_and_shows_it():
    shell = RecordingShell()
    nix = Nix(run=FakeNix())
    tool = InstallProgram(nix, RunProgram(nix, shell))
    assert "and start it" in tool.approval_request({"name": "fastfetch", "run": True}).summary
    tool.run({"name": "fastfetch", "run": True})
    assert shell.ran[-1]["show"] is True and "fastfetch" in shell.ran[-1]["command"]


def test_unknown_or_already_installed_packages_never_reach_the_user():
    tool = InstallProgram(Nix(run=FakeNix(installed=["fastfetch"])))
    with pytest.raises(ToolError, match="no package called 'fastfetchh'"):
        tool.approval_request({"name": "fastfetchh"})
    with pytest.raises(ToolError, match="already installed"):
        tool.approval_request({"name": "fastfetch"})


def test_names_that_are_not_package_names_are_rejected():
    nix = FakeNix()
    with pytest.raises(ToolError):
        InstallProgram(Nix(run=nix)).approval_request({"name": "fastfetch; rm -rf ~"})
    assert not any(a[:2] == ["nix", "eval"] for a in nix.calls)


def test_run_program_fetches_what_isnt_installed_and_shows_it():
    shell = RecordingShell()
    name = "zz-not-on-this-machine"
    tool = RunProgram(Nix(run=FakeNix({name: "a demo"})), shell)
    request = tool.approval_request({"name": name, "args": ["--logo", "small"]})
    assert request.summary == f"run {name} --logo small on screen (not installed: fetched just for this run)"
    tool.run({"name": name, "args": ["--logo", "small"]})
    assert shell.ran[-1] == {"command": f"nix shell 'nixpkgs#{name}' -c {name} --logo small",
                             "purpose": f"run {name}", "show": True}


def test_run_program_quotes_arguments():
    shell = RecordingShell()
    RunProgram(Nix(run=FakeNix()), shell).run({"name": "echo", "args": ["a; rm -rf ~"]})
    assert shell.ran[-1]["command"] == "echo 'a; rm -rf ~'"


def test_remove_only_what_is_installed():
    nix = FakeNix(installed=["fastfetch"])
    tool = RemoveProgram(Nix(run=nix))
    with pytest.raises(ToolError, match="isn't installed"):
        tool.approval_request({"name": "htop"})
    assert tool.approval_request({"name": "fastfetch"}).summary == "uninstall fastfetch"
    tool.run({"name": "fastfetch"})
    assert nix.installed == []


def test_find_program_lists_names_and_descriptions():
    assert FindProgram(Nix(run=FakeNix())).run({"query": "system info"}) == "fastfetch: system info"
