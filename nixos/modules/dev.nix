# Developing the distro on itself.
{ pkgs, ... }:

{
  environment.systemPackages = with pkgs; [
    # The director itself, built from this repo. The system runs this pinned
    # build; development happens in the checkout and lands with a rebuild.
    director

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
