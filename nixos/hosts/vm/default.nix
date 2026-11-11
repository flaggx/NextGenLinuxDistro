# The laptop's desktop in a VM, for trying changes without rebooting:
#   nixos-rebuild build-vm --flake .#vm && ./result/bin/run-*-vm
# No NVIDIA here, so Ollama runs on the CPU.
{ pkgs, ... }:

{
  imports = [
    ../../modules/base.nix
    ../../modules/desktop.nix
    ../../modules/ollama.nix
    ../../modules/dev.nix
  ];

  networking.hostName = "director-vm";
  services.ollama.package = pkgs.ollama-cpu;
  users.users.baldur.initialPassword = "test";

  virtualisation.vmVariant.virtualisation = {
    memorySize = 8192;
    cores = 4;
    diskSize = 16384;
  };

  # build-vm replaces these; they only need to exist for the config to evaluate.
  fileSystems."/" = { device = "/dev/disk/by-label/nixos"; fsType = "ext4"; };
  boot.loader.grub.device = "nodev";
  nixpkgs.hostPlatform = "x86_64-linux";
}
