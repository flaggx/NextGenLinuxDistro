# A conventional KDE Plasma desktop for now. The director's own stage (a
# tiling compositor it controls, roadmap step 2) arrives as a second session.
{ ... }:

{
  services.displayManager.sddm = {
    enable = true;
    wayland.enable = true;
  };
  services.desktopManager.plasma6.enable = true;

  hardware.graphics.enable = true;
  hardware.bluetooth.enable = true;

  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    pulse.enable = true;
  };

  services.printing.enable = true;
  services.fwupd.enable = true;
  programs.firefox.enable = true;
}
