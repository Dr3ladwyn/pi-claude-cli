import { readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

function isSystemdUserReaper(pid) {
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
    const fields = stat.slice(stat.lastIndexOf(")") + 2).split(" ");
    const uid = process.getuid?.();
    const status = readFileSync(`/proc/${pid}/status`, "utf8");
    const owner = status.match(/^Uid:\s+(\d+)/m)?.[1];
    const cgroup = readFileSync(`/proc/${pid}/cgroup`, "utf8");
    const args = readFileSync(`/proc/${pid}/cmdline`, "utf8")
      .split("\0")
      .filter(Boolean);
    return (
      uid !== undefined &&
      stat.slice(stat.indexOf("(") + 1, stat.lastIndexOf(")")) === "systemd" &&
      fields[1] === "1" &&
      owner === String(uid) &&
      cgroup.includes(`/user-${uid}.slice/user@${uid}.service/init.scope`) &&
      args[0] === "/usr/lib/systemd/systemd" &&
      args[1] === "--user"
    );
  } catch {
    return false;
  }
}

export function managedPiHelperCommand(name, executable, argv, root) {
  const broker = join(root, "pi-intercom/broker/broker.ts");
  const cli = join(root, "tsx/dist/cli.mjs");
  const preflight = join(root, "tsx/dist/preflight.cjs");
  const loader = pathToFileURL(join(root, "tsx/dist/loader.mjs")).href;
  const node =
    ["node", "node-MainThread"].includes(name) &&
    /\/node(?:js)?$/.test(executable);
  if (node && argv.length === 3 && argv[1] === cli && argv[2] === broker)
    return "pi-intercom";
  if (
    node &&
    argv.length === 6 &&
    argv[1] === "--require" &&
    argv[2] === preflight &&
    ["--import", "--loader"].includes(argv[3]) &&
    argv[4] === loader &&
    argv[5] === broker
  )
    return "pi-intercom";
  const compiler = join(root, "@esbuild/linux-x64/bin/esbuild");
  if (
    name === "esbuild" &&
    executable === compiler &&
    argv.length === 3 &&
    argv[0] === compiler &&
    /^--service=\d+\.\d+\.\d+$/.test(argv[1]) &&
    argv[2] === "--ping"
  )
    return "intercom-compiler";
}

export function managedPiHelper(
  process,
  root = join(homedir(), ".pi/agent/npm/node_modules"),
) {
  if (!["node", "node-MainThread", "esbuild"].includes(process.name)) return;
  try {
    const argv = readFileSync(`/proc/${process.pid}/cmdline`, "utf8")
      .split("\0")
      .filter(Boolean);
    const executable = realpathSync(`/proc/${process.pid}/exe`);
    const stat = readFileSync(`/proc/${process.pid}/stat`, "utf8");
    if (stat.slice(stat.lastIndexOf(")") + 2).split(" ")[19] !== process.start)
      return;
    return managedPiHelperCommand(process.name, executable, argv, root);
  } catch {
    /* A process can exit before classification; unknown children stay strict. */
  }
}

export function nativeHelperCleanup(
  cleanup,
  baseline,
  hostPid,
  baselineProcesses,
  allowIntercom = false,
) {
  const observed = new Map(
    cleanup.observedProcesses.map((process) => [process.pid, process]),
  );
  const original = new Map(
    baselineProcesses.map((process) => [process.pid, process]),
  );
  const helpers = [],
    rejected = [];
  for (const pid of cleanup.forcedChildren) {
    const process = observed.get(pid);
    const before = original.get(pid);
    let reason;
    const ancestors = [];
    const postBaselineIntercom =
      !baseline.has(pid) &&
      allowIntercom &&
      ["pi-intercom", "intercom-compiler"].includes(before?.helperOwner) &&
      process?.helperOwner === before.helperOwner;
    if (!baseline.has(pid) && !postBaselineIntercom)
      reason = "after-inference-baseline";
    else if (!process || !before) reason = "missing-process-evidence";
    else if (
      !["node", "node-MainThread", "esbuild"].includes(process.name) ||
      process.name !== before.name
    )
      reason = "unknown-helper-name";
    else if (
      process.name === "node" &&
      (before.helperOwner !== "pi-intercom" ||
        process.helperOwner !== before.helperOwner)
    )
      reason = "unverified-node-command";
    else if (process.start !== before.start)
      reason = "changed-process-identity";
    else {
      // Require the first observed ancestry to reach the owned host, then
      // check current recorded ancestry too.
      for (const graph of [original, observed]) {
        const visited = new Set();
        let cursor = pid;
        let brokerSeen = false;
        while (cursor !== hostPid) {
          if (visited.has(cursor) || visited.size >= 32) {
            reason = "unbounded-or-cyclic-ancestry";
            break;
          }
          visited.add(cursor);
          const ancestor = graph.get(cursor);
          if (!ancestor) {
            reason = "unknown-ancestry";
            break;
          }
          if (/claude/i.test(ancestor.name)) {
            reason = "claude-transport-ancestry";
            break;
          }
          if (postBaselineIntercom) {
            const anchor = original.get(cursor),
              current = observed.get(cursor);
            if (
              !anchor ||
              !current ||
              anchor.start !== current.start ||
              anchor.name !== current.name ||
              anchor.helperOwner !== current.helperOwner
            ) {
              reason = "changed-ancestor-identity";
              break;
            }
            if (
              current.parent !== anchor.parent &&
              current.parent !== 1 &&
              !isSystemdUserReaper(current.parent)
            ) {
              reason = "changed-ancestor-parent";
              break;
            }
            if (
              !["pi-intercom", "intercom-compiler"].includes(
                ancestor.helperOwner,
              )
            ) {
              reason = "unverified-intercom-ancestry";
              break;
            }
            brokerSeen ||= ancestor.helperOwner === "pi-intercom";
          }
          // Linux may reparent a proven helper to this user's systemd
          // manager instead of PID 1. Verify the exact manager before ending
          // the observed ancestry walk; the original ancestry still reached
          // the owned host above.
          if (
            graph === observed &&
            postBaselineIntercom &&
            isSystemdUserReaper(ancestor.parent)
          )
            break;
          if (graph === original) ancestors.push(cursor);
          // A host exit can reparent a proven startup helper to Linux init.
          if (graph === observed && ancestor.parent === 1) break;
          cursor = ancestor.parent;
        }
        if (
          !reason &&
          postBaselineIntercom &&
          graph === original &&
          !brokerSeen
        )
          reason = "missing-intercom-broker";
        if (reason) break;
      }
      if (!reason && postBaselineIntercom) {
        const anchor = original.get(hostPid),
          current = observed.get(hostPid);
        if (
          !anchor ||
          !current ||
          anchor.start !== current.start ||
          anchor.name !== current.name
        )
          reason = "changed-host-identity";
      }
    }
    if (reason) rejected.push({ pid, reason });
    else
      helpers.push({
        pid,
        name: process.name,
        parent: before.parent,
        start: process.start,
        ancestors,
        ...(postBaselineIntercom ? { helperOwner: before.helperOwner } : {}),
      });
  }
  return {
    allowedHelperCount: helpers.length,
    allowedHelpers: helpers.slice(0, 32),
    rejectedCount: rejected.length,
    rejectedChildren: rejected.slice(0, 32),
  };
}
