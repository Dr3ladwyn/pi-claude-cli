import { spawnSync } from "node:child_process";
import { copyFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

it("answers the control fixture version without loading MCP dependencies", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pcc-version-only-"));
  try {
    const target = join(directory, "fixture.mjs");
    await copyFile(
      fileURLToPath(new URL("./offline-claude.mjs", import.meta.url)),
      target,
    );
    const result = spawnSync(process.execPath, [target, "--version"], {
      encoding: "utf8",
      timeout: 1000,
      env: {},
    });
    expect(result.stderr).toBe("");
    expect(result.status).toBe(0);
    expect(result.stdout).toContain("2.1.285");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

it("answers the protocol fixture version without loading MCP dependencies", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pcc-version-only-"));
  try {
    const target = join(directory, "fixture.mjs");
    await copyFile(
      fileURLToPath(
        new URL("../../support/offline-protocol-cli.mjs", import.meta.url),
      ),
      target,
    );
    const result = spawnSync(process.execPath, [target, "--version"], {
      encoding: "utf8",
      timeout: 1000,
      env: {},
    });
    expect(result.stderr).toBe("");
    expect(result.status).toBe(0);
    expect(result.stdout).toContain("2.1.285");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
