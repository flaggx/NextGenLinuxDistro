import json
import subprocess

import pytest

from director.permissions import Tier
from director.tools.base import ToolError
from director.tools.shell import RunCommand
from director.tools.software import FindProgram, InstallProgram, Nix, RemoveProgram, RunProgram


@pytest.fixture(autouse=True)
def nothing_installed_here(monkeypatch):
    """Independent of this machine's programs; tests that need one installed say so."""
    monkeypatch.setattr("director.tools.software.shutil.which", lambda name: None)
    monkeypatch.setenv("PATH", "")


class FakeNix:
    """Answers the nix commands the tools use; records the rest."""

    def __init__(self, packages=None, installed=()):
        self.packages = packages or {"fastfetch": "neofetch-like system information tool"}
        self.installed = list(installed)
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        ok = lambda out="": subprocess.CompletedProcess(argv, 0, out, "")
        if argv[:3] == ["nix", "eval", "--json"]:
            name = argv[3].removeprefix("nixpkgs#").removesuffix(".meta")
            if name in self.packages:
                found = self.packages[name]
                description, program = found if isinstance(found, tuple) else (found, None)
                return ok(json.dumps({"d": description, "p": program}))
            return subprocess.CompletedProcess(argv, 1, "", "error: flake 'flake:nixpkgs' does not provide attribute")
        if argv[:3] == ["nix", "profile", "list"]:
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


def test_a_package_whose_program_has_another_name_runs_the_installed_program(monkeypatch):
    # claude-code's program is `claude`; it's already on this computer, so nothing is fetched.
    monkeypatch.setattr("director.tools.software.shutil.which",
                        lambda name: "/run/current-system/sw/bin/claude" if name == "claude" else None)
    nix, shell = FakeNix({"claude-code": ("Agentic coding tool", "claude")}), RecordingShell()
    tool = RunProgram(Nix(run=nix), shell)
    assert "fetched" not in tool.approval_request({"name": "claude-code"}).summary
    tool.run({"name": "claude-code"})
    assert shell.ran[-1]["command"] == "claude"
    with pytest.raises(ToolError, match="already installed \\(its program is `claude`\\)"):
        InstallProgram(Nix(run=nix)).approval_request({"name": "claude-code"})


def test_find_program_puts_whats_installed_and_the_best_names_first(monkeypatch, tmp_path):
    (tmp_path / "claude").write_text("")
    (tmp_path / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    class SearchNix(FakeNix):
        def __call__(self, argv, timeout):
            if argv[:2] == ["nix", "search"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps({
                    "legacyPackages.x86_64-linux.cc-switch-cli": {"description": "manage Claude Code, Codex"},
                    "legacyPackages.x86_64-linux.claude-code": {"description": "Agentic coding tool"},
                }), "")
            return super().__call__(argv, timeout)

    out = FindProgram(Nix(run=SearchNix())).run({"query": "claude cli"})
    assert out.startswith("Already on this computer (start with run_program): claude")
    assert out.index("claude-code") < out.index("cc-switch-cli")


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
    assert shell.ran[-1] == {"command": f"NIXPKGS_ALLOW_UNFREE=1 nix shell 'nixpkgs#{name}' --impure -c {name} --logo small",
                             "purpose": f"run {name}", "show": True}


def test_run_program_quotes_arguments(monkeypatch):
    monkeypatch.setattr("director.tools.software.shutil.which", lambda name: "/bin/echo" if name == "echo" else None)
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
    assert FindProgram(Nix(run=FakeNix())).run({"query": "system info"}) == (
        "Available to install, best matches first:\nfastfetch: system info")


def desktop(directory, stem, exec_line, terminal="false"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stem}.desktop").write_text(
        f"[Desktop Entry]\nName={stem}\nExec={exec_line}\nTerminal={terminal}\n"
        f"[Desktop Action new-window]\nExec={exec_line.split()[0]} --new-window\n")


class LaunchingFakeNix(FakeNix):
    def __init__(self, outputs, **kw):
        super().__init__(**kw)
        self.outputs = outputs

    def __call__(self, argv, timeout):
        if argv[:2] == ["nix", "build"]:
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.outputs) + "\n", "")
        return super().__call__(argv, timeout)


def test_graphical_programs_get_their_own_window_not_a_terminal(tmp_path):
    out = tmp_path / "store" / "chromium"
    desktop(out / "share" / "applications", "chromium-browser", "chromium %U")
    (out / "bin").mkdir()
    (out / "bin" / "chromium").write_text("")
    launched, shell = [], RecordingShell()
    tool = RunProgram(Nix(run=LaunchingFakeNix([str(tmp_path / "store" / "chromium-man"), str(out)],
                                               packages={"chromium": "web browser"})),
                      shell, launch=launched.append, app_dirs=[])
    assert tool.run({"name": "chromium", "args": ["example.org"]}) == "Started chromium in its own window."
    assert launched == [[str(out / "bin" / "chromium"), "example.org"]]
    assert shell.ran == []  # no terminal


def test_terminal_programs_still_go_to_backstage(tmp_path):
    out = tmp_path / "store" / "htop"
    desktop(out / "share" / "applications", "htop", "htop", terminal="true")
    launched, shell = [], RecordingShell()
    tool = RunProgram(Nix(run=LaunchingFakeNix([str(out)], packages={"htop": "process viewer"})),
                      shell, launch=launched.append, app_dirs=[])
    tool.run({"name": "htop"})
    assert launched == [] and shell.ran[-1]["show"] is True


def test_installed_graphical_programs_are_found_in_the_profile(tmp_path, monkeypatch):
    apps = tmp_path / "profile" / "share" / "applications"
    desktop(apps, "org.gimp.GIMP", "gimp-3.0 %U")
    monkeypatch.setattr("director.tools.software.shutil.which", lambda name: f"/bin/{name}")
    launched = []
    RunProgram(Nix(run=FakeNix()), RecordingShell(), launch=launched.append, app_dirs=[apps]).run(
        {"name": "gimp-3.0"})
    assert launched == [["gimp-3.0"]]
