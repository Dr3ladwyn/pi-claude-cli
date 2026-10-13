"""Installed-artifact tests through the actual Hermes conversation loop."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import providers

ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = Path(providers.__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "POSIX native fixture and process-lifecycle qualification")
class RealHermesLoopTests(unittest.TestCase):
    def run_probe(self, case: str) -> dict:
        artifact = Path(os.environ["PCC_HERMES_ARTIFACT"]).resolve()
        temp_root = Path(os.environ["TMPDIR"])
        with tempfile.TemporaryDirectory(prefix="hermes-loop-", dir=temp_root) as temporary:
            sandbox = Path(temporary)
            home, profile = sandbox / "home", sandbox / "hermes"
            node = shutil.which("node")
            if node is None:
                raise RuntimeError("Node.js is required for the built Hermes artifact")
            environment = {
                "PATH": os.pathsep.join((str(Path(node).parent), "/usr/bin", "/bin")),
                "PYTHONPATH": str(CORE_ROOT), "PYTHONDONTWRITEBYTECODE": "1",
                "HOME": str(home), "HERMES_HOME": str(profile),
                "HERMES_TEST_ISOLATION": str(profile), "HERMES_DISABLE_LAZY_INSTALLS": "1",
                "HERMES_MANAGED_DIR": str(sandbox / "managed"),
                "HERMES_GATEWAY_LOCK_DIR": str(sandbox / "locks"),
                "CLAUDE_CONFIG_DIR": str(sandbox / "claude"), "TMPDIR": str(temp_root),
                "PI_CLAUDE_DRIVER": "cli", "PI_CLAUDE_AUTH": "claude-login",
                "PI_CLAUDE_EXECUTABLE": str(ROOT / "tests" / "support" / "offline-protocol-cli.mjs"),
                "PCC_SCENARIO_SESSION": "hermes-loop-fixture", "PCC_SCENARIO_RECEIPT": str(sandbox / "native.json"),
            }
            for key in ("CONFIG", "DATA", "STATE", "CACHE"):
                environment["XDG_" + key + "_HOME"] = str(sandbox / key.lower())
            for key, value in environment.items():
                if key.endswith("_HOME") or key in ("HOME", "CLAUDE_CONFIG_DIR", "HERMES_MANAGED_DIR", "HERMES_GATEWAY_LOCK_DIR"):
                    Path(value).mkdir(parents=True, exist_ok=True)
            work = home / "work"
            work.mkdir()
            (profile / "config.yaml").write_text(json.dumps({
                "model": {"provider": "pi-claude-cli", "default": "offline-model", "context_length": 64000},
                "agent": {"api_max_retries": 1, "auto_recovery_cycles": 0}, "compression": {"enabled": False},
                "tools": {"tool_search": {"enabled": "off"}},
                "auxiliary": {"title_generation": {"enabled": False, "model_upgrade_enabled": False}},
            }))
            installed = subprocess.run([sys.executable, str(artifact / "install.py"), "--artifact", str(artifact),
                                        "--profile-home", str(profile)], env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            output = sandbox / "result.json"
            probe = subprocess.run([sys.executable, str(ROOT / "tests" / "hermes" / "real_agent_probe.py"),
                                    "--case", case, "--output", str(output)], env=environment, cwd=work,
                                   capture_output=True, text=True, timeout=45)
            self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
            result = json.loads(output.read_text())
            self.assertTrue(result["fixture"])
            self.assertTrue(result["processes_reaped"])
            return result

    def test_hermes_executes_and_returns_a_host_tool_through_one_resident_worker(self):
        result = self.run_probe("tool")
        self.assertTrue(result["completed"])
        self.assertEqual(result["tool_executions"], 1)
        self.assertEqual(result["api_calls"], 2)

    def test_hermes_hard_interrupt_cancels_the_active_native_request_and_reaps_processes(self):
        result = self.run_probe("cancel")
        self.assertTrue(result["interrupted"])
        self.assertEqual(result["tool_executions"], 0)


if __name__ == "__main__":
    unittest.main()
