# Hybrid graphics: the desktop runs on the Intel GPU, and the NVIDIA GPU is
# kept for local models. That leaves all its memory to the models, and lets it
# power off completely when the director unloads them.
{ config, lib, ... }:

{
  options.director.nvidia = {
    intelBusId = lib.mkOption { type = lib.types.str; example = "PCI:0:2:0"; };
    nvidiaBusId = lib.mkOption { type = lib.types.str; example = "PCI:1:0:0"; };
  };

  config = {
    services.xserver.videoDrivers = [ "nvidia" ];
    hardware.nvidia = {
      # Blackwell (RTX 50) is only supported by the open kernel module.
      open = true;
      package = config.boot.kernelPackages.nvidiaPackages.stable;
      modesetting.enable = true;
      powerManagement.enable = true;
      # Power the GPU off when nothing uses it (needs offload mode).
      powerManagement.finegrained = true;
      prime = {
        offload.enable = true;
        offload.enableOffloadCmd = true; # `nvidia-offload <app>` to run an app on NVIDIA
        inherit (config.director.nvidia) intelBusId nvidiaBusId;
      };
    };
  };
}
