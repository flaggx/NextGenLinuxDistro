# Developing the distro on itself.
{ pkgs, ... }:

{
  environment.systemPackages = with pkgs; [
    git
    gh
    claude-code
    python3
    bubblewrap # bench/ sandbox
    nodejs
    ripgrep
    jq
    pciutils
    nvtopPackages.full
  ];

  # Lets prebuilt Linux binaries (installers, npm/pip wheels) run on NixOS.
  programs.nix-ld.enable = true;
}
