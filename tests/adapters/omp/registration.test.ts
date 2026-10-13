import { beforeEach, describe, expect, it, vi } from "vitest";
import * as OmpAI from "@oh-my-pi/pi-ai";
import type * as OmpCatalog from "@oh-my-pi/pi-catalog/models";
import type {
  ExtensionAPI,
  ExtensionContext,
  ProviderConfig,
} from "@oh-my-pi/pi-coding-agent";
import type { Model } from "@oh-my-pi/pi-ai";
import type {
  ClaudeRuntime,
  HostRoundRequest,
} from "../../../src/contracts/index.js";
import { readRuntimeConfiguration } from "../../../entrypoints/config.js";
vi.mock(
  "@oh-my-pi/pi-utils",
  async () => import("@oh-my-pi/pi-utils/fetch-retry"),
);
vi.mock("@oh-my-pi/pi-ai", async () => {
  const native = await import("@oh-my-pi/pi-ai/utils/event-stream");
  return {
    getBundledModels: () => [
      {
        id: "claude-haiku-4-5",
        name: "Haiku",
        reasoning: false,
        input: ["text", "image"],
        cost: {},
        contextWindow: 200000,
        maxTokens: 64000,
      },
    ],

    createAssistantMessageEventStream: native.createAssistantMessageEventStream,
  };
});
const hostVersion = vi.hoisted(() => ({ value: "18.10.2" }));
vi.mock("@oh-my-pi/pi-coding-agent", () => ({
  get VERSION() {
    return hostVersion.value;
  },
}));
import { registerOmpAdapter } from "../../../src/adapters/omp/index.js";
import entrypoint from "../../../entrypoints/omp.js";

function setup() {
  let provider: ProviderConfig | undefined;
  const registerProvider = vi.fn((id: string, config: ProviderConfig) => {
    expect(id).toBe("pi-claude-cli");
    provider = config;
  });
  const on = vi.fn();
  const api = { registerProvider, on } as unknown as ExtensionAPI;
  return {
    api,
    on,
    registerProvider,
    provider: () => {
      if (!provider) throw new Error("Provider missing");
      return provider;
    },
  };
}
describe("OMP discovery and native registration", () => {
  beforeEach(() => {
    hostVersion.value = "18.10.2";
  });
  it.each(["18.8.6", "18.8.7", "18.10.2", "19.0.0"])(
    "registers against host capabilities rather than OMP version %s",
    (version) => {
      hostVersion.value = version;
      const host = setup();
      expect(() => registerOmpAdapter(host.api)).not.toThrow();
      expect(host.registerProvider).toHaveBeenCalledOnce();
    },
  );
  it("exposes a native default entrypoint", () => {
    expect(typeof entrypoint).toBe("function");
  });
  it("rejects a missing native catalog capability before registration", () => {
    const catalog = vi.spyOn(
      OmpAI as typeof OmpAI &
        Partial<Pick<typeof OmpCatalog, "getBundledModels">>,
      "getBundledModels",
      "get",
    );
    catalog.mockReturnValue(undefined);
    const host = setup();
    try {
      expect(() => registerOmpAdapter(host.api)).toThrow(
        "OMP native extension catalog export is unavailable",
      );
      expect(host.registerProvider).not.toHaveBeenCalled();
      expect(host.on).not.toHaveBeenCalled();
    } finally {
      catalog.mockRestore();
    }
  });
  it("registers the provider and uses the shared configuration/runtime factory", async () => {
    const host = setup();
    const requests: HostRoundRequest[] = [];
    const backend: ClaudeRuntime = {
      async *streamRound(request) {
        requests.push(request);
        yield {
          type: "round_end",
          roundId: request.roundId,
          reason: "stop",
          content: [{ type: "text", text: "done" }],
          pendingToolCallIds: [],
        };
      },
      invalidate: vi.fn(async () => {}),
      close: vi.fn(async () => {}),
      closeAll: vi.fn(async () => {}),
    };
    const configuration = readRuntimeConfiguration({ PI_CLAUDE_DRIVER: "sdk" });
    const runtimeFactory = vi.fn(async () => backend);
    registerOmpAdapter(host.api, { configuration, runtimeFactory });
    expect(runtimeFactory).not.toHaveBeenCalled();
    const start = host.on.mock.calls.find(
      ([name]) => name === "session_start",
    )?.[1] as (event: unknown, ctx: ExtensionContext) => void;
    start({ type: "session_start" }, {
      cwd: "/native-cwd",
      agent: { kind: "main", id: "Main", name: "main", depth: 0 },
      sessionManager: { getSessionId: () => "host" },
      ui: { setStatus: vi.fn() },
    } as unknown as ExtensionContext);
    expect(host.provider().models?.[0]).toMatchObject({
      id: "claude-haiku-4-5",
      reasoning: false,
      thinking: undefined,
    });
    const nativeStream = host.provider().streamSimple?.(
      {
        id: "claude-haiku-4-5",
        api: "pi-claude-cli",
        provider: "pi-claude-cli",
        reasoning: false,
      } as Model,
      { messages: [{ role: "user", content: "hello", timestamp: 0 }] },
      {
        cwd: "/native-cwd",
        onPayload: (payload) => ({
          ...(payload as HostRoundRequest),
          systemPrompt: "hook",
        }),
      },
    );
    expect((await nativeStream?.result())?.content).toEqual([
      { type: "text", text: "done" },
    ]);
    expect(runtimeFactory).toHaveBeenCalledWith(configuration);
    expect(requests[0]).toMatchObject({
      cwd: "/native-cwd",
      systemPrompt: "hook",
      auth: { mode: "claude-login" },
    });
  });
});
