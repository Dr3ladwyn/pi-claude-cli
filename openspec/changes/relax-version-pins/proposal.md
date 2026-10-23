# Supported runtime version ranges

Bead: `pcc-zwq`.

0.5.0 rejects every Claude CLI or Pi version except the exact tested binary. Consumers need compatible patches without repinning their whole host.

Use the tested minimum with a conservative minor boundary: Claude `>=2.1.285 <2.2.0`, Pi `>=0.99.1 <0.100.0`. Fail below the minimum and on malformed output. Above the boundary, warn once per component per process and continue unless `PI_CLAUDE_CLI_STRICT_VERSION=1`. Keep the existing OMP range and the version-paired Agent SDK dependency. Document the protocol/API assumptions and keep existing framing/correlation failures intact.

Owned files include the shared version policy, CLI/Pi adapters, matching tests, package metadata/lockfile, current compatibility/installation docs, changelog, and coordinated Hermes/Python version constants. No new runtime dependency. Finish with full offline Linux gates, compiled OMP probes, offline Node harness, coordinated release artifacts, and a committed/pushed ready PR. Publishing, tags, releases, active-profile changes and authenticated inference are excluded.
