# Hermes provider

`pi-claude-cli` is a separate Hermes model provider. A thin Python facade runs the compiled Node worker over versioned stdio, reusing this repository's TypeScript core and official CLI/Agent SDK drivers. Hermes keeps its tools and approvals. Pi/OMP package names, provider registrations and entrypoints are unchanged.

## Build and install

Build from a checkout with its existing locked dependencies. The artifact includes Python files, compiled worker/core/drivers, runtime dependencies, official SDK platform assets and a local installer. Nothing downloads or compiles TypeScript on the first model call.

Nushell:

```nu
$env.HERMES_BUILD_DIR = ($env.HOME | path join "dev" "agentic-scratchpads" "pi-claude-cli" "hermes-provider-build")
npm run typecheck:hermes
npm run build:hermes
let profile_home = ($env.HERMES_HOME? | default ($env.HOME | path join ".hermes"))
^python3 ($env.HERMES_BUILD_DIR | path join "install.py") --artifact $env.HERMES_BUILD_DIR --profile-home $profile_home
```

The build refuses non-empty output directories. Choose a fresh build directory for another build. Build separately on each target OS/architecture; bundled SDK runtime assets are platform-specific.

The installer writes only `<profile-home>/plugins/model-providers/pi-claude-cli`. It refuses an existing target and does not change your selected model, credentials or configuration. The installer itself needs only Python's standard library. Select a different profile by supplying its explicit home directory.

## Use Opus

The SDK route is recommended because its official runtime is version-paired with the pinned dependency. Start a new Hermes CLI session without changing the global default:

```nu
with-env { PI_CLAUDE_DRIVER: "sdk" } { hermes --provider pi-claude-cli -m opus }
```

If an inherited `PI_CLAUDE_EXECUTABLE` is set, remove that override from the launch environment when you want the SDK's bundled runtime. A Desktop or gateway runtime needs these variables in its own launch environment. Exporting them in another terminal does not change an already-running runtime.

The aliases `opus`, `sonnet` and `haiku` are passed to the official runtime so it chooses the current corresponding model. The bridge uses a conservative 200,000-token context budget. This is not a claim that every account has the same maximum context entitlement.

`PI_CLAUDE_DRIVER=cli` remains the shared runtime's default. That driver deliberately requires unmodified Claude Code **2.1.285**. Set `PI_CLAUDE_EXECUTABLE` to an existing supported executable if the global CLI is newer. A mismatched version fails before inference. Do not remove the compatibility guard or silently route to another driver.

The bridge needs Node.js 22.19.0 or later and a Hermes installation with the external-process provider and provider-owned replay contracts. It was exercised against Hermes revision `0438ca2da53bf9caa4af4a5dacc0b2757a6ba3b9` with managed Python 3.14.7 on Linux x64. Older Hermes revisions and macOS/Windows live behavior are not qualified by that test.

## Authentication and tools

- `PI_CLAUDE_AUTH=claude-login` is the default. The selected official runtime owns its login and uses `CLAUDE_CONFIG_DIR` when configured. The Python facade and Node adapter do not read, refresh or relay subscription tokens.
- `PI_CLAUDE_AUTH=api-key` is an explicit billing choice. It uses the existing shared `ANTHROPIC_API_KEY` configuration; the plugin does not automatically switch to API billing.
- Shared configuration rejects conflicting inherited credentials, endpoint and cloud overrides. Import, registration and static model discovery do not start inference or inspect auth stores. Executable availability is not reported as verified login status.
- Hermes supplies its effective function tools and executes the returned proposals through its normal tool path. Native built-in tools and user MCP servers are disabled by default. Enabling them through shared `PI_CLAUDE_*` settings changes that tool boundary deliberately.
- No account-usage endpoint or token-reading subscription telemetry is implemented. Using an official runtime does **not** establish Anthropic endorsement or guarantee account-enforcement immunity. Check current vendor terms for your use case.

## Protocol and lifecycle

Worker stdin/stdout carry NDJSON with `version: 1`, request IDs and message types. The host handshakes with `hello`; the worker acknowledges `ready`. Requests are `round`, `cancel`, `invalidate`, `close` and `shutdown`. Responses are normalized `event` packets followed by `result`, or an explicit `error`. Diagnostics stay on stderr.

Each client owns its worker and session. Calls through one Python client serialize; overlapping rounds sent directly to the worker for one session are rejected. There is no HTTP inference server or global daemon.

The shared core parks native MCP handlers at a complete tool proposal. Hermes returns the corresponding result by exact call ID; the adapter recovers the tool name from the authoritative prior proposal when Hermes omits it. Only the latest proposal's results are submitted. The same worker/native session continues rather than replaying every tool round through a fresh process.

System instructions become the native system prompt, separately from user/developer history. Ordered prompt tails and transcript prefixes remain intact. Completed native assistant blocks, including signed and redacted thinking, survive through the provider-owned `pi-claude-cli.native_assistant` replay carrier. Edited visible history that conflicts with a carrier fails explicitly.

Sync and async calls, text/tool stream deltas, cancellation and close are supported. The tested Hermes primary loop currently disables streaming for external-process providers, so its text arrives as a completed response even though the facade exposes streaming. POSIX cleanup owns a worker process group; Windows fallback cleanup is limited to the direct worker unless the platform terminates its tree. Abrupt OS-level failures are not a cross-platform cleanup guarantee.

## Request boundaries

Text, data-URL user images, correlated tool calls/results, declared tools, native effort, output token limits, finish reasons and reported cache/reasoning usage are translated through the existing contracts. Incomplete argument deltas are not executable tool proposals. Unknown roles, malformed tool arguments and unsupported image sources fail explicitly.

Direct facade calls reject sampling controls, constrained `response_format`, parallel completions and unsupported effort values. The provider declares omitted temperature and unsupported structured formats to Hermes so ordinary HTTP defaults are not sent to the native runtime. Native thinking defaults remain runtime-owned when no supported effort is requested. This is not full OpenAI API parity or qualification of every Hermes auxiliary workflow.

## Verification

Nushell, using the Python interpreter that actually has your Hermes dependencies:

```nu
npm run test:offline
npm run typecheck:pi
npm run typecheck:omp
npm run typecheck:hermes
$env.PCC_HERMES_ARTIFACT = $env.HERMES_BUILD_DIR
# Set HERMES_PYTHON to your Hermes-managed environment's Python executable.
^($env.HERMES_PYTHON) -m unittest discover -s tests/hermes -p 'test_*.py' -v
```

The Python integration suite requires an explicit built artifact and a caller-owned `TMPDIR`. Keep that path short enough for the existing CLI driver's Unix socket. It uses fresh isolated homes and authored native CLI/SDK fixtures. The real-loop probes patch only startup dotenv loading and forbid Python networking; actual Hermes provider discovery, conversation control and host tool dispatch still run.

Offline qualification includes the compiled artifact, both driver paths, sync/async/stream behavior, malformed/version-mismatched protocol input, installer overwrite refusal, real Hermes host-tool continuation, hard cancellation and worker failure/pipe cleanup. These fixtures are not authenticated model evidence.

Separately approved live checks served `claude-opus-5-5` through both CLI and SDK. Each completed a real Hermes host-tool loop in two Hermes API calls with one tool execution and one resident worker. The live-tested candidate preceded an EOF pipe-cleanup fix; that later failure-path change was exercised on a rebuilt artifact by the termination regression. No login, global provider selection, extra-usage setting, publication or dependency installation was changed.
