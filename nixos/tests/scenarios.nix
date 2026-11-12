# The real stage driven like a user would: requests typed into the director's
# window, approvals answered, outcomes checked against the design goals
# (scenarios.py). It needs the network and the host's Ollama, so it runs
# outside the Nix sandbox:
#
#   nix build .#scenarios && ./result/bin/nixos-test-driver -o results/
#   SCENARIOS=zoom,undo RUNS=3 ./result/bin/nixos-test-driver -o results/
#
# The director in the VM uses the host's Ollama (GPU, models already there)
# at 10.0.2.2, which QEMU's user networking maps to the host's loopback.
{ pkgs, modules }:

pkgs.testers.runNixOSTest {
  name = "scenarios";
  node.pkgsReadOnly = false; # base.nix sets nixpkgs.config
  nodes.machine = { lib, ... }: {
    imports = modules;
    virtualisation = {
      memorySize = 8192; # like the vm host; `nix profile add` evaluates nixpkgs (~3 GB)
      cores = 4;
      emptyDiskImages = [{ size = 4096; driveConfig.deviceExtraOpts.serial = "home"; }];
      fileSystems."/home" = {
        device = "/dev/disk/by-id/virtio-home";
        fsType = "btrfs";
        autoFormat = true;
        neededForBoot = true;
      };
      qemu.options = [ "-vga none" "-device virtio-vga" ];
    };
    boot.initrd.supportedFilesystems = [ "btrfs" ];
    # QEMU's user network (the outside world, and the host at 10.0.2.2).
    networking.interfaces.eth0.useDHCP = lib.mkForce true;

    # Straight into the stage, no login prompt.
    services.greetd.settings.initial_session = { command = "sway"; user = "baldur"; };
    environment.sessionVariables = {
      WLR_RENDERER = "pixman";
      WLR_NO_HARDWARE_CURSORS = "1";
      OLLAMA_HOST = "10.0.2.2:11434";
      DIRECTOR_LOG = "/home/baldur/director.jsonl";
    };
  };
  testScript = builtins.readFile ./scenarios.py;
}
