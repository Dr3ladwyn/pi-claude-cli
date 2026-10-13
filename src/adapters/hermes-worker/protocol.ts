export const HERMES_WORKER_PROTOCOL_VERSION = 1 as const;

export interface WorkerMessage {
  version: typeof HERMES_WORKER_PROTOCOL_VERSION;
  id: string;
  type: "hello" | "round" | "cancel" | "invalidate" | "close" | "shutdown";
  request?: unknown;
  session?: unknown;
  reason?: unknown;
  targetId?: unknown;
}

export function parseWorkerInput(line: string): WorkerMessage {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    throw new Error("Malformed worker JSON input");
  }
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new Error("Worker message must be a JSON object");
  const message = value as Record<string, unknown>;
  if (message.version !== HERMES_WORKER_PROTOCOL_VERSION)
    throw new Error(
      `Unsupported worker protocol version ${String(message.version)}`,
    );
  if (typeof message.id !== "string" || message.id.length === 0)
    throw new Error("Worker message requires a request ID");
  const base = { version: HERMES_WORKER_PROTOCOL_VERSION, id: message.id };
  if (message.type === "hello") return { ...base, type: "hello" };
  if (message.type === "round")
    return { ...base, type: "round", request: message.request };
  if (message.type === "cancel")
    return { ...base, type: "cancel", targetId: message.targetId };
  if (message.type === "invalidate")
    return {
      ...base,
      type: "invalidate",
      session: message.session,
      reason: message.reason,
    };
  if (message.type === "close")
    return { ...base, type: "close", session: message.session };
  if (message.type === "shutdown") return { ...base, type: "shutdown" };
  throw new Error(`Unsupported worker message type ${String(message.type)}`);
}
