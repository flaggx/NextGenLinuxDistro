# Running the distro

`nixosConfigurations.laptop` is the machine this is developed on: NixOS next to
Fedora, with the director's own stage instead of a desktop environment.
`nixosConfigurations.vm` is the same system in a VM.

```
nixos/
  modules/      base, stage (Sway, stripped down), undo (snapper on /home),
                nvidia (hybrid, desktop on Intel), ollama, dev
  hosts/laptop  Alienware 16 Aurora: disk layout, bus IDs, shared Ollama models
  hosts/vm      for trying changes (below)
  tests/        stage-undo: nix build .#checks.x86_64-linux.stage-undo
```

## The stage

You log in at a text prompt, and Sway opens with one window: the director's
conversation. There are no panels, bars or menus; the director opens what you
need, and anything it changes in your files can be undone ("undo that").

| Keys | Does |
|---|---|
| Super+Space | back to the director (reopens it if closed) |
| Super+Enter | backstage: the terminal the director's commands run in (one tab each) and your shell; or ask "show me the terminal" |
| Super+Shift+Enter | a separate terminal |
| Super+D | app launcher |
| Super+I | status: time, battery, Wi-Fi, volume |
| Super+N / B / A | Wi-Fi / Bluetooth / sound settings |
| Super+Q | close the window |
| Super+arrows, Super+Shift+arrows | move focus, move the window |
| Super+H / V / W / S / F | split side by side / top to bottom, tabs, stack, fullscreen |
| Super+1..5, Super+Shift+1..5 | switch workspace, send the window there |
| Super+Escape | lock |
| Super+Shift+E | log out |

## Trying it in a VM

```bash
mkdir -p ~/director-vm && cd ~/director-vm
nix build ~/clones/NextGenLinuxDistro#nixosConfigurations.vm.config.system.build.vm
TMPDIR=$PWD USE_TMPDIR=1 NIX_DISK_IMAGE=$PWD/disk.qcow2 ./result/bin/run-director-vm-vm
```

Log in as `baldur`, password `test`. Your own desktop may catch the Super key
first: click into the VM and press Ctrl+Alt+G so it gets the keyboard. The VM's disks live in that folder
(`disk.qcow2`, and `empty0.qcow2` for its btrfs `/home`); delete them to start
fresh. The director in the VM uses the host's Ollama (at 10.0.2.2), so Ollama
must be running on the host with `lfm3:1.7b` pulled; answers come from the
host's GPU.

Once installed, every system change is a commit to this repo, applied with
`sudo nixos-rebuild switch --flake ~/clones/NextGenLinuxDistro#laptop`. A bad
change is undone by picking the previous generation in the boot menu.

## Installing next to Fedora

Both systems live on the same LUKS-encrypted btrfs volume as separate
subvolumes, so nothing is repartitioned and they share the free space. Fedora
keeps working throughout and stays in the boot menu.

### 1. On Fedora

1. **Back up what you can't re-create** (at least `~/.ssh`), off this disk. The
   steps below don't touch Fedora's data, but a typo during an install can.
   Encrypt it if it leaves the machine:
   `tar -czf - -C ~ .ssh | gpg --symmetric --cipher-algo AES256 -o ~/ssh-backup.tar.gz.gpg`
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

Pick NixOS in the boot menu (Fedora is listed below it) and log in.
NixOS has its own home folder, so bring over your SSH keys from Fedora's:

```bash
cp -a /mnt/fedora-home/baldur/.ssh ~/ && ssh -T git@github.com
```

Then check:

| What | How | Expect |
|---|---|---|
| NVIDIA driver | `nvidia-smi` | RTX 5060 listed |
| Desktop on Intel | `nvidia-smi` while idle | no `sway` process on the GPU |
| GPU powers off | `cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status` with no model loaded | `suspended` |
| Ollama on GPU | `ollama run lfm3:1.7b hi && ollama ps` | `100% GPU`, models shared with Fedora |
| Shared checkout | `ls ~/clones` | same as on Fedora |
| Director | ask it the time in its window | an answer |
| Undo | `snapper -c home list`; ask it to create a folder, then "undo that" | a pre/post pair; the folder is gone |
| Benchmark | `python -m bench.run lfm3:1.7b --tasks time,mkdir,declined` in the repo | 3 passes |

### If something goes wrong

- **NixOS won't boot:** pick an older generation in the boot menu, or boot
  Fedora (from the menu, or F12 then Fedora).
- **The boot menu itself is broken:** F12, pick Fedora. Fedora's own boot entry is untouched.
- **Giving up on NixOS:** from Fedora, delete the `nixos-*` subvolumes and
  NixOS's files in the ESP (`/boot/efi/EFI/nixos`, `loader/`), and make Fedora
  first again with `efibootmgr`. The shared models stay usable by Fedora.
