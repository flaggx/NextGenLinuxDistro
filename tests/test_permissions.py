import pytest

from director.tools.shell import is_read_only


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
    "ls |& cat",
    "ls |",
    "| ls",
    "ls | | wc",
    "grep x '|' rm",
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
