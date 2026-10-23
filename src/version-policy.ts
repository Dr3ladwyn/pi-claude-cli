/** Stable release triplets only. Prereleases aren't covered by our peer ranges. */
function parseVersion(version: string): number[] | undefined {
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version))
    return undefined;
  const parts = version.split(".").map(Number);
  return parts.every(Number.isSafeInteger) ? parts : undefined;
}

function compare(left: number[], right: number[]): number {
  for (let index = 0; index < 3; index++) {
    const difference = left[index] - right[index];
    if (difference !== 0) return difference;
  }
  return 0;
}

/** One warning per component per process, shared across drivers/registrations. */
export function createVersionCheck(
  component: string,
  minimum: string,
  exclusiveMaximum: string,
): (version: string, environment?: NodeJS.ProcessEnv) => void {
  const lower = parseVersion(minimum);
  const upper = parseVersion(exclusiveMaximum);
  if (!lower || !upper || compare(lower, upper) >= 0)
    throw new Error("Invalid supported version range");
  const range = `>=${minimum} <${exclusiveMaximum}`;
  const requirement = `pi-claude-cli requires ${component} ${minimum} or newer; supported range ${range}`;
  let warned = false;
  return (version, environment = process.env) => {
    const parsed = parseVersion(version);
    if (!parsed)
      throw new Error(`${requirement}; malformed stable release version`);
    if (compare(parsed, lower) < 0)
      throw new Error(`${requirement}; loaded ${version}`);
    if (compare(parsed, upper) < 0) return;
    if (environment.PI_CLAUDE_CLI_STRICT_VERSION === "1")
      throw new Error(`${requirement}; loaded ${version}; strict version mode`);
    if (!warned) {
      warned = true;
      // stderr keeps host RPC and stream-json stdout clean.
      console.warn(
        `pi-claude-cli: ${component} ${version} is above the tested range ${range}; continuing with an unverified version. Set PI_CLAUDE_CLI_STRICT_VERSION=1 to fail instead.`,
      );
    }
  };
}
