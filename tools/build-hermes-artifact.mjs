import { cp, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(
  process.env.HERMES_BUILD_DIR ??
    join(
      homedir(),
      "dev",
      "agentic-scratchpads",
      "pi-claude-cli",
      "hermes-provider-build",
    ),
);
const plugin = join(output, "plugin");
const runtime = join(plugin, "runtime");
const packageData = JSON.parse(
  await readFile(join(root, "package.json"), "utf8"),
);
const lock = JSON.parse(
  await readFile(join(root, "package-lock.json"), "utf8"),
);

try {
  const entries = await readdir(output);
  if (entries.length)
    throw new Error(`Refusing to overwrite non-empty build output: ${output}`);
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
await mkdir(runtime, { recursive: true });
const tsc = join(root, "node_modules", "typescript", "bin", "tsc");
const compile = spawnSync(
  process.execPath,
  [
    tsc,
    "--project",
    join(root, "tsconfig.hermes.json"),
    "--noEmit",
    "false",
    "--declaration",
    "false",
    "--declarationMap",
    "false",
    "--sourceMap",
    "false",
    "--rootDir",
    root,
    "--outDir",
    runtime,
  ],
  { cwd: root, encoding: "utf8" },
);
if (compile.status !== 0) {
  process.stderr.write(compile.stdout ?? "");
  process.stderr.write(compile.stderr ?? "");
  process.exit(compile.status ?? 1);
}
await cp(join(root, "hermes"), plugin, {
  recursive: true,
  filter: (source) =>
    !source.includes("__pycache__") && !source.endsWith(".pyc"),
});
await cp(
  join(root, "src", "drivers", "cli", "host-mcp.mjs"),
  join(runtime, "src", "drivers", "cli", "host-mcp.mjs"),
);
await cp(
  join(root, "tools", "install-hermes-artifact.py"),
  join(output, "install.py"),
);
await cp(join(root, "LICENSE"), join(output, "LICENSE"));
await writeFile(
  join(runtime, "package.json"),
  JSON.stringify(
    { type: "module", private: true, dependencies: packageData.dependencies },
    null,
    2,
  ) + "\n",
);

let copied = 0;
for (const [relative, entry] of Object.entries(lock.packages)) {
  if (!relative.startsWith("node_modules/") || entry.dev === true) continue;
  const source = join(root, relative);
  const destination = join(runtime, relative);
  try {
    await readFile(join(source, "package.json"), "utf8");
  } catch {
    continue;
  }
  await mkdir(dirname(destination), { recursive: true });
  await cp(source, destination, { recursive: true, dereference: true });
  copied += 1;
}
const metadata = {
  artifactFormat: 1,
  providerId: "pi-claude-cli",
  packageVersion: packageData.version,
  workerProtocolVersion: 1,
  nodeEngine: packageData.engines.node,
  buildPlatform: process.platform,
  buildArchitecture: process.arch,
  runtimeDependencyPackagesCopied: copied,
  driverDependencies: packageData.dependencies,
};
await writeFile(
  join(output, "artifact.json"),
  JSON.stringify(metadata, null, 2) + "\n",
);
process.stdout.write(
  `${JSON.stringify({ artifact: output, metadata }, null, 2)}\n`,
);
