{ lib, python3Packages }:

python3Packages.buildPythonApplication {
  pname = "director";
  version = "0.0.1";
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [ ../pyproject.toml ../README.md ../src ../tests ];
  };

  build-system = [ python3Packages.hatchling ];
  dependencies = [ python3Packages.anthropic ];
  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  meta = {
    description = "The orchestration layer (the director) for an agent-oriented Linux desktop";
    mainProgram = "director";
  };
}
