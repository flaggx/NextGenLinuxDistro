import pytest

from director.tools.shell import PIP_REFUSAL, RunCommand, is_read_only


@pytest.mark.parametrize("cmd", [
    "ls -la", "cat notes.txt", "df -h", "find . -name '*.py'", "grep -r TODO src",
    "grep -R 4471 ~ 2>/dev/null",
    "find / -name '*.conf' 2> /dev/null",
    "ls missing >/dev/null 2>&1",
    "du -sh ~ &>/dev/null",
    "cat notes.txt 2>&1",
    'grep -r "8080" ~/ | head -50',
    "ps aux | grep firefox | wc -l",
    "find ~ -name '*.log' 2>/dev/null | head",
    "du -sh ~/* 2>/dev/null|tail -5",
    "grep 'a|b' notes.txt",
    'echo $HOME && ls -la $HOME/.config/nixpkgs 2>/dev/null || echo "no nixpkgs dir"',
    "ls ~; df -h",
    "echo ${USER}",
    "which claude || which claude-code",
    "find ~/Documents -type f -printf '%s %p\\n' 2>/dev/null | sort -rn | head -n 1",
    "sort -t, -k3 -n expenses.csv",
    "du -s * | sort --numeric-sort --reverse",
])
def test_read_only(cmd):
    assert is_read_only(cmd)


@pytest.mark.parametrize("cmd", [
    "rm -rf ~/x",
    "ls; rm x",
    "cat a > b",
    "cat a 2>errors.txt",
    "cat a >> b",
    "ls 2>/dev/nullx",
    "ls 2>/dev/null/../../home/me/x",
    "ls>/dev/null; rm x",
    "ls 2>/dev/null; rm x",
    "ls 2>/dev/null | sh",
    "cat urls.txt | xargs rm",
    "find . -name '*.tmp' | head | sh",
    "ls | find . -delete",
    "ls || rm x",
    "ls && rm x",
    "ls & rm x",
    "ls &",
    "echo $(rm x)",
    "echo ${HOME:=x}",
    "echo `rm x`",
    "ls |& cat",
    "ls |",
    "| ls",
    "ls | | wc",
    "grep x '|' rm",
    "sort -o notes.txt notes.txt",
    "sort -onotes.txt notes.txt",
    "sort -rno out.txt in.txt",
    "sort --output=out.txt in.txt",
    "sort --out out.txt in.txt",
    "ls | sort --compress-program=sh",
    "sort --comp=sh big.txt",
    "echo $(whoami)",
    "ls | sh",
    "find . -delete",
    "find . -exec rm {} +",
    "find . -fprint out.txt",
    "sudo ls",
    "nixos-rebuild switch",
    "",
    "cat 'unterminated",
])
def test_needs_approval(cmd):
    assert not is_read_only(cmd)


@pytest.mark.parametrize("cmd", [
    "pip install fastfetch",
    "pip3 install --user fastfetch",
    "pip3.12 install requests",
    "/usr/bin/pip install x",
    "python3 -m pip install x",
    "pipx install fastfetch",
    "uv pip install x",
    "uv tool install x",
    "sudo pip install x",
    "sudo -H pip install x",
    "cd /tmp && pip install x",
    "true; pip install x",
    "echo hi | pip install x",
    "env pip install x",
    "bash -c 'pip install x'",
    'sh -c "cd /tmp; pip install x"',
    "nix shell nixpkgs#pip -c pip install requests",
    "nix shell nixpkgs#python3Packages.pip --command pip install requests",
    "nix run nixpkgs#python3Packages.pip -- install requests",
    "nix shell nixpkgs#pip install requests",
])
def test_pip_installs_are_refused_before_approval(cmd):
    assert RunCommand().refusal({"command": cmd, "purpose": "install"}) == PIP_REFUSAL


@pytest.mark.parametrize("cmd", [
    "pip list", "pip show requests", "grep 'pip install' README.md", "nix profile install nixpkgs#fastfetch",
    "echo pipinstall",
    "nix shell nixpkgs#fastfetch -c fastfetch",
    "nix profile add nixpkgs#python313Packages.requests",
    "nix search nixpkgs pip",
])
def test_other_pip_use_and_mentions_are_allowed(cmd):
    assert RunCommand().refusal({"command": cmd, "purpose": "x"}) is None
