# The stage: Sway, stripped down. No panels, bars or menus: the director's
# conversation is the main window, and everything else is shown on demand
# (Design.md: "visuals assembled on demand instead of permanent chrome").
# A shell is always one key away: backstage.
{ config, lib, pkgs, ... }:

let
  lockCmd = "swaylock -f -c 1d1f21";

  # The conversation window's program: if the director exits (an error, or
  # Ctrl-D), say so and offer to start it again instead of the window vanishing.
  director-session = pkgs.writeShellScriptBin "director-session" ''
    while true; do
      director
      printf '\nThe director stopped. Press Enter to start it again.\n'
      read -r _ || exit 0
    done
  '';

  # Backstage (src/director/backstage.py): the terminal the director's commands
  # run in, one tab each, with the user's own shell as the first tab.
  director-backstage = pkgs.writeShellScriptBin "director-backstage" ''
    swaymsg '[app_id="backstage"] focus' >/dev/null 2>&1 \
      || swaymsg exec 'foot --app-id backstage --font=monospace:size=10 tmux -L director new-session -A -s backstage'
  '';

  # Back to the conversation: focus it, or open it again if it was closed.
  director-window = pkgs.writeShellScriptBin "director-window" ''
    swaymsg '[app_id="director"] focus' >/dev/null 2>&1 \
      || swaymsg exec 'foot --app-id director director-session'
  '';

  # Status on demand instead of a permanent bar.
  stage-status = pkgs.writeShellScriptBin "stage-status" ''
    time=$(date '+%a %d %b  %H:%M')
    bat=""
    for b in /sys/class/power_supply/BAT*; do
      [ -e "$b/capacity" ] && bat="Battery $(cat "$b/capacity")% ($(cat "$b/status"))"
    done
    wifi=$(nmcli -t -f active,ssid dev wifi 2>/dev/null | sed -n 's/^yes://p' | head -1)
    vol=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null | sed 's/Volume: //')
    zoom=$(swaymsg -t get_outputs -r | jq -r '[.[].scale] | max')
    notify-send -t 6000 "$time" "$(printf '%s\nWi-Fi: %s\nVolume: %s\nZoom: %sx (Super+0: normal)' \
      "$bat" "''${wifi:-off}" "''${vol:-?}" "''${zoom:-1}")"
  '';

  swayConfig = ''
    set $mod Mod4
    font pango:sans 10
    default_border pixel 2
    default_floating_border pixel 2
    gaps inner 4
    output * bg #1d1f21 solid_color
    client.focused #5f87af #5f87af #ffffff #5f87af #5f87af

    input type:touchpad {
      tap enabled
      natural_scroll enabled
    }

    # The director's conversation opens first, and stays.
    exec foot --app-id director director-session
    # Full screen alone, a strip along the bottom once anything else opens.
    exec director-dock
    exec mako
    exec swayidle -w \
      timeout 300 '${lockCmd}' \
      timeout 600 'swaymsg "output * power off"' resume 'swaymsg "output * power on"' \
      before-sleep '${lockCmd}'

    bindsym $mod+space exec director-window
    bindsym $mod+Return exec director-backstage
    bindsym $mod+Shift+Return exec foot
    bindsym $mod+d exec fuzzel
    bindsym $mod+i exec stage-status
    bindsym $mod+0 output * scale 1
    bindsym $mod+n exec foot -e nmtui
    bindsym $mod+b exec foot -e bluetuith
    bindsym $mod+a exec foot -e pulsemixer
    bindsym $mod+Escape exec ${lockCmd}
    bindsym $mod+q kill
    bindsym $mod+Shift+e exec swaynag -t warning -m 'Log out?' -B 'Log out' 'swaymsg exit'
    bindsym $mod+Shift+c reload

    bindsym $mod+Left focus left
    bindsym $mod+Down focus down
    bindsym $mod+Up focus up
    bindsym $mod+Right focus right
    bindsym $mod+Shift+Left move left
    bindsym $mod+Shift+Down move down
    bindsym $mod+Shift+Up move up
    bindsym $mod+Shift+Right move right

    bindsym $mod+h splith
    bindsym $mod+v splitv
    bindsym $mod+s layout stacking
    bindsym $mod+w layout tabbed
    bindsym $mod+e layout toggle split
    bindsym $mod+f fullscreen
    bindsym $mod+Shift+space floating toggle
    bindsym $mod+r mode resize
    mode resize {
      bindsym Left resize shrink width 40px
      bindsym Right resize grow width 40px
      bindsym Up resize shrink height 40px
      bindsym Down resize grow height 40px
      bindsym Return mode default
      bindsym Escape mode default
    }

    ${lib.concatMapStrings (n: ''
      bindsym $mod+${n} workspace number ${n}
      bindsym $mod+Shift+${n} move container to workspace number ${n}
    '') [ "1" "2" "3" "4" "5" ]}

    bindsym XF86AudioRaiseVolume exec wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+
    bindsym XF86AudioLowerVolume exec wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
    bindsym XF86AudioMute exec wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
    bindsym XF86MonBrightnessUp exec brightnessctl set 5%+
    bindsym XF86MonBrightnessDown exec brightnessctl set 5%-
    bindsym Print exec grim -g "$(slurp)" - | wl-copy
    bindsym Shift+Print exec grim - | wl-copy

    # No bar: status is $mod+i.
    # NixOS's part: hands the session environment to systemd and starts
    # sway-session.target, which the polkit agent waits for.
    include /etc/sway/config.d/*
  '';
in
{
  programs.sway = {
    enable = true;
    wrapperFeatures.gtk = true;
    # The polkit agent (soteria) runs as a user service and needs the login
    # session's id, which NixOS's sway setup doesn't hand to systemd. Without
    # this it crash-loops and password prompts never appear.
    # (Not fatal: Sway must still start without a user service manager.)
    extraSessionCommands = ''
      systemctl --user import-environment XDG_SESSION_ID XDG_SESSION_TYPE || true
    '';
    # Only what the config above uses; the module's defaults include a menu and bar.
    extraPackages = with pkgs; [
      foot fuzzel mako libnotify swaylock swayidle grim slurp wl-clipboard
      brightnessctl pulsemixer bluetuith xdg-utils
      tmux jq director-session director-window director-backstage stage-status
    ];
  };
  environment.etc."sway/config".text = swayConfig;
  # Terminals (the director's window and shells): readable by default.
  # Ctrl+Shift+plus/minus changes it per window; the director's `zoom` scales everything.
  environment.etc."xdg/foot/foot.ini".text = ''
    [main]
    font=monospace:size=12
  '';

  environment.systemPackages = with pkgs; [
    # The director itself, built from this repo. The system runs this pinned
    # build; development happens in the checkout and lands with a rebuild.
    director
    # Props (roadmap step 3): what the director's `open` shows things with.
    zathura
    imv
  ];
  xdg.mime.defaultApplications = {
    "application/pdf" = "org.pwmt.zathura-pdf-mupdf.desktop";
  } // lib.genAttrs [ "image/png" "image/jpeg" "image/gif" "image/webp" "image/svg+xml" ] (_: "imv.desktop");

  # Login: a plain text greeter that starts Sway.
  services.greetd = {
    enable = true;
    settings.default_session = {
      command = "${pkgs.tuigreet}/bin/tuigreet --time --remember --asterisks --cmd sway";
      user = "greeter";
    };
  };

  # Password prompts for anything that needs admin rights.
  security.soteria.enable = true;

  # File pickers and screen sharing in apps.
  xdg.portal = {
    enable = true;
    wlr.enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
    config.common.default = [ "wlr" "gtk" ];
  };

  environment.sessionVariables = {
    DIRECTOR_BACKEND = "local";
    NIXOS_OZONE_WL = "1"; # Electron and Chromium apps on Wayland
  };

  fonts.packages = with pkgs; [ noto-fonts noto-fonts-color-emoji dejavu_fonts ];

  hardware.graphics.enable = true;
  hardware.bluetooth.enable = true;
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    pulse.enable = true;
  };
  services.power-profiles-daemon.enable = true;
  services.printing.enable = true;
  services.fwupd.enable = true;
  programs.firefox.enable = true;
}
