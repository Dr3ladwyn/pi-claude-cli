"""Resolve the local runtime bundle or explicit pip-installed worker cache."""
from __future__ import annotations

import os
import platform
from pathlib import Path


def default_worker_path(plugin_root: Path) -> Path:
    local = plugin_root / "runtime" / "src" / "adapters" / "hermes-worker" / "index.js"
    if (plugin_root / "runtime").is_dir():
        return local
    configured = os.environ.get("HERMES_CLAUDE_BRIDGE_CACHE")
    cache = Path(configured).expanduser() if configured else Path.home() / ".cache" / "hermes-claude-bridge"
    system = platform.system().lower()
    architecture = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    return cache / "0.5.1" / system / architecture / "plugin" / "runtime" / "src" / "adapters" / "hermes-worker" / "index.js"


def require_worker(path: Path) -> Path:
    bundled = Path(__file__).resolve().parent / "runtime" / "src" / "adapters" / "hermes-worker" / "index.js"
    if path == bundled and path.is_file():
        return path
    if __package__:
        import importlib
        try:
            setup = importlib.import_module(f"{__package__}.setup_worker")
        except ModuleNotFoundError as error:
            if error.name != f"{__package__}.setup_worker":
                raise
        else:
            validated = setup.cached_worker_path()
            if validated is not None and path.absolute() == validated.absolute():
                return validated
    system = platform.system().lower()
    machine = {"x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower(), platform.machine().lower())
    if (system, machine) != ("linux", "x64"):
        raise RuntimeError(f"No Hermes Claude worker is available for {system} {machine}; this release supports Linux x64 only.")
    raise RuntimeError(f"Hermes Claude worker is not installed at {path}. Run `hermes-claude-bridge setup` first.")
