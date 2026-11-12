{
  description = "Agent-oriented Linux desktop (working title TBD)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
      overlay = final: prev: { director = final.callPackage ./nix/director.nix { }; };
      testModules = [
        { nixpkgs.overlays = [ overlay ]; }
        ./nixos/modules/base.nix
        ./nixos/modules/stage.nix
        ./nixos/modules/undo.nix
      ];
      nixos = host: nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [ { nixpkgs.overlays = [ overlay ]; } host ];
      };
    in {
      overlays.default = overlay;

      packages = forAll (pkgs: rec {
        director = pkgs.callPackage ./nix/director.nix { };
        default = director;
      } // nixpkgs.lib.optionalAttrs (pkgs.stdenv.hostPlatform.system == "x86_64-linux") {
        # The scenario harness's driver. Not a check: it needs the network and the
        # host's Ollama (nixos/tests/scenarios.nix).
        scenarios = (import ./nixos/tests/scenarios.nix {
          pkgs = pkgs.extend overlay;
          modules = testModules ++ [ ./nixos/modules/dev.nix ];
        }).driver;
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [ ps.anthropic ps.pytest ]))
            pkgs.sway # stage (roadmap step 2): provides swaymsg for IPC
            pkgs.ollama # free local model backend
            pkgs.bubblewrap # bench/ sandbox
          ];
          shellHook = ''export PYTHONPATH="$PWD/src:$PYTHONPATH"'';
        };
      });

      # The machine this is developed on (dual boot next to Fedora), and a VM
      # with the same desktop for trying changes: nixos-rebuild build-vm --flake .#vm
      nixosConfigurations = {
        laptop = nixos ./nixos/hosts/laptop;
        vm = nixos ./nixos/hosts/vm;
      };

      checks.x86_64-linux.stage-undo = import ./nixos/tests/stage-undo.nix {
        pkgs = nixpkgs.legacyPackages.x86_64-linux.extend overlay;
        modules = testModules;
      };
    };
}
