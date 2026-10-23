# Supported versions

This modernization targets current releases only. There isn't a legacy Pi adapter or migration layer.

| Component                          | Supported range / dependency |
| ---------------------------------- | ---------------------------- |
| Node.js                            | 22.19.0 or newer             |
| Canonical Pi (`@earendil-works/*`) | `>=0.99.1 <0.100.0`          |
| Oh My Pi (`@oh-my-pi/*`)           | `^18.8.6`                    |
| Published Claude Code executable   | `>=2.1.285 <2.2.0`           |
| Official Claude Agent SDK          | 0.3.285, pinned              |
| MCP SDK                            | 1.31.0, pinned               |

## Version policy

Claude CLI and Pi fail below their tested minimum, accept stable releases inside the supported range silently, and accept newer releases with one warning per component per process. Warnings go to stderr so host RPC/stream-json stdout stays clean. `PI_CLAUDE_CLI_STRICT_VERSION=1` rejects releases at or above the exclusive upper bound instead. It doesn't require the exact minimum and can't bypass the minimum or malformed-version checks. The CLI uses its merged driver environment; Pi uses the host process environment.

Version checks accept canonical stable `major.minor.patch` triplets. Claude's `--version` may append a parenthesized product label, as in `2.1.285 (Claude Code)`. Banners, extra output lines, prereleases, build suffixes and malformed/unsafe numeric components fail before startup. Prereleases aren't included in the peer ranges and need separate qualification.

The Claude bound keeps the current 2.1 protocol family. The driver depends on newline-delimited `stream-json` input/output, `--include-partial-messages`, stdio permission/control requests, initialize/interrupt and queue acknowledgements, `--system-prompt-file`, `--strict-mcp-config`, `--setting-sources`, `--no-session-persistence`, and correlated native MCP calls. These dependencies justify a conservative minor boundary, not proof that every 2.1 patch has been tested. The minimum remains the protocol fixture/live reference, 2.1.285. Later minor/major versions are unverified and warn; required framing, controls and tool correlation still fail explicitly if incompatible.

Pi's pre-1.0 minor boundary protects its native `registerProvider`/`streamSimple`, lifecycle, event projection, tool schemas and provider callback contracts. Peer dependencies use the same supported range. Development dependencies stay at 0.99.1 so typechecks and fixtures retain a reproducible baseline. Newer hosts outside the peer range can run with the warning policy, but package managers may report a peer mismatch.

The OMP adapter has no numeric runtime gate. It uses native APIs and checks its required catalog export before registration. Its peers remain `^18.8.6`, with development dependencies pinned to 18.8.6. A later version loading successfully doesn't establish full inference compatibility. The root entrypoint and provider ID remain `pi-claude-cli`.

## Agent SDK dependency

The installed `@anthropic-ai/claude-agent-sdk@0.3.285` manifest declares `claudeCodeVersion: "2.1.285"` and exact optional platform-runtime dependencies at 0.3.285. Its default query transport resolves that bundled native runtime; `pathToClaudeCodeExecutable` can select an explicit executable. Inspection of its subprocess startup shows no `--version` preflight or exact external-version comparison. This is a version-paired SDK distribution, not a constraint on the separate CLI driver, which directly spawns `claude` without loading SDK query transport.

Keep the SDK pin for reproducible SDK APIs and its paired runtime. Widening it would change the SDK transport and bundled executable, beyond relaxing the external CLI/Pi guards. The shared driver passes an explicit executable to the SDK only when configured. The default bundled SDK runtime retains its existing qualification; overriding it doesn't establish compatibility with every external CLI version.

The CLI host-tool bridge uses a private Unix-domain socket and process-group cleanup. Windows isn't supported by this driver. Linux is the current live-verification environment; macOS support requires its own live evidence. SDK transport also needs a supported official Claude executable/runtime.

Both drivers require authoritative `_meta["claudecode/toolUseId"]` on host MCP calls. That's a guarded Claude protocol extension, not a generic MCP guarantee. Missing correlation fails explicitly; the bridge never substitutes JSON-RPC IDs or guesses from call order.

Same-process continuation retains the resident Claude identity. Imported or changed host history can be replayed under a fresh Claude identity. This replay labels the complete host history as user-provided context; it doesn't import private Claude JSONL files or claim native assistant-turn persistence. Both production drivers accept queued steering at host tool boundaries, with native queue admission before releasing original results. OMP owns input until that boundary; immediate during-token preemption isn't integrated.

Provider payload callbacks receive the host-neutral request. Transport response observations use status `0` and transport metadata for these subprocess/query transports; they don't invent an HTTP response. Error/abort results carry each host's actual assistant-message shape.

The repository records approved scope and pinned research in `openspec/changes/modernize-claude-runtime/execution.md`. Target declarations alone aren't verification receipts.

## Verified execution

On September 30, 2026, all four standard actual-host cases passed at source revision `b40ee2b`: Pi + CLI, Pi + SDK, OMP + CLI and OMP + SDK. Each exercised seven authenticated phases, including native tools, resident continuation, saved-host-history replay under a fresh Claude ID, actual streaming/native-tool aborts, recovery and natural cleanup. Both OMP cases performed a real native hashline edit. This is Linux evidence, not macOS or Windows evidence.

The final matrix invocation passed three cases; OMP CLI needed a selected rerun after Claude first emitted a malformed patch and then corrected it. The strict one-edit assertion remained unchanged. All four accepted receipts use the same source revision; this isn't a claim that one matrix invocation returned four passes. The failed receipt remains documented in [the live harness evidence](./testing/live-harness.md).

The integrated offline gate passed 531 tests in 29 files, all three typecheck profiles, lint and formatting, with 94.14% line/statement coverage, 97.24% function coverage and 89.15% branch coverage against unchanged thresholds. Twenty-four Node harness tests also passed. Documentation/tracker commits following the verified revision don't change runtime source.
