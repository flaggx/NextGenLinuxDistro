from director.system import NIXOS_CONTEXT, os_context


def test_nixos_gets_instructions_other_systems_dont(tmp_path):
    release = tmp_path / "os-release"
    release.write_text('NAME=NixOS\nID=nixos\nVERSION_ID="26.11"\n')
    assert os_context(release) == NIXOS_CONTEXT
    assert "nix profile add" in NIXOS_CONTEXT and "apt" in NIXOS_CONTEXT
    release.write_text('NAME="Fedora Linux"\nID=fedora\n')
    assert os_context(release) == ""
    assert os_context(tmp_path / "missing") == ""
