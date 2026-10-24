{
  description = "Horse Tinder: swipe right on the horse of your dreams";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      runtimePython =
        pkgs:
        pkgs.python3.withPackages (ps: [
          ps.fastapi
          ps.uvicorn
        ]);
      devPython =
        pkgs:
        pkgs.python3.withPackages (ps: [
          ps.fastapi
          ps.uvicorn
          ps.httpx
          ps.pytest
        ]);
    in
    {
      packages = forAllSystems (pkgs: {
        default = pkgs.writeShellApplication {
          name = "horse-tinder";
          runtimeInputs = [ (runtimePython pkgs) ];
          text = ''
            export PYTHONPATH=${./backend}
            export HORSE_TINDER_FRONTEND="''${HORSE_TINDER_FRONTEND:-${./frontend}}"
            exec python -m horse_tinder.app "$@"
          '';
        };

        # Self-hosted Renovate. The nix manager shells out to `nix` and `git`,
        # so both are pinned here alongside Renovate itself.
        renovate = pkgs.writeShellApplication {
          name = "renovate-self-hosted";
          runtimeInputs = [
            pkgs.renovate
            pkgs.nix
            pkgs.git
          ];
          text = ''
            export RENOVATE_CONFIG_FILE="''${RENOVATE_CONFIG_FILE:-${./renovate/global.json}}"
            exec renovate "$@"
          '';
        };
      });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.system}.default}/bin/horse-tinder";
          meta.description = "Run the Horse Tinder server";
        };

        renovate = {
          type = "app";
          program = "${self.packages.${pkgs.system}.renovate}/bin/renovate-self-hosted";
          meta.description = "Run self-hosted Renovate with this repo's global config";
        };
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (devPython pkgs)
            pkgs.ruff
            pkgs.sqlite
          ];
        };
      });

      checks = forAllSystems (pkgs: {
        lint = pkgs.runCommand "horse-tinder-lint" { nativeBuildInputs = [ pkgs.ruff ]; } ''
          cd ${self}
          ruff check --no-cache .
          ruff format --no-cache --check .
          touch $out
        '';

        tests = pkgs.runCommand "horse-tinder-tests" { nativeBuildInputs = [ (devPython pkgs) ]; } ''
          cp -r ${self} src
          chmod -R u+w src
          cd src
          pytest -p no:cacheprovider
          touch $out
        '';

        package = self.packages.${pkgs.system}.default;
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
