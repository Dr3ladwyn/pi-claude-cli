import { afterEach, expect, it, vi } from "vitest";
import { createVersionCheck } from "../src/version-policy.js";

afterEach(() => vi.restoreAllMocks());
it.each([
  ["garbage", "2.0.0"],
  ["1.0.0", "garbage"],
  ["1.0.0", "1.0.0"],
  ["2.0.0", "1.0.0"],
])("rejects invalid policy %s to %s", (minimum, maximum) => {
  expect(() => createVersionCheck("fixture", minimum, maximum)).toThrow(
    "Invalid supported version range",
  );
});
it.each(["1.0.0-rc.1", "1.0.0+build", "1.0.9007199254740992"])(
  "rejects unsupported version syntax %s",
  (version) => {
    expect(() =>
      createVersionCheck("fixture", "1.0.0", "2.0.0")(version, {}),
    ).toThrow("malformed stable release version");
  },
);
it("compares numerically across patch, minor, and major boundaries", () => {
  const check = createVersionCheck("fixture", "2.9.9", "3.0.0");
  expect(() => check("1.99.999", {})).toThrow("requires fixture 2.9.9");
  expect(() => check("2.8.999", {})).toThrow("requires fixture 2.9.9");
  expect(() => check("2.9.10", {})).not.toThrow();
  expect(() => check("2.10.0", {})).not.toThrow();
  const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
  check("3.0.0", { PI_CLAUDE_CLI_STRICT_VERSION: "0" });
  check("4.0.0", {});
  expect(warning).toHaveBeenCalledOnce();
  expect(() => check("3.0.0", { PI_CLAUDE_CLI_STRICT_VERSION: "1" })).toThrow(
    "strict version mode",
  );
});
