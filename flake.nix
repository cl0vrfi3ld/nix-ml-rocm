{
  description = "nix-ml-rocm flake";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachSystem [ "x86_64-linux" ] (
      system:
      let
        # instantiate nixpkgs with ROCm enabled and CUDA disabled to force
        # the correct build variants for all downstream packages.
        pkgs = import nixpkgs {
          inherit system;
          config = {
            allowUnfree = true;
            rocmSupport = true;
            cudaSupport = false;
          };
        };

        # Helper function to generate attributes for a specific Python version
        mkMlPackages =
          pyVersion:
          let
            # pyVersion should be "311", "312", etc.
            # We access the python package set directly.
            ps = pkgs.${"python" + pyVersion + "Packages"};
          in
          {
            "torch-py${pyVersion}" = ps.torch;
            "torchaudio-py${pyVersion}" = ps.torchaudio;
            "torchvision-py${pyVersion}" = ps.torchvision;
          };
        # runtime deps
        runtimeDeps = with pkgs; [
          python312
          cachix
          curl
          jq
        ];
      in
      {
        # provide a dev shell env for working on the builder script
        devShells.default = pkgs.mkShell {
          packages = runtimeDeps;
        };
      
        apps.build-cache = {
          type = "app";
          program = "${
            pkgs.writeShellApplication {
              name = "build-cache";
              runtimeInputs = runtimeDeps;
              text = ''
                # ensure build script exists in PWD
                if [ ! -f "build_cache.py" ]; then
                  echo "Build script was not found in current directory"
                  exit 1
                fi

                # run build script
                python3 build_cache.py "$@"
              '';
            }
          }/bin/build-cache";
        };
        apps.default = self.apps.build-cache;

        # merge the package sets for all requested Python versions
        packages =
          (mkMlPackages "311")
          // (mkMlPackages "312")
          // (mkMlPackages "313")
          // {
            # ---------------------------------------------------
            # DIAGNOSTIC TARGET
            # Run: nix build .#test-artifact
            # ---------------------------------------------------
            test-artifact = pkgs.writeText "cachix-test" ''
              This is a test artifact for ml-rocm.
              Timestamp: ${toString self.lastModified}
              System: ${system}
            '';
          };
        # custom build groups for convenience
        buildGroups =
          let
            # Grab all package names once
            allPackages = builtins.attrNames self.packages.${system};

            # filters all packages by their prefix
            filterByPrefix = prefix: builtins.filter (name: pkgs.lib.hasPrefix prefix name) allPackages;
          in
          {
            # build by python version
            py312 = builtins.attrNames (mkMlPackages "312");
            py313 = builtins.attrNames (mkMlPackages "313");

            core-ml = filterByPrefix "torch-";
            vision = filterByPrefix "torchvision-";
            audio = filterByPrefix "torchaudio-";

            all = builtins.filter (name: name != "test-artifact") allPackages;
          };
      }
    );
}
