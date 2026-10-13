from __future__ import annotations

import os
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent

REPOSITORY = ROOT if (ROOT / "hermes").is_dir() else ROOT.parent
def worker_manifest() -> Path:
    configured = os.environ.get("HERMES_CLAUDE_BRIDGE_WORKER_MANIFEST")
    candidate = Path(configured).expanduser() if configured else ROOT / "worker-manifest.json"
    if not candidate.is_file():
        raise RuntimeError("Missing release worker manifest. Set HERMES_CLAUDE_BRIDGE_WORKER_MANIFEST to the version-paired worker-manifest.json input.")
    return candidate.resolve()


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        package = Path(self.build_lib) / "hermes_claude_bridge"
        package.mkdir(parents=True, exist_ok=True)
        for source, destination in ((REPOSITORY / "hermes" / "__init__.py", package / "provider.py"), (REPOSITORY / "hermes" / "client.py", package / "client.py"), (REPOSITORY / "hermes" / "worker_location.py", package / "worker_location.py")):
            self.copy_file(str(source), str(destination))
        self.copy_file(str(worker_manifest()), str(package / "worker-manifest.json"))
        self.copy_file(str(REPOSITORY / "hermes" / "plugin.yaml"), str(package / "plugin.yaml"))


class ReleaseSdist(sdist):
    def run(self) -> None:
        manifest = worker_manifest()
        staged_manifest = ROOT / "worker-manifest.json"
        staged_sources = ROOT / "hermes"
        remove_manifest = not staged_manifest.exists()
        remove_sources = not staged_sources.exists()
        if remove_manifest:
            shutil.copyfile(manifest, staged_manifest)
        if remove_sources:
            shutil.copytree(REPOSITORY / "hermes", staged_sources, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "runtime"))
        try:
            super().run()
        finally:
            if remove_manifest:
                staged_manifest.unlink(missing_ok=True)
            if remove_sources:
                shutil.rmtree(staged_sources)

setup(
    name="hermes-claude-bridge",
    version="0.5.0",
    description="Hermes provider plugin for the pi-claude-cli Claude worker",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=">=3.10",
    packages=["hermes_claude_bridge"],
    package_data={"hermes_claude_bridge": ["worker-manifest.json", "plugin.yaml"]},
    include_package_data=True,
    cmdclass={"build_py": BuildPy, "sdist": ReleaseSdist},
    zip_safe=False,
)
