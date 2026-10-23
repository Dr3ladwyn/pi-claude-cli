import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { configuration, host } from "./support.js";

const native = vi.hoisted(() => ({ version: "0.99.1" }));
vi.mock("@earendil-works/pi-coding-agent", () => ({
  get VERSION() {
    return native.version;
  },
}));

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv("PI_CLAUDE_CLI_STRICT_VERSION", "");
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

it.each(["0.99.0", "0.98.99"])(
  "rejects Pi %s before registration",
  async (version) => {
    native.version = version;
    const { registerPiAdapter } =
      await import("../../../src/adapters/pi/index.js");
    const api = host().pi;
    expect(() => registerPiAdapter(api, { configuration })).toThrow(
      "requires Pi 0.99.1",
    );
    expect(api.registerProvider).not.toHaveBeenCalled();
  },
);
it.each(["0.99.1", "0.99.2", "0.99.999"])(
  "accepts Pi %s silently",
  async (version) => {
    native.version = version;
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { registerPiAdapter } =
      await import("../../../src/adapters/pi/index.js");
    const api = host().pi;
    registerPiAdapter(api, { configuration });
    expect(api.registerProvider).toHaveBeenCalledOnce();
    expect(warning).not.toHaveBeenCalled();
  },
);
it("warns once above the tested Pi range across adapter registrations", async () => {
  const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
  const { registerPiAdapter } =
    await import("../../../src/adapters/pi/index.js");
  for (const version of ["0.100.0", "1.0.0"]) {
    native.version = version;
    const api = host().pi;
    registerPiAdapter(api, { configuration });
    expect(api.registerProvider).toHaveBeenCalledOnce();
  }
  expect(warning).toHaveBeenCalledTimes(1);
  expect(warning.mock.calls[0]?.[0]).toContain(">=0.99.1 <0.100.0");
});
it.each(["", "garbage", "0.99", "0.99.1extra", "00.99.1", "0.99.1\n1.0.0"])(
  "rejects malformed Pi version %j",
  async (version) => {
    native.version = version;
    const { registerPiAdapter } =
      await import("../../../src/adapters/pi/index.js");
    expect(() => registerPiAdapter(host().pi, { configuration })).toThrow(
      "requires Pi 0.99.1",
    );
  },
);
it("strict mode rejects newer Pi even after a warning and accepts in-range Pi", async () => {
  vi.spyOn(console, "warn").mockImplementation(() => {});
  const { registerPiAdapter } =
    await import("../../../src/adapters/pi/index.js");
  native.version = "0.100.0";
  registerPiAdapter(host().pi, { configuration });
  vi.stubEnv("PI_CLAUDE_CLI_STRICT_VERSION", "1");
  expect(() => registerPiAdapter(host().pi, { configuration })).toThrow(
    "strict version mode",
  );
  native.version = "0.99.2";
  expect(() => registerPiAdapter(host().pi, { configuration })).not.toThrow();
});
