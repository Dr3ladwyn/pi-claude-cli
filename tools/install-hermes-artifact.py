"""Install a previously built local Hermes provider artifact into one profile."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True, help="Local directory produced by build:hermes")
    parser.add_argument("--profile-home", type=Path, help="Target Hermes profile home; defaults to HERMES_HOME")
    args = parser.parse_args()
    artifact = args.artifact.expanduser().resolve()
    profile = (args.profile_home or (Path(os.environ["HERMES_HOME"]) if os.environ.get("HERMES_HOME") else None))
    if profile is None:
        parser.error("--profile-home or HERMES_HOME is required")
    profile = profile.expanduser().resolve()
    metadata_path = artifact / "artifact.json"
    plugin_source = artifact / "plugin"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("artifactFormat") != 1 or metadata.get("providerId") != "pi-claude-cli" or metadata.get("workerProtocolVersion") != 1:
        raise SystemExit("Unsupported or mismatched Hermes worker artifact")
    if not (plugin_source / "plugin.yaml").is_file() or not (plugin_source / "runtime" / "src" / "adapters" / "hermes-worker" / "index.js").is_file():
        raise SystemExit("Artifact is missing the compiled worker or plugin metadata")
    target = profile / "plugins" / "model-providers" / "pi-claude-cli"
    if target.exists():
        raise SystemExit(f"Refusing to overwrite existing Hermes provider path: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(plugin_source, target, symlinks=False)
    (target / "artifact.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Installed pi-claude-cli {metadata['packageVersion']} worker protocol {metadata['workerProtocolVersion']} into {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
