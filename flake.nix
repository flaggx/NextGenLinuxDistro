{
  description = "Agent-oriented Linux desktop (working title TBD) - dev shell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in {
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [ ps.anthropic ps.pytest ]))
            pkgs.sway # stage (roadmap step 2): provides swaymsg for IPC
          ];
          shellHook = ''export PYTHONPATH="$PWD/src:$PYTHONPATH"'';
        };
      });
      # Roadmap step 5 (the distro image) will add nixosConfigurations here.
    };
}
