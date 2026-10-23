"""Regression tests for real GitHub asset routing and native executable extraction."""
from __future__ import annotations
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from hermes_claude_bridge.setup_worker import _download, _safe_extract


class FixtureResponse(io.BytesIO):
    def __init__(self, payload: bytes, url: str):
        super().__init__(payload)
        self.url = url

    def geturl(self) -> str:
        return self.url


class ReleaseInstallerRegressionTests(unittest.TestCase):
    def test_github_asset_redirect_preserves_pinned_digest(self):
        payload = b"labelled fixture archive bytes"
        response = FixtureResponse(payload, "https://release-assets.githubusercontent.com/github-production-release-asset/fixture?signature=fixture")
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen", return_value=response):
            downloaded = _download("https://github.com/ramarivera/pi-claude-cli/releases/download/v0.5.1/fixture.tar.gz", hashlib.sha256(payload).hexdigest(), Path(directory))
            self.assertEqual(downloaded.read_bytes(), payload)

    def test_foreign_redirect_remains_rejected(self):
        response = FixtureResponse(b"fixture", "https://untrusted.invalid/fixture")
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "redirect"):
                _download("https://github.com/ramarivera/pi-claude-cli/releases/download/v0.5.1/fixture.tar.gz", "0" * 64, Path(directory))

    def test_executable_modes_survive_without_privileged_permission_bits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                item = tarfile.TarInfo("native-runtime")
                item.mode = 0o6755
                item.size = 7
                tar.addfile(item, io.BytesIO(b"fixture"))
            output = root / "output"
            output.mkdir()
            _safe_extract(archive, output)
            self.assertEqual((output / "native-runtime").stat().st_mode & 0o7777, 0o755)

    def test_links_are_not_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                item = tarfile.TarInfo("link")
                item.type = tarfile.SYMTYPE
                item.linkname = "/etc/passwd"
                tar.addfile(item)
            output = root / "output"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "unsupported archive entry"):
                _safe_extract(archive, output)
            self.assertFalse((output / "link").exists())
