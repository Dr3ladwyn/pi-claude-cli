"""Unit translation regressions; real installed-loop coverage is separate."""
import unittest
from unittest.mock import patch

from hermes.client import HermesClaudeClient, to_transcript, _response, NATIVE_REPLAY_TYPE, _event_chunks
from hermes import profile
from providers.base import OMIT_TEMPERATURE


class RequestTranslationTests(unittest.TestCase):
    def test_system_instructions_use_native_system_prompt_not_prompt_history(self):
        client = HermesClaudeClient(command="node", args=(), client_kwargs={})
        captured = []

        def capture(payload, *args):
            captured.append(payload["request"])
            return [{"type": "round_end", "reason": "stop", "content": []}]

        try:
            with patch.object(client._worker, "request", side_effect=capture):
                client.chat.completions.create(model="fixture-model", messages=[
                    {"role": "system", "content": "Keep the host's contract."},
                    {"role": "user", "content": "hello"},
                ])
            self.assertEqual(captured[0]["systemPrompt"], "Keep the host's contract.")
            self.assertEqual([m["role"] for m in captured[0]["transcript"]], ["user"])
            self.assertEqual(captured[0]["input"]["messages"], captured[0]["transcript"])
        finally:
            client.close()

    def test_tool_result_name_is_recovered_from_its_authoritative_call_id(self):
        transcript = to_transcript([
            {"role": "assistant", "tool_calls": [{"id": "call-1", "function": {"name": "lookup", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "host result"},
        ])
        self.assertEqual(transcript[-1]["toolName"], "lookup")

    def test_developer_and_user_prompt_tail_is_sent_in_original_order(self):
        client = HermesClaudeClient(command="node", args=(), client_kwargs={})
        captured = []
        def capture(payload, *args):
            captured.append(payload["request"])
            return [{"type": "round_end", "reason": "stop", "content": []}]
        try:
            with patch.object(client._worker, "request", side_effect=capture):
                client.chat.completions.create(model="fixture-model", messages=[
                    {"role": "user", "content": "old"}, {"role": "assistant", "content": "old reply"},
                    {"role": "developer", "content": "new constraint"}, {"role": "user", "content": "new prompt"},
                ])
            request = captured[0]
            self.assertEqual(request["input"]["messages"], request["transcript"][2:])
            self.assertEqual(request["input"]["content"], [{"type": "text", "text": "new constraint"}, {"type": "text", "text": "new prompt"}])
        finally:
            client.close()

    def test_only_latest_proposal_results_are_submitted_to_parked_handlers(self):
        client = HermesClaudeClient(command="node", args=(), client_kwargs={})
        captured = []
        def capture(payload, *args):
            captured.append(payload["request"])
            return [{"type": "round_end", "reason": "stop", "content": []}]
        def proposal(call_id):
            return {"role": "assistant", "tool_calls": [{"id": call_id, "function": {"name": "lookup", "arguments": "{}"}}]}
        try:
            with patch.object(client._worker, "request", side_effect=capture):
                client.chat.completions.create(model="fixture-model", messages=[
                    {"role": "user", "content": "run"}, proposal("old-call"),
                    {"role": "tool", "tool_call_id": "old-call", "content": "old result"},
                    proposal("current-call"), {"role": "tool", "tool_call_id": "current-call", "content": "new result"},
                ])
            self.assertEqual([r["toolCallId"] for r in captured[0]["input"]["results"]], ["current-call"])
        finally:
            client.close()

    def test_completed_response_replays_exact_signed_and_redacted_native_blocks(self):
        native = [
            {"type": "thinking", "thinking": "fixture plan", "signature": "opaque-fixture-signature"},
            {"type": "redacted_thinking", "data": "opaque-fixture-redaction"},
            {"type": "text", "text": "checking"},
            {"type": "tool_call", "id": "signed-call", "name": "lookup", "arguments": {"key": "alpha"}},
        ]
        events = [
            {"type": "driver_event", "event": {"type": "content_start", "content": {"type": "thinking", "thinking": ""}}},
            {"type": "driver_event", "event": {"type": "assistant_snapshot", "content": native}},
            {"type": "driver_event", "event": {"type": "host_tool_request", "call": {"id": "signed-call", "name": "lookup", "arguments": {"key": "alpha"}}}},
            {"type": "round_end", "reason": "toolUse", "content": native},
        ]
        message = _response(events, "request", "fixture-model").choices[0].message
        wire = {"role": "assistant", "content": message.content, "reasoning_details": message.reasoning_details,
                "tool_calls": [{"id": c.id, "function": vars(c.function)} for c in message.tool_calls]}
        self.assertEqual(to_transcript([wire])[0]["content"], native)

    def test_profile_declares_private_replay_carrier_ownership(self):
        self.assertEqual(profile.native_reasoning_details_type, NATIVE_REPLAY_TYPE)

    def test_profile_routes_low_effort_to_native_worker_request(self):
        self.assertEqual(profile.build_api_kwargs_extras(reasoning_config={"enabled": True, "effort": "low"}), ({}, {"reasoning_effort": "low"}))

    def test_profile_has_a_non_http_external_process_route_marker(self):
        self.assertEqual(profile.base_url, "process://pi-claude-cli")

    def test_opus_alias_delegates_version_selection_to_the_official_runtime(self):
        self.assertEqual(profile.model_aliases["opus"], "opus")
        self.assertIn("opus", profile.fallback_models)

    def test_profile_omits_http_sampling_defaults_for_native_runtime(self):
        self.assertIs(profile.fixed_temperature, OMIT_TEMPERATURE)

    def test_response_model_reports_the_native_served_model(self):
        events = [{"type": "driver_event", "event": {"type": "message_start", "model": "actual-native-model"}},
                  {"type": "round_end", "reason": "stop", "content": [{"type": "text", "text": "done"}]}]
        self.assertEqual(_response(events, "request", "requested-alias").model, "actual-native-model")

    def test_stream_deltas_allow_openai_attribute_access(self):
        chunk = _event_chunks({"type": "driver_event", "event": {"type": "content_delta", "delta": {"kind": "text", "text": "fixture text"}}}, "id", "fixture-model", {})[0]
        self.assertEqual(getattr(chunk.choices[0].delta, "content", None), "fixture text")
        self.assertEqual(chunk.choices[0].delta.get("content"), "fixture text")

    def test_profile_declares_unsupported_structured_output_to_auxiliary_callers(self):
        self.assertIn("json_schema", profile.unsupported_response_formats)
        self.assertIn("json_object", profile.unsupported_response_formats)


if __name__ == "__main__":
    unittest.main()
