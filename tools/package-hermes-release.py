"""Package a qualified worker deterministically and emit its pinned wheel manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def package_worker(source: Path, output: Path) -> Path:
    metadata = json.loads((source / "artifact.json").read_text())
    for key, value in {"artifactFormat": 1, "providerId": "pi-claude-cli", "workerProtocolVersion": 1, "buildPlatform": "linux", "buildArchitecture": "x64"}.items():
        if metadata.get(key) != value:
            raise ValueError(f"Unqualified worker metadata {key}: {metadata.get(key)!r}")
    version = metadata["packageVersion"]
    asset = f"hermes-claude-bridge-{version}-linux-x64.tar.gz"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / asset
    if archive.exists():
        raise FileExistsError(f"Refusing to replace {archive}")
    import gzip
    with archive.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w") as tar:
        for path in sorted(source.rglob("*")):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ValueError(f"Unsupported worker entry: {path}")
            relative = path.relative_to(source).as_posix()
            if any(part in {".git", "__pycache__"} for part in path.relative_to(source).parts) or path.name.endswith(".pyc") or path.name == ".env":
                raise ValueError(f"Unexpected private/development entry: {relative}")
            info = tar.gettarinfo(str(path), arcname=relative)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644
            if path.is_file():
                with path.open("rb") as stream:
                    tar.addfile(info, stream)
            else:
                tar.addfile(info)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"manifestVersion": 1, "packageVersion": version, "providerId": "pi-claude-cli", "workerProtocolVersion": 1, "artifacts": [{"platform": "linux", "architecture": "x64", "asset": asset, "sha256": digest}]}
    (output / "worker-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(f"{digest}  {asset}\n")
    print(json.dumps({"archive": str(archive), "manifest": str(output / "worker-manifest.json"), "sha256": digest}))
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    package_worker(args.source.resolve(), args.output.resolve())
