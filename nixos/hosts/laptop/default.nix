# Alienware 16 Aurora (AC16250): Intel Core 7 240H, RTX 5060 Laptop (8 GB), 32 GB.
# Dual boots with Fedora; see nixos/README.md for the install.
{ ... }:

{
  imports = [
    ./hardware.nix
    ../../modules/base.nix
    ../../modules/stage.nix
    ../../modules/undo.nix
    ../../modules/nvidia.nix
    ../../modules/ollama.nix
    ../../modules/dev.nix
  ];

  networking.hostName = "KDEFNotebook";

  # From `lspci -D`: 0000:00:02.0 Intel, 0000:01:00.0 NVIDIA.
  director.nvidia = {
    intelBusId = "PCI:0:2:0";
    nvidiaBusId = "PCI:1:0:0";
  };

  # Ollama's models live on a subvolume Fedora shares, so neither system
  # downloads them twice. The uid matches Fedora's ollama user.
  services.ollama = {
    user = "ollama";
    group = "ollama";
    modelsDir = "/srv/ollama-models";
  };
  users.users.ollama.uid = 969;
  users.groups.ollama.gid = 969;
}
