import { describe, expect, it } from "vitest";
import { parseWorkerInput } from "../../src/adapters/hermes-worker/protocol.js";

describe("Hermes worker protocol", () => {
  it("rejects protocol version mismatches before dispatch", () => {
    expect(() =>
      parseWorkerInput(JSON.stringify({ version: 2, id: "r1", type: "hello" })),
    ).toThrow(/protocol version/i);
  });

  it("requires a request ID and a supported message type", () => {
    expect(() =>
      parseWorkerInput(JSON.stringify({ version: 1, type: "hello" })),
    ).toThrow(/request ID/i);
    expect(() =>
      parseWorkerInput(
        JSON.stringify({ version: 1, id: "r1", type: "unknown" }),
      ),
    ).toThrow(/unsupported/i);
  });

  it("rejects malformed JSON at the protocol boundary", () => {
    expect(() => parseWorkerInput("{")).toThrow(/malformed worker JSON/i);
  });

  it("accepts a versioned handshake", () => {
    expect(
      parseWorkerInput(
        JSON.stringify({ version: 1, id: "hello-1", type: "hello" }),
      ),
    ).toEqual({
      version: 1,
      id: "hello-1",
      type: "hello",
    });
  });
});
