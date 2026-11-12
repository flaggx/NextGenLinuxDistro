# The laptop's desktop in a VM, for trying changes without rebooting:
#   nixos-rebuild build-vm --flake .#vm && ./result/bin/run-*-vm
# Start it from a folder of its own: its disks are created there.
# The director uses the host's Ollama (GPU, models already downloaded) at
# 10.0.2.2, which QEMU's user network maps to the host; none runs in the VM.
{ ... }:

{
  imports = [
    ../../modules/base.nix
    ../../modules/stage.nix
    ../../modules/undo.nix
    ../../modules/dev.nix
  ];

  networking.hostName = "director-vm";
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
    # No 3D: a Nix-built QEMU can't find the host's graphics drivers on a
    # non-NixOS host (Fedora), so Sway draws in software instead (below).
    qemu.options = [ "-vga none" "-device virtio-vga" ];
  };
  environment.sessionVariables = {
    WLR_RENDERER = "pixman";
    WLR_NO_HARDWARE_CURSORS = "1";
    OLLAMA_HOST = "10.0.2.2:11434";
  };
  boot.initrd.supportedFilesystems = [ "btrfs" ];

  # build-vm replaces these; they only need to exist for the config to evaluate.
  fileSystems."/" = { device = "/dev/disk/by-label/nixos"; fsType = "ext4"; };
  boot.loader.grub.device = "nodev";
  nixpkgs.hostPlatform = "x86_64-linux";
}
