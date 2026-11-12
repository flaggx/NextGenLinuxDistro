# Undo for the director's changes to files (src/director/undo.py): snapper
# takes btrfs snapshots of /home before and after each approved action. The
# director runs as the user; snapperd (root) does the snapshotting, and this
# config allows only the user, only on /home. /home must be btrfs.
{ config, lib, pkgs, ... }:

let
  users = [ "baldur" ];
in
{
  services.snapper = {
    configs.home = {
      SUBVOLUME = "/home";
      ALLOW_USERS = users;
      # Only the director's pre/post pairs: no hourly snapshots.
      TIMELINE_CREATE = false;
      NUMBER_CLEANUP = true;
      NUMBER_LIMIT = "50";
      NUMBER_MIN_AGE = "3600";
    };
    cleanupInterval = "1h";
  };

  # snapper keeps snapshots in /home/.snapshots, which must be a subvolume.
  systemd.services.snapper-home-init = {
    description = "Create /home/.snapshots for snapper";
    wantedBy = [ "multi-user.target" ];
    before = [ "snapperd.service" ];
    unitConfig.RequiresMountsFor = "/home";
    serviceConfig.Type = "oneshot";
    path = [ pkgs.btrfs-progs ];
    script = ''
      [ -e /home/.snapshots ] || btrfs subvolume create /home/.snapshots
    '';
  };

  environment.systemPackages = [ pkgs.snapper ];
}
