# What every machine running the director has: Nix itself, locale, the user.
{ lib, pkgs, ... }:

{
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    # CUDA packages (ollama-cuda) aren't on cache.nixos.org; without this they
    # compile locally, which takes hours.
    substituters = [ "https://cache.nixos-cuda.org" ];
    trusted-public-keys = [ "cache.nixos-cuda.org:74DUi4Ye579gUqzH4ziL9IyiJBlDpMRn9MBN8oNan9M=" ];
    auto-optimise-store = true;
  };
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 30d";
  };
  # NVIDIA's driver, CUDA and Claude Code are unfree.
  nixpkgs.config.allowUnfree = true;

  time.timeZone = lib.mkDefault "America/New_York";
  i18n.defaultLocale = "en_US.UTF-8";
  console.keyMap = "us";

  # The newest kernel rather than the LTS default: new laptop hardware, and
  # closer to what Fedora runs.
  boot.kernelPackages = pkgs.linuxPackages_latest;

  networking.networkmanager.enable = true;
  zramSwap.enable = true;

  users.users.baldur = {
    isNormalUser = true;
    uid = 1000; # same as on Fedora, so shared files keep their owner
    extraGroups = [ "wheel" "networkmanager" "video" "render" ];
  };

  system.stateVersion = "26.11"; # the release current at install time; never change it afterwards
}
