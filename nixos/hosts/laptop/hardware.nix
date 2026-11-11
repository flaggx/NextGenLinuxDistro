# Disk layout, shared with Fedora on one LUKS-encrypted btrfs volume:
#
#   nvme0n1p1  ESP (vfat)       Fedora's /boot/efi, NixOS's /boot
#   nvme0n1p2  ext4             Fedora's /boot only
#   nvme0n1p3  LUKS -> btrfs    subvolumes:
#     root, home                Fedora
#     nixos-root, nixos-home,
#     nixos-nix                 NixOS
#     shared-ollama             both: Ollama models
#
# Fedora's home is mounted too, so ~/clones is the same checkout in both.
# Verify against `nixos-generate-config --show-hardware-config` on install day.
{ config, lib, modulesPath, ... }:

let
  btrfs = "/dev/disk/by-uuid/8847f182-1156-45d3-af75-97a610d302a5";
  subvol = name: {
    device = btrfs;
    fsType = "btrfs";
    options = [ "subvol=${name}" "compress=zstd:1" "noatime" ];
  };
in
{
  imports = [ (modulesPath + "/installer/scan/not-detected.nix") ];

  boot.initrd.availableKernelModules = [ "xhci_pci" "thunderbolt" "nvme" "usb_storage" "sd_mod" ];
  boot.kernelModules = [ "kvm-intel" ];
  hardware.cpu.intel.updateMicrocode = true;
  hardware.enableRedistributableFirmware = true;

  boot.initrd.luks.devices.cryptroot.device = "/dev/disk/by-uuid/a42b6f24-79fa-4934-a28d-07b6ba886f98";

  fileSystems = {
    "/" = subvol "nixos-root";
    "/home" = subvol "nixos-home";
    "/nix" = subvol "nixos-nix";
    "/srv/ollama-models" = subvol "shared-ollama";
    "/mnt/fedora-home" = subvol "home";
    "/boot" = {
      device = "/dev/disk/by-uuid/F3FE-299F";
      fsType = "vfat";
      options = [ "fmask=0077" "dmask=0077" ];
    };
  };

  systemd.tmpfiles.rules = [ "L /home/baldur/clones - - - - /mnt/fedora-home/baldur/clones" ];

  boot.loader.systemd-boot = {
    enable = true;
    # The ESP is 600 MB and Fedora uses it too; each generation adds a kernel.
    configurationLimit = 5;
    # Fedora's GRUB, via its shim, as a menu entry.
    extraEntries."fedora.conf" = ''
      title Fedora
      efi /EFI/fedora/shimx64.efi
      sort-key z_fedora
    '';
  };
  boot.loader.efi.canTouchEfiVariables = true;

  nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
}
