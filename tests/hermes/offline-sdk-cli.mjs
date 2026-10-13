#!/usr/bin/env node
/** Synthetic executable for the official Agent SDK path. No inference, auth, or network. */
import { createInterface } from "node:readline";

const sessionId = "hermes-offline-sdk-session";
const send = (packet) => process.stdout.write(`${JSON.stringify(packet)}\n`);
const input = createInterface({ input: process.stdin });
let initialized = false;
for await (const line of input) {
  const packet = JSON.parse(line);
  if (packet.type === "control_request") {
    send({
      type: "control_response",
      response: {
        subtype: "success",
        request_id: packet.request_id,
        response: {},
      },
    });
    continue;
  }
  if (packet.type !== "user") continue;
  if (!initialized) {
    initialized = true;
    send({
      type: "system",
      subtype: "init",
      session_id: sessionId,
      model: "offline-no-inference",
      claude_code_version: "2.1.285",
      capabilities: [],
      tools: [],
      mcp_servers: [],
    });
  }
  const messageId = `message-${Date.now()}`;
  const text = packet.message.content[0]?.text ?? "";
  const answer = text.startsWith("hermes-sdk-text:")
    ? text.slice("hermes-sdk-text:".length)
    : "unexpected fixture prompt";
  const envelope = (value) =>
    send({ session_id: sessionId, parent_tool_use_id: null, ...value });
  const stream = (event) => envelope({ type: "stream_event", event });
  stream({
    type: "message_start",
    message: {
      id: messageId,
      model: "offline-no-inference",
      usage: { input_tokens: 1 },
    },
  });
  stream({
    type: "content_block_start",
    index: 0,
    content_block: { type: "text", text: "" },
  });
  stream({
    type: "content_block_delta",
    index: 0,
    delta: { type: "text_delta", text: answer },
  });
  stream({ type: "content_block_stop", index: 0 });
  envelope({
    type: "assistant",
    uuid: `${messageId}-assistant`,
    message: {
      id: messageId,
      model: "offline-no-inference",
      content: [{ type: "text", text: answer }],
      stop_reason: "end_turn",
      usage: { input_tokens: 1, output_tokens: 1 },
    },
  });
  stream({
    type: "message_delta",
    delta: { stop_reason: "end_turn" },
    usage: { output_tokens: 1 },
  });
  stream({ type: "message_stop" });
  envelope({
    type: "result",
    uuid: `${messageId}-result`,
    subtype: "success",
    is_error: false,
    result: answer,
    usage: { input_tokens: 1, output_tokens: 1 },
    total_cost_usd: 0,
  });
}
