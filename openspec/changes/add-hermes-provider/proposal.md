# Add Hermes model-provider integration

## Outcome

Add an installable Hermes `model-provider` plugin that talks to the existing Claude bridge through a resident, versioned Node NDJSON worker. The worker reuses the neutral runtime and configured official CLI or Agent SDK driver. Hermes retains host tool execution and approvals; Claude's official login is the default, with explicit API-key mode only.

## Decisions

- Preserve the repository identity, package version, and Pi/OMP entrypoints.
- Register provider ID `pi-claude-cli` only in Hermes's provider registry; do not alias or replace `anthropic`.
- Keep worker sessions resident across tool-result calls and scope ownership by client/session IDs. Reject same-owner overlapping rounds.
- Keep stdout protocol-only, use sanitized stderr diagnostics, and implement cancellation/shutdown as worker control messages.
- Build a version-paired, local artifact containing compiled JavaScript and runtime dependencies. The installer copies only into the selected Hermes plugin directory and refuses unrelated collisions.
- Do not read host OAuth credentials, implement usage authentication, perform inference during discovery, or make paid/live calls in offline tests.

## Acceptance checklist

- [ ] Versioned request/response/stream protocol validates handshakes, IDs, malformed data and shutdown.
- [ ] Python plugin discovery, canonical history/tools conversion, streaming/non-streaming and async/sync client paths work through the Node worker and real core with offline native fixtures.
- [ ] Cancellation, close, crashes, history invalidation, compaction, result matching and concurrent owner isolation have deterministic tests.
- [ ] Compiled artifact build, package smoke and profile-safe installer run from the built artifact.
- [ ] Installation/configuration/auth/runtime constraints and limitations are documented.
- [ ] Required offline suite and scoped checks pass; exact evidence is written to the worker result path.
