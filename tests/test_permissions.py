import pytest

from director.tools.shell import is_read_only


@pytest.mark.parametrize("cmd", ["ls -la", "cat notes.txt", "df -h", "find . -name '*.py'", "grep -r TODO src"])
def test_read_only(cmd):
    assert is_read_only(cmd)


@pytest.mark.parametrize("cmd", [
    "rm -rf ~/x",
    "ls; rm x",
    "cat a > b",
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
