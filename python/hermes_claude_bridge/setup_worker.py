from __future__ import annotations

import hashlib
import json
import os
import platform as host_platform
import shutil
import stat
import tarfile
import tempfile
import urllib.request
from urllib.parse import urlparse
from pathlib import Path, PurePosixPath

VERSION = "0.5.1"
PROVIDER_ID = "pi-claude-cli"
PROTOCOL_VERSION = 1
RELEASE_REPO = "ramarivera/pi-claude-cli"
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024


def default_cache_root() -> Path:
    configured = os.environ.get("HERMES_CLAUDE_BRIDGE_CACHE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "hermes-claude-bridge"


def host_target() -> tuple[str, str]:
    system = host_platform.system().lower()
    machine = host_platform.machine().lower()
    architectures = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}
    if system not in {"linux", "darwin", "windows"} or machine not in architectures:
        raise RuntimeError(f"Unsupported worker platform {system}/{machine}. The initial bundle supports Linux x64 only.")
    result = system, architectures[machine]
    if result != ("linux", "x64"):
        raise RuntimeError(f"No Hermes worker is released for {result[0]} {result[1]}; the initial bundle supports Linux x64 only.")
    return result


def _validate_manifest(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != {"manifestVersion", "packageVersion", "providerId", "workerProtocolVersion", "artifacts"}:
        raise ValueError("Invalid worker manifest fields")
    if data["manifestVersion"] != 1 or data["packageVersion"] != VERSION or data["providerId"] != PROVIDER_ID or data["workerProtocolVersion"] != PROTOCOL_VERSION:
        raise ValueError("Worker manifest version/provider/protocol does not match this package")
    entries = data["artifacts"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Worker manifest has no artifacts")
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"platform", "architecture", "asset", "sha256"}:
            raise ValueError("Invalid artifact manifest entry")
        if not all(isinstance(entry[key], str) for key in ("platform", "architecture", "asset", "sha256")):
            raise ValueError("Artifact manifest values must be strings")
        if not entry["asset"] or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in entry["asset"]) or entry["asset"] in {".", ".."}:
            raise ValueError("Unsafe worker asset name")
        if len(entry["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in entry["sha256"]):
            raise ValueError("Invalid worker SHA256")
        key = entry["platform"], entry["architecture"]
        if key in seen:
            raise ValueError("Duplicate platform/architecture worker manifest entry")
        seen.add(key)
    return data


def load_manifest(path: Path) -> dict:
    try:
        manifest = _validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError as error:
        raise RuntimeError("Worker manifest is missing from this distribution. Reinstall the hermes-claude-bridge 0.5.1 wheel that includes its release manifest.") from error
    return manifest



def _select(manifest: dict) -> dict:
    target = host_target()
    for entry in manifest["artifacts"]:
        if (entry["platform"], entry["architecture"]) == target:
            return entry
    raise RuntimeError(f"Worker manifest has no artifact for {target[0]} {target[1]}; install a supported release.")


def _download_url(asset: str) -> str:
    return f"https://github.com/{RELEASE_REPO}/releases/download/v{VERSION}/{asset}"


def _safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        seen: set[str] = set()
        total_size = 0
        for member in tar:
            path = PurePosixPath(member.name)
            if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts) or "\\" in member.name:
                raise ValueError(f"unsafe archive path: {member.name}")
            if member.name in seen:
                raise ValueError(f"duplicate archive path: {member.name}")
            seen.add(member.name)
            if not (member.isdir() or member.isfile()):
                raise ValueError(f"unsupported archive entry type: {member.name}")
            total_size += member.size
            if total_size > MAX_ARCHIVE_BYTES:
                raise ValueError("extracted worker exceeds the size limit")
            target = destination.joinpath(*path.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"unsafe archive path: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.size < 0 or member.size > MAX_ARCHIVE_BYTES:
                raise ValueError(f"invalid archive file size: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                raise ValueError(f"unreadable archive entry: {member.name}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _validate_artifact(root: Path) -> dict:
    metadata_path = root / "artifact.json"
    plugin = root / "plugin"
    worker = plugin / "runtime" / "src" / "adapters" / "hermes-worker" / "index.js"
    plugin_yaml = plugin / "plugin.yaml"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Worker artifact is missing valid artifact.json metadata") from error
    expected = {"artifactFormat": 1, "providerId": PROVIDER_ID, "packageVersion": VERSION, "workerProtocolVersion": PROTOCOL_VERSION, "buildPlatform": "linux", "buildArchitecture": "x64", "nodeEngine": ">=22.19.0"}
    if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError("Worker artifact metadata version/provider/protocol/platform/architecture mismatch")
    if not worker.is_file() or not plugin_yaml.is_file():
        raise ValueError("Worker artifact is missing compiled worker or plugin metadata")
    return metadata


def _download(url: str, expected_sha256: str, cache: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "hermes-claude-bridge/0.5.1"})
    downloaded: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            final_url = response.geturl()
            redirected = urlparse(final_url)
            github_asset_hosts = {"release-assets.githubusercontent.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com"}
            if final_url != url and not (
                redirected.scheme == "https"
                and redirected.hostname in github_asset_hosts
                and redirected.port in {None, 443}
                and redirected.username is None
                and redirected.password is None
            ):
                raise ValueError("Worker download redirect is outside GitHub's asset hosts")
            with tempfile.NamedTemporaryFile(prefix="hermes-worker-", suffix=".tar.gz", delete=False, dir=cache) as output:
                downloaded = Path(output.name)
                digest = hashlib.sha256()
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ValueError("Worker archive exceeds the size limit")
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("Downloaded worker SHA256 does not match the embedded release manifest")
        return downloaded
    except BaseException:
        if downloaded is not None:
            downloaded.unlink(missing_ok=True)
        raise


def _secure_path(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"Refusing symbolic-link worker cache path: {path}")
    if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise RuntimeError(f"Unsafe worker cache ownership or permissions: {path}")


def _secure_ancestry(cache: Path) -> None:
    for ancestor in cache.parents:
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise RuntimeError(f"Refusing symbolic-link cache ancestor: {ancestor}")
        if os.name == "posix":
            trusted_owner = info.st_uid in {0, os.getuid()}
            protected_sticky = bool(info.st_mode & stat.S_ISVTX) and trusted_owner
            if not trusted_owner or (info.st_mode & 0o022 and not protected_sticky):
                raise RuntimeError(f"Unsafe worker cache ancestor ownership or permissions: {ancestor}")


def _cache_target(cache: Path, selected: dict) -> Path:
    cache = cache.expanduser().absolute()
    if cache.resolve() != cache:
        raise RuntimeError(f"Refusing symbolic-link worker cache ancestry: {cache}")
    _secure_ancestry(cache)
    target = cache / VERSION / selected["platform"] / selected["architecture"]
    for directory in (cache, cache / VERSION, target.parent, target):
        if directory.exists() or directory.is_symlink():
            _secure_path(directory)
    return target


def _validated_cached_worker(cache: Path, selected: dict) -> Path:
    target = _cache_target(cache, selected)
    if not target.is_dir():
        raise RuntimeError(f"Worker cache is not installed: {target}")
    for directory, folders, files in os.walk(target, followlinks=False):
        _secure_path(Path(directory))
        for name in folders + files:
            _secure_path(Path(directory) / name)
    metadata = _validate_artifact(target)
    try:
        owner = json.loads((target / ".hermes-claude-bridge-owner.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Refusing unowned worker cache: {target}") from error
    if not isinstance(owner, dict) or set(owner) != {"packageVersion", "sha256"} or owner.get("packageVersion") != VERSION or owner.get("sha256") != selected["sha256"]:
        raise RuntimeError(f"Refusing invalid ownership or different artifact in worker cache: {target}")
    if metadata["packageVersion"] != VERSION:
        raise RuntimeError(f"Worker cache version mismatch: {target}")
    return target / "plugin" / "runtime" / "src" / "adapters" / "hermes-worker" / "index.js"


def cached_worker_path(cache_root: Path | None = None) -> Path | None:
    selected = _select(load_manifest(Path(__file__).with_name("worker-manifest.json")))
    try:
        return _validated_cached_worker(cache_root or default_cache_root(), selected)
    except (OSError, RuntimeError, ValueError):
        return None


def _install_worker(*, manifest_path: Path | None = None, local_artifact: Path | None = None, cache_root: Path | None = None) -> Path:
    manifest_file = manifest_path or Path(__file__).with_name("worker-manifest.json")
    manifest = load_manifest(manifest_file)
    selected = _select(manifest)
    cache = (cache_root or default_cache_root()).expanduser().absolute()
    target = _cache_target(cache, selected)
    if target.exists():
        _validated_cached_worker(cache, selected)
        return target

    downloaded: Path | None = None
    if local_artifact is not None:
        source = local_artifact.expanduser().resolve()
        if not source.is_file():
            raise ValueError("Local worker artifact must be a regular archive file")
    else:
        url = _download_url(selected["asset"])
        if not url.startswith(f"https://github.com/{RELEASE_REPO}/releases/download/v{VERSION}/"):
            raise ValueError("Worker release URL is outside the pinned repository/version")
        cache.mkdir(parents=True, exist_ok=True)
        downloaded = _download(url, selected["sha256"], cache)
        source = downloaded

    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise ValueError("Worker archive exceeds the size limit")
            digest.update(chunk)
    if digest.hexdigest() != selected["sha256"]:
        raise ValueError("Local worker artifact SHA256 does not match the embedded release manifest")

    cache.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".hermes-worker-install-", dir=cache))
    try:
        _safe_extract(source, staging)
        for directory, _, _ in os.walk(staging):
            Path(directory).chmod(0o755)
        metadata = _validate_artifact(staging)
        if (metadata["buildPlatform"], metadata["buildArchitecture"]) != (selected["platform"], selected["architecture"]):
            raise ValueError("Worker artifact platform/architecture disagrees with manifest selection")
        (staging / ".hermes-claude-bridge-owner.json").write_text(json.dumps({"packageVersion": VERSION, "sha256": selected["sha256"]}, sort_keys=True) + "\n", encoding="utf-8")
        (staging / ".hermes-claude-bridge-owner.json").chmod(0o644)
        for directory in (cache / VERSION, target.parent):
            if not directory.exists():
                directory.mkdir(mode=0o755)
                directory.chmod(0o755)
            _secure_path(directory)
        try:
            staging.rename(target)
        except FileExistsError:
            raise RuntimeError(f"Worker cache appeared during setup; refusing to overwrite: {target}")
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if downloaded is not None:
            downloaded.unlink(missing_ok=True)
    _validated_cached_worker(cache, selected)
    return target

def _prepare_cache_directory(cache: Path) -> None:
    """Walk/create through pinned directory handles, never following symlinks."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(cache.anchor, flags)
    try:
        parts = cache.parts[1:]
        for index, name in enumerate(parts):
            info = os.fstat(descriptor)
            trusted = info.st_uid in {0, os.getuid()}
            if not trusted or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise RuntimeError("Unsafe worker cache ancestor ownership or permissions")
            try:
                child = os.open(name, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(name, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(name, flags, dir_fd=descriptor)
            try:
                info = os.fstat(child)
                trusted = info.st_uid in {0, os.getuid()}
                leaf = index == len(parts) - 1
                if leaf:
                    if info.st_uid != os.getuid() or info.st_mode & 0o022:
                        raise RuntimeError("Unsafe worker cache ownership or permissions")
                elif not trusted or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                    raise RuntimeError("Unsafe worker cache ancestor ownership or permissions")
            except BaseException:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
    finally:
        os.close(descriptor)


def install_worker(*, manifest_path: Path | None = None, local_artifact: Path | None = None, cache_root: Path | None = None) -> Path:
    host_target()
    cache = (cache_root or default_cache_root()).expanduser().absolute()
    _prepare_cache_directory(cache)
    _secure_path(cache)
    _secure_ancestry(cache)
    if cache.resolve() != cache:
        raise RuntimeError(f"Refusing symbolic-link worker cache ancestry: {cache}")
    lock = cache / ".hermes-claude-bridge-setup.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError(f"Another worker setup is running or left a lock at {lock}; do not remove it until that process has stopped.") from error
    try:
        return _install_worker(manifest_path=manifest_path, local_artifact=local_artifact, cache_root=cache)
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)
