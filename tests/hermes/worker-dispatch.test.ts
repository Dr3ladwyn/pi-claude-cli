import { EventEmitter } from "node:events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({
  input: undefined as EventEmitter | undefined,
  packets: [] as Record<string, unknown>[],
  close: vi.fn(),
  closeAll: vi.fn(),
  invalidate: vi.fn(),
  streamRound: vi.fn(),
  create: vi.fn(),
}));
vi.mock("node:readline", () => ({ createInterface: () => fixture.input }));
vi.mock("../../entrypoints/runtime.js", () => ({
  createConfiguredRuntime: fixture.create,
  readRuntimeConfiguration: () => ({
    auth: { mode: "claude-login" },
    settings: { claudeTools: [], userMcpServers: {}, settingSources: [] },
  }),
}));

const session = { sessionId: "test", branchId: "main", historyRevision: "1" };
const request = {
  session,
  roundId: "round",
  transcript: [],
  tools: [],
  settings: {},
};
async function send(type: string, extra: Record<string, unknown> = {}) {
  const id = `request-${fixture.packets.length}`;
  fixture.input?.emit(
    "line",
    JSON.stringify({ version: 1, id, type, ...extra }),
  );
  await vi.waitFor(() =>
    expect(fixture.packets.some((p) => p.id === id && p.type !== "event")).toBe(
      true,
    ),
  );
  return fixture.packets.find((p) => p.id === id && p.type !== "event");
}

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  fixture.input = new EventEmitter();
  fixture.packets.length = 0;
  fixture.streamRound.mockImplementation(async function* () {
    yield { type: "round_end", reason: "stop" };
  });
  fixture.create.mockResolvedValue(fixture);
  const originalWrite = process.stdout.write.bind(process.stdout);
  vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
    if (typeof chunk === "string" && chunk.startsWith('{"version":1,')) {
      fixture.packets.push(JSON.parse(chunk) as Record<string, unknown>);
      return true;
    }
    return originalWrite(chunk);
  });
  vi.spyOn(process.stdin, "pause").mockReturnValue(process.stdin);
  await import("../../src/adapters/hermes-worker/index.js");
});
afterEach(() => vi.restoreAllMocks());

describe("Hermes worker dispatch", () => {
  it("handshakes without initializing the runtime and rejects another handshake", async () => {
    expect(await send("hello")).toMatchObject({
      type: "ready",
      contractVersion: 1,
    });
    expect(fixture.create).not.toHaveBeenCalled();
    expect(await send("hello")).toMatchObject({
      type: "error",
      error: "Handshake already completed",
    });
  });
  it.each(["round", "cancel", "invalidate", "close"])(
    "requires handshake for %s",
    async (type) => {
      expect(await send(type)).toMatchObject({
        type: "error",
        error: "Handshake required before requests",
      });
    },
  );
  it("frames malformed input without an invented request ID", () => {
    fixture.input?.emit("line", "{");
    expect(fixture.packets).toEqual([
      expect.objectContaining({ id: null, type: "error" }),
    ]);
  });
  it("streams a round and lazily reuses its runtime", async () => {
    await send("hello");
    expect(await send("round", { request })).toMatchObject({ type: "result" });
    expect(await send("round", { request })).toMatchObject({ type: "result" });
    expect(fixture.create).toHaveBeenCalledTimes(1);
    expect(fixture.streamRound).toHaveBeenCalledTimes(2);
    expect(fixture.packets.filter((p) => p.type === "event")).toHaveLength(2);
    expect(fixture.streamRound.mock.calls[0][0]).toMatchObject({
      auth: { mode: "claude-login" },
    });
  });
  it.each([
    [null, "Round request must be an object"],
    [{ ...request, session: null }, "Session identity must be an object"],
    [{ ...request, session: {} }, "Session identity fields are invalid"],
    [{ ...request, roundId: "" }, "Round request requires roundId"],
    [
      { ...request, tools: null },
      "Round request requires transcript and effective tools arrays",
    ],
  ])("rejects malformed rounds before runtime creation", async (bad, error) => {
    await send("hello");
    expect(await send("round", { request: bad })).toMatchObject({
      type: "error",
      error,
    });
    expect(fixture.create).not.toHaveBeenCalled();
  });
  it("invalidates and closes the supplied session", async () => {
    await send("hello");
    expect(
      await send("invalidate", { session, reason: "compaction" }),
    ).toMatchObject({ type: "result" });
    expect(fixture.invalidate).toHaveBeenCalledWith(session, "compaction");
    expect(await send("close", { session })).toMatchObject({ type: "result" });
    expect(fixture.close).toHaveBeenCalledWith("test");
    expect(
      await send("invalidate", { session, reason: "unknown" }),
    ).toMatchObject({
      type: "error",
      error: "Unsupported history invalidation reason",
    });
  });
  it("reports cancellation accurately and validates its target", async () => {
    await send("hello");
    expect(await send("cancel", { targetId: "not-running" })).toMatchObject({
      type: "result",
      cancelled: false,
    });
    expect(await send("cancel")).toMatchObject({
      type: "error",
      error: "Cancel requires targetId",
    });
  });
  it("closes an initialized runtime on shutdown and refuses new rounds", async () => {
    await send("hello");
    await send("round", { request });
    expect(await send("shutdown")).toMatchObject({ type: "result" });
    expect(fixture.closeAll).toHaveBeenCalledTimes(1);
    expect(process.stdin.pause).toHaveBeenCalled();
    expect(await send("round", { request })).toMatchObject({
      type: "error",
      error: "Worker is shutting down",
    });
  });
  it("closes the runtime on EOF", async () => {
    await send("hello");
    await send("round", { request });
    fixture.input?.emit("close");
    await vi.waitFor(() => expect(fixture.closeAll).toHaveBeenCalledTimes(1));
  });
});
