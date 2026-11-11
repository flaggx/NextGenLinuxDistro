# Running the distro

`nixosConfigurations.laptop` is the machine this is developed on: NixOS with
KDE, next to Fedora. `nixosConfigurations.vm` is the same desktop in a VM.

```
nixos/
  modules/      base, desktop (KDE), nvidia (hybrid, desktop on Intel), ollama, dev
  hosts/laptop  Alienware 16 Aurora: disk layout, bus IDs, shared Ollama models
  hosts/vm      for trying changes:  nixos-rebuild build-vm --flake .#vm
```

Once installed, every system change is a commit to this repo, applied with
`sudo nixos-rebuild switch --flake ~/clones/NextGenLinuxDistro#laptop`. A bad
change is undone by picking the previous generation in the boot menu.

## Installing next to Fedora

Both systems live on the same LUKS-encrypted btrfs volume as separate
subvolumes, so nothing is repartitioned and they share the free space. Fedora
keeps working throughout and stays in the boot menu.

### 1. On Fedora

1. **Back up your home folder** to another disk. The steps below don't touch
   Fedora's data, but a typo during an install can.
2. Check Fedora's boot loader is where the NixOS boot menu expects it:
   `sudo ls /boot/efi/EFI/fedora/shimx64.efi`. If not, fix the path in
   `hosts/laptop/hardware.nix` (`extraEntries`).
3. Move Ollama's models to a subvolume both systems mount (about 65 GB, but a
   reflink copy is instant and takes no extra space):

   ```bash
   sudo mkdir -p /mnt/top /srv/ollama-models
   sudo mount -o subvolid=5 /dev/mapper/luks-a42b6f24-79fa-4934-a28d-07b6ba886f98 /mnt/top
   sudo btrfs subvolume create /mnt/top/shared-ollama
   sudo systemctl stop ollama
   sudo cp -a --reflink=always /var/lib/ollama/.ollama/models/. /mnt/top/shared-ollama/
   sudo chown -R ollama:ollama /mnt/top/shared-ollama
   echo 'UUID=8847f182-1156-45d3-af75-97a610d302a5 /srv/ollama-models btrfs subvol=shared-ollama,compress=zstd:1 0 0' | sudo tee -a /etc/fstab
   sudo systemctl daemon-reload && sudo mount /srv/ollama-models
   sudo mkdir -p /etc/systemd/system/ollama.service.d
   printf '[Service]\nEnvironment=OLLAMA_MODELS=/srv/ollama-models\n' | sudo tee /etc/systemd/system/ollama.service.d/models.conf
   sudo systemctl daemon-reload && sudo systemctl start ollama && ollama list
   ```

   Once `ollama list` shows the models, the old copy can go:
   `sudo rm -r /var/lib/ollama/.ollama/models`.
4. Write a NixOS installer (unstable, graphical ISO) to a USB stick, e.g. with
   Fedora Media Writer.

### 2. From the installer

Boot the USB stick (F12 on the Alienware for the boot menu), connect to
Wi-Fi, then open a terminal:

```bash
sudo -i
cryptsetup open /dev/nvme0n1p3 cryptroot

# New subvolumes for NixOS, next to Fedora's root and home.
mkdir -p /mnt-top && mount -o subvolid=5 /dev/mapper/cryptroot /mnt-top
for s in nixos-root nixos-home nixos-nix; do btrfs subvolume create /mnt-top/$s; done
umount /mnt-top

o=compress=zstd:1,noatime
mount -o subvol=nixos-root,$o /dev/mapper/cryptroot /mnt
mkdir -p /mnt/{home,nix,boot,srv/ollama-models,mnt/fedora-home}
mount -o subvol=nixos-home,$o /dev/mapper/cryptroot /mnt/home
mount -o subvol=nixos-nix,$o /dev/mapper/cryptroot /mnt/nix
mount -o subvol=shared-ollama,$o /dev/mapper/cryptroot /mnt/srv/ollama-models
mount -o subvol=home,$o /dev/mapper/cryptroot /mnt/mnt/fedora-home
mount -o fmask=0077,dmask=0077 /dev/nvme0n1p1 /mnt/boot

# Compare with hosts/laptop/hardware.nix; fix anything that differs.
nixos-generate-config --root /mnt --show-hardware-config

# The repo is already on disk, in Fedora's home.
nixos-install --flake /mnt/mnt/fedora-home/baldur/clones/NextGenLinuxDistro#laptop
nixos-enter --root /mnt -c 'passwd baldur'
reboot
```

`nixos-install` asks for a root password at the end. The first install
downloads a few GB; CUDA packages come from cache.nixos-cuda.org (see
`modules/base.nix`), so nothing should need hours of compiling.

### 3. First boot

Pick NixOS in the boot menu (Fedora is listed below it) and log in to Plasma.
Then check:

| What | How | Expect |
|---|---|---|
| NVIDIA driver | `nvidia-smi` | RTX 5060 listed |
| Desktop on Intel | `nvidia-smi` while idle | no Plasma processes on the GPU |
| GPU powers off | `cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status` with no model loaded | `suspended` |
| Ollama on GPU | `ollama run lfm3:1.7b hi && ollama ps` | `100% GPU`, models shared with Fedora |
| Shared checkout | `ls ~/clones` | same as on Fedora |
| Director | `director --backend local --model lfm3:1.7b what time is it` | an answer |
| Benchmark | `python -m bench.run lfm3:1.7b --tasks time,mkdir,declined` in the repo | 3 passes |

### If something goes wrong

- **NixOS won't boot:** pick an older generation in the boot menu, or boot
  Fedora (from the menu, or F12 then Fedora).
- **The boot menu itself is broken:** F12, pick Fedora. Fedora's own boot entry is untouched.
- **Giving up on NixOS:** from Fedora, delete the `nixos-*` subvolumes and
  NixOS's files in the ESP (`/boot/efi/EFI/nixos`, `loader/`), and make Fedora
  first again with `efibootmgr`. The shared models stay usable by Fedora.
