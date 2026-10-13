import { createInterface } from "node:readline";
import {
  createConfiguredRuntime,
  readRuntimeConfiguration,
} from "../../../entrypoints/runtime.js";
import type {
  ClaudeRuntime,
  HistoryInvalidationReason,
  HostRoundRequest,
  HostSessionIdentity,
} from "../../contracts/index.js";
import {
  HERMES_WORKER_PROTOCOL_VERSION,
  parseWorkerInput,
  type WorkerMessage,
} from "./protocol.js";

const write = (packet: Record<string, unknown>): void => {
  process.stdout.write(`${JSON.stringify(packet)}\n`);
};
const log = (message: string): void => {
  process.stderr.write(
    `[hermes-worker] ${message.replace(/[\r\n\t]/g, " ").slice(0, 400)}\n`,
  );
};
const runtimePromise: { value?: Promise<ClaudeRuntime> } = {};
const controllers = new Map<string, AbortController>();
const activeOwners = new Set<string>();
let handshaken = false;
let shuttingDown = false;

async function runtime(): Promise<ClaudeRuntime> {
  runtimePromise.value ??= createConfiguredRuntime();
  return runtimePromise.value;
}

function sessionIdentity(value: unknown): HostSessionIdentity {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new Error("Session identity must be an object");
  const session = value as Record<string, unknown>;
  if (
    typeof session.sessionId !== "string" ||
    typeof session.branchId !== "string" ||
    typeof session.historyRevision !== "string"
  )
    throw new Error("Session identity fields are invalid");
  return {
    sessionId: session.sessionId,
    branchId: session.branchId,
    historyRevision: session.historyRevision,
  };
}

async function round(message: WorkerMessage): Promise<void> {
  if (shuttingDown) throw new Error("Worker is shutting down");
  if (
    typeof message.request !== "object" ||
    message.request === null ||
    Array.isArray(message.request)
  )
    throw new Error("Round request must be an object");
  const request = message.request as HostRoundRequest;
  const identity = sessionIdentity(request.session);
  if (typeof request.roundId !== "string" || request.roundId.length === 0)
    throw new Error("Round request requires roundId");
  if (!Array.isArray(request.transcript) || !Array.isArray(request.tools))
    throw new Error(
      "Round request requires transcript and effective tools arrays",
    );
  const owner = identity.sessionId;
  if (activeOwners.has(owner))
    throw new Error("Overlapping rounds for one session are unsupported");
  const controller = new AbortController();
  controllers.set(message.id, controller);
  activeOwners.add(owner);
  try {
    const configuration = readRuntimeConfiguration();
    const configured = await runtime();
    for await (const event of configured.streamRound({
      ...request,
      auth: configuration.auth,
      settings: {
        ...configuration.settings,
        ...request.settings,
        claudeTools: configuration.settings.claudeTools,
        userMcpServers: configuration.settings.userMcpServers,
        settingSources: configuration.settings.settingSources,
      },
      signal: controller.signal,
    })) {
      write({
        version: HERMES_WORKER_PROTOCOL_VERSION,
        id: message.id,
        type: "event",
        event,
      });
    }
    write({
      version: HERMES_WORKER_PROTOCOL_VERSION,
      id: message.id,
      type: "result",
    });
  } finally {
    controllers.delete(message.id);
    activeOwners.delete(owner);
  }
}

async function dispatch(message: WorkerMessage): Promise<void> {
  switch (message.type) {
    case "hello":
      if (handshaken) throw new Error("Handshake already completed");
      handshaken = true;
      write({
        version: HERMES_WORKER_PROTOCOL_VERSION,
        id: message.id,
        type: "ready",
        contractVersion: 1,
      });
      return;
    case "round":
      if (!handshaken) throw new Error("Handshake required before requests");
      await round(message);
      return;
    case "cancel": {
      if (!handshaken) throw new Error("Handshake required before requests");
      if (typeof message.targetId !== "string")
        throw new Error("Cancel requires targetId");
      const controller = controllers.get(message.targetId);
      if (controller) controller.abort(new Error("Host cancelled request"));
      write({
        version: HERMES_WORKER_PROTOCOL_VERSION,
        id: message.id,
        type: "result",
        cancelled: Boolean(controller),
      });
      return;
    }
    case "invalidate": {
      if (!handshaken) throw new Error("Handshake required before requests");
      const session = sessionIdentity(message.session);
      const reasons: readonly HistoryInvalidationReason[] = [
        "compaction",
        "tree",
        "branch",
        "fork",
        "import",
        "abort",
        "reset",
        "reload",
      ];
      if (
        typeof message.reason !== "string" ||
        !reasons.includes(message.reason as HistoryInvalidationReason)
      )
        throw new Error("Unsupported history invalidation reason");
      await (
        await runtime()
      ).invalidate(session, message.reason as HistoryInvalidationReason);
      write({
        version: HERMES_WORKER_PROTOCOL_VERSION,
        id: message.id,
        type: "result",
      });
      return;
    }
    case "close": {
      if (!handshaken) throw new Error("Handshake required before requests");
      const session = sessionIdentity(message.session);
      await (await runtime()).close(session.sessionId);
      write({
        version: HERMES_WORKER_PROTOCOL_VERSION,
        id: message.id,
        type: "result",
      });
      return;
    }
    case "shutdown":
      shuttingDown = true;
      for (const controller of controllers.values())
        controller.abort(new Error("Worker shutdown"));
      await (await runtimePromise.value)?.closeAll();
      write({
        version: HERMES_WORKER_PROTOCOL_VERSION,
        id: message.id,
        type: "result",
      });
      process.stdin.pause();
      return;
  }
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", (line) => {
  let message: WorkerMessage;
  try {
    message = parseWorkerInput(line);
  } catch (error) {
    const detail =
      error instanceof Error ? error.message : "Invalid worker input";
    write({
      version: HERMES_WORKER_PROTOCOL_VERSION,
      id: null,
      type: "error",
      error: detail,
    });
    return;
  }
  void dispatch(message).catch((error: unknown) => {
    const detail =
      error instanceof Error ? error.message : "Worker request failed";
    log(detail);
    write({
      version: HERMES_WORKER_PROTOCOL_VERSION,
      id: message.id,
      type: "error",
      error: detail,
    });
  });
});
input.on("close", () => {
  shuttingDown = true;
  for (const controller of controllers.values())
    controller.abort(new Error("Worker input closed"));
  void runtimePromise.value
    ?.then((value) => value.closeAll())
    .catch((error: unknown) => {
      log(error instanceof Error ? error.message : "Runtime shutdown failed");
      process.exitCode = 1;
    });
});
