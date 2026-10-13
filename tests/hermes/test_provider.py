import importlib.util
from hermes.client import to_transcript, validate_request
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class HermesProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugin = ROOT / "hermes" / "__init__.py"
        spec = importlib.util.spec_from_file_location("hermes_provider", plugin)
        if spec is None or spec.loader is None:
            raise RuntimeError("Hermes plugin module cannot be loaded")
        cls.provider = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.provider
        spec.loader.exec_module(cls.provider)

    def test_provider_uses_a_distinct_external_process_identity(self):
        profile = self.provider.profile
        self.assertEqual(profile.name, "pi-claude-cli")
        self.assertEqual(profile.auth_type, "external_process")
        self.assertNotEqual(profile.name, "anthropic")
    def test_transport_and_async_wrap_bypasses_are_declared_on_client(self):
        client = self.provider.profile.create_client(command="node", args=("worker.js",))
        self.assertTrue(client.HERMES_SKIP_TRANSPORT_WRAP)
        self.assertTrue(client.HERMES_SKIP_ASYNC_WRAP)
        self.assertIsNone(client._worker._process)
        client.close()
    def test_login_status_is_not_fabricated_by_worker_availability(self):
        self.assertIsNone(self.provider.profile.setup_status())



    def test_history_translation_preserves_roles_tool_ids_and_signed_thinking(self):
        history = [
            {"role": "user", "content": "run"},
            {"role": "assistant", "reasoning_details": [{"type": "thinking", "signature": "sig", "text": "plan"}], "tool_calls": [{"id": "toolu_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"key\":\"v\"}"}}]},
            {"role": "tool", "tool_call_id": "toolu_1", "name": "lookup", "content": "ok"},
        ]
        transcript = to_transcript(history)
        self.assertEqual([message["role"] for message in transcript], ["user", "assistant", "tool_result"])
        self.assertEqual(transcript[1]["content"][0]["signature"], "sig")
        self.assertEqual(transcript[1]["content"][1]["id"], "toolu_1")
        self.assertEqual(transcript[2]["toolCallId"], "toolu_1")

    def test_unsupported_sampling_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "temperature"):
            validate_request({"temperature": 0.2})


if __name__ == "__main__":
    unittest.main()
