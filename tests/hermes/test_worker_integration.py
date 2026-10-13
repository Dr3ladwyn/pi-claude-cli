from __future__ import annotations
import asyncio
import threading
import time

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if not os.environ.get("PCC_HERMES_ARTIFACT"):
    raise RuntimeError("Build a Hermes artifact and set PCC_HERMES_ARTIFACT before running the integration suite")
ARTIFACT = Path(os.environ["PCC_HERMES_ARTIFACT"]).resolve()
TEMP_ROOT = Path(os.environ.get("TMPDIR") or Path.home() / "dev" / "agentic-scratchpads" / "pi-claude-cli" / "hermes-tests")
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
SCRATCH = Path(tempfile.mkdtemp(prefix="hermes-integration-", dir=TEMP_ROOT))


@unittest.skipUnless(os.name == "posix", "POSIX native fixture and process-lifecycle qualification")
class BuiltWorkerIntegrationTests(unittest.TestCase):
    def test_installed_plugin_loads_compiled_worker_and_drives_fixture_tool_round(self):
        profile_home = SCRATCH / "profile"
        receipt = SCRATCH / "fixture-receipt.json"
        isolated_home = SCRATCH / "isolated-home"
        for directory in (profile_home, isolated_home, receipt.parent):
            directory.mkdir(parents=True, exist_ok=True)
        installer = ARTIFACT / "install.py"
        plugin_target = profile_home / "plugins" / "model-providers" / "pi-claude-cli"
        if not plugin_target.exists():
            status = os.spawnv(os.P_WAIT, sys.executable, [sys.executable, str(installer), "--artifact", str(ARTIFACT), "--profile-home", str(profile_home)])
            self.assertEqual(status, 0)
        conflict_profile = SCRATCH / "conflict-profile"
        conflict_target = conflict_profile / "plugins" / "model-providers" / "pi-claude-cli"
        conflict_target.mkdir(parents=True, exist_ok=True)
        sentinel = conflict_target / "owned.txt"
        sentinel.write_text("unrelated plugin", encoding="utf-8")
        refused = subprocess.run(
            [sys.executable, str(installer), "--artifact", str(ARTIFACT), "--profile-home", str(conflict_profile)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unrelated plugin")
        spec = importlib.util.spec_from_file_location("installed_hermes_provider", plugin_target / "__init__.py", submodule_search_locations=[str(plugin_target)])
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.assertTrue(module.HermesClaudeClient.HERMES_SKIP_TRANSPORT_WRAP)
        self.assertTrue(module.HermesClaudeClient.HERMES_SKIP_ASYNC_WRAP)
        node = shutil.which("node")
        self.assertIsNotNone(node)
        probe = subprocess.Popen(
            [node, str(module.DEFAULT_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            probe.stdin.write("{\n")
            probe.stdin.flush()
            self.assertEqual(json.loads(probe.stdout.readline())["type"], "error")
            probe.stdin.write(json.dumps({"version": 2, "id": "wrong-version", "type": "hello"}) + "\n")
            probe.stdin.flush()
            self.assertEqual(json.loads(probe.stdout.readline())["type"], "error")
            probe.stdin.write(json.dumps({"version": 1, "id": "hello", "type": "hello"}) + "\n")
            probe.stdin.flush()
            self.assertEqual(json.loads(probe.stdout.readline())["type"], "ready")
            probe.stdin.write(json.dumps({"version": 1, "id": "shutdown", "type": "shutdown"}) + "\n")
            probe.stdin.flush()
            self.assertEqual(json.loads(probe.stdout.readline())["type"], "result")
            self.assertEqual(probe.wait(timeout=5), 0)
        finally:
            if probe.poll() is None:
                probe.terminate()
                probe.wait(timeout=5)
            for stream in (probe.stdin, probe.stdout, probe.stderr):
                stream.close()
        environment = {
            "PATH": os.pathsep.join((str(Path(node).parent), "/usr/bin", "/bin")),
            "HOME": str(isolated_home),
            "HERMES_HOME": str(profile_home),
            "CLAUDE_CONFIG_DIR": str(isolated_home / "claude-config"),
            "XDG_CONFIG_HOME": str(isolated_home / "xdg"),
            "TMPDIR": str(TEMP_ROOT),
            "PI_CLAUDE_DRIVER": "cli",
            "PI_CLAUDE_AUTH": "claude-login",
            "PI_CLAUDE_EXECUTABLE": str(ROOT / "tests" / "support" / "offline-protocol-cli.mjs"),
            "PCC_SCENARIO_SESSION": "hermes-fixture-session",
            "PCC_SCENARIO_RECEIPT": str(receipt),
        }
        for directory in (Path(environment["CLAUDE_CONFIG_DIR"]), Path(environment["XDG_CONFIG_HOME"]), Path(environment["TMPDIR"])):
            directory.mkdir(parents=True, exist_ok=True)
        tools = [{"type": "function", "function": {"name": "echo", "description": "fixture tool", "parameters": {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}}}]
        cli = module.HermesClaudeClient(command=str(node), args=(str(module.DEFAULT_WORKER),), client_kwargs={})
        try:
            with patch.dict(os.environ, environment, clear=True):
                command = {"turn": "hermes-tool-round", "mode": "tools", "calls": [{"id": "toolu_fixture_1", "name": "echo", "arguments": {"word": "fixture"}}]}
                prompt = json.dumps(command, separators=(",", ":"))
                first = cli.chat.completions.create(model="claude-sonnet-4-5", messages=[{"role": "user", "content": prompt}], tools=tools)
                tool_call = first.choices[0].message.tool_calls[0]
                self.assertEqual(tool_call.id, "toolu_fixture_1")
                self.assertEqual(first.choices[0].finish_reason, "tool_calls")
                history = [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": None, "tool_calls": [{"id": tool_call.id, "type": "function", "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments}}]},
                    {"role": "tool", "tool_call_id": tool_call.id, "name": "echo", "content": "fixture-result"},
                ]
                worker_pid = cli._worker._process.pid
                second = cli.chat.completions.create(model="claude-sonnet-4-5", messages=history, tools=tools)
                self.assertEqual(cli._worker._process.pid, worker_pid)
                self.assertIn("fixture-result", second.choices[0].message.content)
                saved = json.loads(receipt.read_text(encoding="utf-8"))
                self.assertGreater(saved["pid"], 0)
                self.assertEqual(len(saved["prompts"]), 1)
                self.assertEqual(len(saved["results"]), 1)
                self.assertEqual(len(saved["results"][0]), 1)
                async def async_request():
                    return await cli.chat.completions.create(
                        model="claude-sonnet-4-5",
                        messages=[{"role": "user", "content": json.dumps({"turn": "hermes-async", "mode": "text", "text": "async fixture"})}],
                    )
                async_response = asyncio.run(async_request())
                self.assertEqual(async_response.choices[0].message.content, "async fixture")
                async def async_stream():
                    stream = await cli.chat.completions.create(
                        model="claude-sonnet-4-5",
                        messages=[{"role": "user", "content": json.dumps({"turn": "hermes-async-stream", "mode": "text", "text": "stream fixture"})}],
                        stream=True,
                    )
                    return [chunk async for chunk in stream]
                chunks = asyncio.run(async_stream())
                self.assertTrue(any(chunk.choices[0].delta.get("content") == "stream fixture" for chunk in chunks))
                stream_errors = []
                completed = threading.Event()
                def held_stream():
                    try:
                        list(cli.chat.completions.create(
                            model="claude-sonnet-4-5",
                            messages=[{"role": "user", "content": json.dumps({"turn": "hermes-cancel", "mode": "hold"})}],
                            stream=True,
                        ))
                    except BaseException as error:
                        stream_errors.append(error)
                    finally:
                        completed.set()
                stream_thread = threading.Thread(target=held_stream)
                stream_thread.start()
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if receipt.exists() and "hermes-cancel" in receipt.read_text(encoding="utf-8"):
                        break
                    if completed.is_set():
                        break
                    time.sleep(0.025)
                self.assertTrue(receipt.exists() and "hermes-cancel" in receipt.read_text(encoding="utf-8"))
                cli.cancel()
                stream_thread.join(timeout=10)
                self.assertFalse(stream_thread.is_alive())
                self.assertTrue(stream_errors)
                self.assertRegex(str(stream_errors[0]).lower(), "abort|cancel")
                worker_process = cli._worker._process
                cli.close()
                self.assertIsNotNone(worker_process.poll())
                sdk_client = module.HermesClaudeClient(command=str(node), args=(str(module.DEFAULT_WORKER),), client_kwargs={})
                sdk_environment = {
                    **environment,
                    "PI_CLAUDE_DRIVER": "sdk",
                    "PI_CLAUDE_EXECUTABLE": str(ROOT / "tests" / "hermes" / "offline-sdk-cli.mjs"),
                }
                try:
                    with patch.dict(os.environ, sdk_environment, clear=True):
                        sdk_response = sdk_client.chat.completions.create(
                            model="claude-sonnet-4-5",
                            messages=[{"role": "user", "content": "hermes-sdk-text:SDK fixture response"}],
                        )
                    self.assertEqual(sdk_response.choices[0].message.content, "SDK fixture response")
                finally:
                    sdk_process = sdk_client._worker._process
                    sdk_client.close()
                    if sdk_process is not None:
                        self.assertIsNotNone(sdk_process.poll())
        finally:
            cli.close()

    def test_worker_sigterm_settles_request_and_reaps_detached_native_child(self):
        # Fault injection against the actual compiled worker, real core and
        # authored native CLI. No auth store or network is used.
        plugin = ARTIFACT / "plugin"
        spec = importlib.util.spec_from_file_location("signal_test_provider", plugin / "__init__.py", submodule_search_locations=[str(plugin)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js is required")
        receipt = SCRATCH / "signal-native.json"
        isolated = SCRATCH / "signal-home"
        isolated.mkdir()
        environment = {"PATH": os.pathsep.join((str(Path(node).parent), "/usr/bin", "/bin")),
                       "HOME": str(isolated), "HERMES_HOME": str(isolated / "hermes"),
                       "CLAUDE_CONFIG_DIR": str(isolated / "claude"), "XDG_CONFIG_HOME": str(isolated / "config"),
                       "TMPDIR": str(TEMP_ROOT), "PI_CLAUDE_DRIVER": "cli", "PI_CLAUDE_AUTH": "claude-login",
                       "PI_CLAUDE_EXECUTABLE": str(ROOT / "tests/support/offline-protocol-cli.mjs"),
                       "PCC_SCENARIO_SESSION": "signal-fixture", "PCC_SCENARIO_RECEIPT": str(receipt)}
        client = module.HermesClaudeClient(command=node, args=(str(module.DEFAULT_WORKER),), client_kwargs={})
        errors = []
        native_pid = None
        def call():
            try:
                client.chat.completions.create(model="offline-model", messages=[{"role": "user", "content": json.dumps({"turn": "signal-hold", "mode": "hold"})}])
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=call, daemon=True)
        try:
            with patch.dict(os.environ, environment, clear=True):
                thread.start()
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if receipt.exists() and json.loads(receipt.read_text()).get("prompts"):
                        break
                    time.sleep(0.025)
                else:
                    self.fail("Native fixture did not activate")
                native_pid = json.loads(receipt.read_text())["pid"]
                worker = client._worker._process
                worker.terminate()
                thread.join(timeout=8)
                self.assertFalse(thread.is_alive(), "Worker termination left the request blocked")
                client.close()
                self.assertTrue(errors, "Terminated request must not report successful inference")
                self.assertIsNotNone(worker.poll())
                self.assertTrue(all(stream.closed for stream in (worker.stdin, worker.stdout, worker.stderr)), "close must release owned pipes after worker failure")
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try:
                        os.kill(native_pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.025)
                else:
                    self.fail("Detached native child survived worker termination")
        finally:
            client.close()
            if native_pid is not None:
                try:
                    os.killpg(native_pid, 15)
                except ProcessLookupError:
                    pass

    def test_cancelling_one_client_does_not_cancel_an_interleaved_peer(self):
        spec = importlib.util.spec_from_file_location("peer_test_provider", ARTIFACT / "plugin/__init__.py", submodule_search_locations=[str(ARTIFACT / "plugin")])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js is required")
        isolated = SCRATCH / "peer-home"
        isolated.mkdir()
        receipt = SCRATCH / "peer-native.json"
        environment = {"PATH": os.pathsep.join((str(Path(node).parent), "/usr/bin", "/bin")), "HOME": str(isolated),
                       "HERMES_HOME": str(isolated / "hermes"), "CLAUDE_CONFIG_DIR": str(isolated / "claude"),
                       "XDG_CONFIG_HOME": str(isolated / "config"), "TMPDIR": str(TEMP_ROOT),
                       "PI_CLAUDE_DRIVER": "cli", "PI_CLAUDE_AUTH": "claude-login",
                       "PI_CLAUDE_EXECUTABLE": str(ROOT / "tests/support/offline-protocol-cli.mjs"),
                       "PCC_SCENARIO_SESSION": "peer-fixture", "PCC_SCENARIO_RECEIPT": str(receipt)}
        clients = [module.HermesClaudeClient(command=node, args=(str(module.DEFAULT_WORKER),), client_kwargs={}) for _ in range(2)]
        errors = [[], []]
        def call(index):
            try:
                clients[index].chat.completions.create(model="offline-model", messages=[{"role": "user", "content": json.dumps({"turn": f"peer-{index}", "mode": "hold"})}])
            except BaseException as error:
                errors[index].append(error)
        threads = [threading.Thread(target=call, args=(i,), daemon=True) for i in range(2)]
        try:
            with patch.dict(os.environ, environment, clear=True):
                for index, thread in enumerate(threads):
                    thread.start()
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        if receipt.exists() and f"peer-{index}" in receipt.read_text():
                            break
                        time.sleep(0.025)
                    else:
                        self.fail("Peer fixture did not activate")
                self.assertNotEqual(clients[0]._worker._process.pid, clients[1]._worker._process.pid)
                clients[0].cancel()
                threads[0].join(timeout=8)
                self.assertFalse(threads[0].is_alive())
                self.assertTrue(errors[0])
                self.assertTrue(threads[1].is_alive(), "Cancellation crossed into the other owner")
                self.assertIsNone(clients[1]._worker._process.poll())
                clients[1].cancel()
                threads[1].join(timeout=8)
                self.assertFalse(threads[1].is_alive())
                self.assertTrue(errors[1])
        finally:
            for client in clients:
                client.close()


if __name__ == "__main__":
    unittest.main()
