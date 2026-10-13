from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_claude_bridge import __version__
from hermes_claude_bridge.setup_worker import install_worker
_locator_path = Path(__file__).resolve().parents[2] / "hermes" / "worker_location.py"
_locator_spec = importlib.util.spec_from_file_location("worker_location_under_test", _locator_path)
if _locator_spec is None or _locator_spec.loader is None:
    raise RuntimeError("Hermes worker locator cannot be loaded")
_locator = importlib.util.module_from_spec(_locator_spec)
_locator_spec.loader.exec_module(_locator)
default_worker_path = _locator.default_worker_path
require_worker = _locator.require_worker


class DistributionTests(unittest.TestCase):
    def test_import_is_lazy(self) -> None:
        modules = __import__("sys").modules
        self.assertEqual(__version__, "0.5.0")
        self.assertNotIn("providers", modules)
        self.assertNotIn("hermes_claude_bridge.provider", modules)

    def test_worker_locator_prefers_bundle_then_explicit_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            bundled = plugin / "runtime/src/adapters/hermes-worker/index.js"
            bundled.parent.mkdir(parents=True)
            bundled.touch()
            with patch.dict(os.environ, {"HERMES_CLAUDE_BRIDGE_CACHE": str(root / "cache")}):
                self.assertEqual(default_worker_path(plugin), bundled)
                bundled.unlink()
                self.assertEqual(default_worker_path(plugin), bundled)
                with self.assertRaisesRegex(RuntimeError, "setup.*first"):
                    require_worker(bundled)
                shutil.rmtree(plugin / "runtime")
                cached = root / "cache/0.5.0/linux/x64/plugin/runtime/src/adapters/hermes-worker/index.js"
                self.assertEqual(default_worker_path(plugin), cached)
                with self.assertRaisesRegex(RuntimeError, "setup.*first"):
                    require_worker(cached)

    def test_missing_worker_fails_clearly_on_unsupported_platform(self) -> None:
        with patch.object(_locator.platform, "system", return_value="Darwin"), patch.object(_locator.platform, "machine", return_value="arm64"):
            with self.assertRaisesRegex(RuntimeError, "supports Linux x64 only"):
                require_worker(Path("missing-worker"))

    def test_local_fixture_archive_installs_and_repeats_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.tar.gz"
            metadata = {"artifactFormat": 1, "providerId": "pi-claude-cli", "packageVersion": "0.5.0", "workerProtocolVersion": 1, "nodeEngine": ">=22.19.0", "buildPlatform": "linux", "buildArchitecture": "x64"}
            with tarfile.open(archive, "w:gz") as tar:
                for name, data in (("artifact.json", json.dumps(metadata).encode()), ("plugin/plugin.yaml", b"name: pi-claude-cli\n"), ("plugin/runtime/src/adapters/hermes-worker/index.js", b"process.stdout.write('fixture')\n")):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            manifest = {"manifestVersion": 1, "packageVersion": "0.5.0", "providerId": "pi-claude-cli", "workerProtocolVersion": 1, "artifacts": [{"platform": "linux", "architecture": "x64", "asset": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}]}
            manifest_path = root / "worker-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            target = root / "cache"
            installed = install_worker(manifest_path=manifest_path, local_artifact=archive, cache_root=target)
            self.assertTrue((installed / "plugin/runtime/src/adapters/hermes-worker/index.js").is_file())
            self.assertEqual(json.loads((installed / "artifact.json").read_text())["packageVersion"], "0.5.0")
            self.assertEqual(install_worker(manifest_path=manifest_path, local_artifact=archive, cache_root=target), installed)
            foreign_target = root / "foreign/0.5.0/linux/x64"
            foreign_target.mkdir(parents=True)
            marker = foreign_target / "do-not-replace"
            marker.write_text("foreign owner", encoding="utf-8")
            with self.assertRaises(ValueError):
                install_worker(manifest_path=manifest_path, local_artifact=archive, cache_root=root / "foreign")
            self.assertEqual(marker.read_text(encoding="utf-8"), "foreign owner")

    def test_hash_mismatch_and_archive_traversal_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("../escape")
                payload = b"bad"
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            manifest = {"manifestVersion": 1, "packageVersion": "0.5.0", "providerId": "pi-claude-cli", "workerProtocolVersion": 1, "artifacts": [{"platform": "linux", "architecture": "x64", "asset": archive.name, "sha256": "0" * 64}]}
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                install_worker(manifest_path=path, local_artifact=archive, cache_root=root / "cache")
            manifest["artifacts"][0]["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                install_worker(manifest_path=path, local_artifact=archive, cache_root=root / "cache")
            self.assertFalse((root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
