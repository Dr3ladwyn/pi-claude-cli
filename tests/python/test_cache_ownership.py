"""Labelled cache fixtures exercising inference/setup ownership parity."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from hermes_claude_bridge import setup_worker

spec = importlib.util.spec_from_file_location('hermes_claude_bridge.worker_location', Path(__file__).resolve().parents[2] / 'hermes/worker_location.py')
assert spec is not None and spec.loader is not None
locator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = locator
spec.loader.exec_module(locator)


class CacheOwnershipTests(unittest.TestCase):
    def cache(self, root):
        target = root / '0.5.1/linux/x64'
        worker = target / 'plugin/runtime/src/adapters/hermes-worker/index.js'
        worker.parent.mkdir(parents=True)
        worker.write_text('// labelled fixture, never executed\n')
        metadata = {'artifactFormat': 1, 'providerId': 'pi-claude-cli', 'packageVersion': '0.5.1', 'workerProtocolVersion': 1, 'nodeEngine': '>=22.19.0', 'buildPlatform': 'linux', 'buildArchitecture': 'x64'}
        (target / 'artifact.json').write_text(json.dumps(metadata))
        (target / 'plugin/plugin.yaml').write_text('name: pi-claude-cli\n')
        (target / '.hermes-claude-bridge-owner.json').write_text(json.dumps({'packageVersion': '0.5.1', 'sha256': 'a' * 64}))
        manifest = {'manifestVersion': 1, 'packageVersion': '0.5.1', 'providerId': 'pi-claude-cli', 'workerProtocolVersion': 1, 'artifacts': [{'platform': 'linux', 'architecture': 'x64', 'asset': 'labelled-fixture.tar.gz', 'sha256': 'a' * 64}]}
        return target, worker, manifest

    def test_non_object_owner_is_controlled_in_status_and_setup(self):
        for owner in (None, [], 'not-an-owner'):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target, _, manifest = self.cache(root)
                (target / '.hermes-claude-bridge-owner.json').write_text(json.dumps(owner))
                with patch.object(setup_worker, 'load_manifest', return_value=manifest):
                    self.assertIsNone(setup_worker.cached_worker_path(root))
                    with self.assertRaisesRegex(RuntimeError, 'owner|cache'):
                        setup_worker.install_worker(cache_root=root)

    def test_inference_rejects_a_worker_without_setup_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, worker, manifest = self.cache(root)
            (target / '.hermes-claude-bridge-owner.json').unlink()
            with patch.dict(os.environ, {'HERMES_CLAUDE_BRIDGE_CACHE': str(root)}), patch.object(setup_worker, 'load_manifest', return_value=manifest):
                with self.assertRaisesRegex(RuntimeError, 'setup|cache|owner'):
                    locator.require_worker(worker)

    def test_symlinked_worker_is_rejected_even_with_a_matching_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, worker, manifest = self.cache(root)
            outside = root / 'outside.js'
            outside.write_text('// labelled untrusted fixture\n')
            worker.unlink()
            worker.symlink_to(outside)
            with patch.dict(os.environ, {'HERMES_CLAUDE_BRIDGE_CACHE': str(root)}), patch.object(setup_worker, 'load_manifest', return_value=manifest):
                self.assertIsNone(setup_worker.cached_worker_path(root))
                with self.assertRaisesRegex(RuntimeError, 'setup|cache|symbolic'):
                    locator.require_worker(worker)

    def test_group_writable_cache_cannot_be_used_for_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, worker, manifest = self.cache(root)
            root.chmod(0o770)
            with patch.dict(os.environ, {'HERMES_CLAUDE_BRIDGE_CACHE': str(root)}), patch.object(setup_worker, 'load_manifest', return_value=manifest):
                self.assertIsNone(setup_worker.cached_worker_path(root))
                with self.assertRaisesRegex(RuntimeError, 'setup|cache|permission'):
                    locator.require_worker(worker)

    def test_writable_non_sticky_ancestor_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / 'cache'
            root.mkdir(mode=0o700)
            _, worker, manifest = self.cache(root)
            parent.chmod(0o777)
            with patch.dict(os.environ, {'HERMES_CLAUDE_BRIDGE_CACHE': str(root)}), patch.object(setup_worker, 'load_manifest', return_value=manifest):
                self.assertIsNone(setup_worker.cached_worker_path(root))
                with self.assertRaisesRegex(RuntimeError, 'setup|cache|ancestor'):
                    locator.require_worker(worker)

    def test_setup_under_group_writable_umask_is_ready_and_idempotent(self):
        import hashlib
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_root = root / 'fixture-source'
            _, _, manifest = self.cache(fixture_root)
            target = fixture_root / '0.5.1/linux/x64'
            archive = root / 'labelled-fixture.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for path in sorted(target.rglob('*')):
                    if path.is_file() and path.name != '.hermes-claude-bridge-owner.json':
                        tar.add(path, arcname=path.relative_to(target).as_posix())
            manifest['artifacts'][0]['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
            cache = root / 'new-parent' / 'installed-cache'
            with patch.dict(os.environ, {'HERMES_CLAUDE_BRIDGE_CACHE': str(cache)}), patch.object(setup_worker, 'load_manifest', return_value=manifest):
                old_umask = os.umask(0o002)
                try:
                    installed = setup_worker.install_worker(local_artifact=archive, cache_root=cache)
                    worker = setup_worker.cached_worker_path(cache)
                    self.assertIsNotNone(worker)
                    self.assertEqual(locator.require_worker(worker), worker)
                    self.assertEqual(setup_worker.install_worker(local_artifact=archive, cache_root=cache), installed)
                finally:
                    os.umask(old_umask)

    def test_missing_cache_parents_are_private_at_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'fresh-parent' / 'fresh-cache'
            actual_mkdir = os.mkdir
            observed = []

            def mkdir(path, mode=0o777, *, dir_fd=None):
                if str(path) in {'fresh-parent', 'fresh-cache'}:
                    observed.append(str(path))
                    self.assertEqual(mode, 0o700)
                    self.assertIsNotNone(dir_fd)
                return actual_mkdir(path, mode=mode, dir_fd=dir_fd)

            with patch.object(os, 'mkdir', new=mkdir), patch.object(setup_worker, '_install_worker', return_value=cache):
                setup_worker.install_worker(cache_root=cache)
            self.assertEqual(observed, ['fresh-parent', 'fresh-cache'])

    def test_ancestor_swap_before_open_cannot_redirect_directory_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / 'outside'
            outside.mkdir()
            parent = root / 'fresh-parent'
            cache = parent / 'fresh-cache'
            actual_open = os.open
            injected = []

            def opened(path, flags, mode=0o777, *, dir_fd=None):
                if str(path) == 'fresh-parent' and dir_fd is not None and not injected:
                    parent.symlink_to(outside, target_is_directory=True)
                    injected.append(True)
                return actual_open(path, flags, mode, dir_fd=dir_fd)

            with patch.object(os, 'open', new=opened), patch.object(setup_worker, '_install_worker', return_value=cache):
                with self.assertRaises((OSError, RuntimeError)):
                    setup_worker.install_worker(cache_root=cache)
            self.assertEqual(injected, [True])
            self.assertFalse((outside / 'fresh-cache').exists())

    def test_private_matching_cache_is_accepted_by_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, worker, manifest = self.cache(root)
            with patch.dict(os.environ, {'HERMES_CLAUDE_BRIDGE_CACHE': str(root)}), patch.object(setup_worker, 'load_manifest', return_value=manifest):
                self.assertEqual(setup_worker.cached_worker_path(root), worker)
                self.assertEqual(locator.require_worker(worker), worker)
