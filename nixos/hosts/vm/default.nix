# The laptop's desktop in a VM, for trying changes without rebooting:
#   nixos-rebuild build-vm --flake .#vm && ./result/bin/run-*-vm
# Start it from a folder of its own: its disks are created there.
# No NVIDIA here, so Ollama runs on the CPU.
{ pkgs, ... }:

{
  imports = [
    ../../modules/base.nix
    ../../modules/stage.nix
    ../../modules/undo.nix
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
    # /home on its own btrfs disk, as on the laptop, so undo (snapper) works.
    # The image is kept next to the VM's main disk, in the folder it's started from.
    emptyDiskImages = [{ size = 8192; driveConfig.deviceExtraOpts.serial = "home"; }];
    fileSystems."/home" = {
      device = "/dev/disk/by-id/virtio-home";
      fsType = "btrfs";
      autoFormat = true;
      # Mounted before users are set up, so the home folder lands on this disk.
      neededForBoot = true;
    };
    # Sway needs accelerated graphics: QEMU's virtual 3D GPU (virgl).
    qemu.options = [ "-vga none" "-device virtio-vga-gl" "-display gtk,gl=on" ];
  };
  boot.initrd.supportedFilesystems = [ "btrfs" ];

  # build-vm replaces these; they only need to exist for the config to evaluate.
  fileSystems."/" = { device = "/dev/disk/by-label/nixos"; fsType = "ext4"; };
  boot.loader.grub.device = "nodev";
  nixpkgs.hostPlatform = "x86_64-linux";
}
