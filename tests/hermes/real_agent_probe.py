"""Real Hermes loop probe with an explicitly synthetic native CLI backend.

Run only in a fresh allowlisted subprocess. Inference, provider construction,
worker protocol and host tool dispatch are real; only the native model replies
are authored fixture data. This file never selects a real Claude executable.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--case", choices=("tool", "cancel"), required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

home = Path(os.environ["HERMES_HOME"]).resolve()
assert os.environ["HERMES_TEST_ISOLATION"] == str(home)
assert Path(os.environ["CLAUDE_CONFIG_DIR"]).is_relative_to(home.parent)
fixture = Path(os.environ["PI_CLAUDE_EXECUTABLE"]).resolve()
assert fixture.name == "offline-protocol-cli.mjs"
assert os.environ["PI_CLAUDE_DRIVER"] == "cli"
receipt_path = Path(os.environ["PCC_SCENARIO_RECEIPT"])

with patch("hermes_cli.env_loader.load_hermes_dotenv", return_value=[]), patch("socket.socket.connect", side_effect=AssertionError("Python networking is forbidden in this fixture")):
    from providers import get_provider_profile
    from run_agent import AIAgent
    from tools.registry import registry

    profile = get_provider_profile("pi-claude-cli")
    assert profile is not None
    calls = []
    marker = "HERMES-HOST-FIXTURE-OK"

    def probe(arguments, **_context):
        calls.append(arguments)
        return json.dumps({"value": marker})

    registry.register(name="pcc_probe", toolset="pcc_probe", schema={
        "name": "pcc_probe", "description": "Read-only authored fixture marker",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"], "additionalProperties": False},
    }, handler=probe)
    agent = AIAgent(provider=profile.name, api_mode="chat_completions", base_url=profile.base_url,
                    api_key="external-process", command=profile.process_command, args=list(profile.process_args),
                    model="offline-model", enabled_toolsets=["pcc_probe"], disabled_toolsets=[],
                    session_id="hermes-fixture-" + args.case, session_db=None, cwd=str(Path.cwd()),
                    quiet_mode=True, save_trajectories=False, verbose_logging=False, skip_context_files=True,
                    load_soul_identity=False, skip_memory=True, skip_background_review=True,
                    checkpoints_enabled=False, credential_pool=None, fallback_model=None,
                    max_iterations=3, max_tokens=512, reasoning_config={"enabled": True, "effort": "low"}, run_budget_seconds=30)
    assert type(agent.client).__name__ == "HermesClaudeClient"
    assert getattr(agent, "valid_tool_names") == {"pcc_probe"}
    module = importlib.import_module(type(agent.client).__module__)
    original_start = module._Worker._start
    worker_pids = set()

    def observe_start(worker):
        process = original_start(worker)
        worker_pids.add(process.pid)
        return process

    module._Worker._start = observe_start
    result = {}
    thread = None
    summary = {"fixture": True, "case": args.case}
    try:
        command: dict[str, object] = {"turn": "real-hermes-fixture", "mode": "tools" if args.case == "tool" else "hold"}
        if args.case == "tool":
            command["calls"] = [{"id": "toolu_real_loop", "name": "pcc_probe", "arguments": {"key": "alpha"}}]
            result = agent.run_conversation(json.dumps(command))
            assert result["completed"] and not result["failed"] and not result["interrupted"], result
            assert calls == [{"key": "alpha"}], calls
            assert marker in result["final_response"], result
            assert result["api_calls"] == 2, result
            proposals = [c for m in result["messages"] if m["role"] == "assistant" for c in m.get("tool_calls", [])]
            results = [m for m in result["messages"] if m["role"] == "tool"]
            assert len(proposals) == 1 and len(results) == 1
            assert proposals[0]["id"] == results[0]["tool_call_id"] == "toolu_real_loop"
            native = json.loads(receipt_path.read_text())
            assert len(native["prompts"]) == 1 and len(native["results"]) == 1, native
            assert marker in json.dumps(native["results"]), native
        else:
            def run():
                result.update(agent.run_conversation(json.dumps(command)))
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if receipt_path.exists() and json.loads(receipt_path.read_text()).get("prompts"):
                    break
                time.sleep(0.025)
            else:
                raise AssertionError("Native fixture never reached an active request")
            agent.interrupt(hard_cancel=True)
            thread.join(timeout=10)
            assert not thread.is_alive(), "Hermes hard cancellation did not settle"
            assert result.get("interrupted") and not result.get("failed"), result
            assert calls == [], calls
            native = json.loads(receipt_path.read_text())
        assert len(worker_pids) == 1, worker_pids
        summary.update({"completed": result.get("completed"), "interrupted": result.get("interrupted"),
                        "api_calls": result.get("api_calls"), "tool_executions": len(calls),
                        "worker_pids": sorted(worker_pids), "native_pid": native["pid"]})
    finally:
        agent.close()
        module._Worker._start = original_start
        registry.deregister("pcc_probe")
    for pid in [*worker_pids, summary["native_pid"]]:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise AssertionError(f"Owned process still exists after close: {pid}")
    summary["processes_reaped"] = True
    Path(args.output).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
