# Execution notes

## Scope and ownership

Feature `pcc-898`, branch `feat/hermes-provider`, base `317a412fa0e6ee1ee6629b4e03d85236438652bf`.

The implementation lane produced the Node adapter, Python facade and artifact tooling. The parent stopped that lane intentionally, preserved its edits/transcript and took ownership of real Hermes integration and final acceptance. The lane was not accepted as a completed implementation.

No dependencies, CI configuration, existing Pi/OMP registrations, login settings or active Hermes model selection were changed. Nothing was published or pushed. The user explicitly approved a few bounded live Opus checks using the existing login, with no extra-usage or billing-setting changes.

## Runtime discovery

The source checkout's old Python 3.11 `venv` is not the active dependency environment. Real Hermes-loop tests used the actual managed Python 3.14.7 environment and installed Hermes revision `0438ca2da53bf9caa4af4a5dacc0b2757a6ba3b9`.

Tests used isolated HOME/HERMES_HOME/XDG/config/temp roots. Real-loop probes disabled the installed project's dotenv loader before importing `run_agent`, since changing HOME alone does not prevent it loading the source checkout's `.env`. Offline probes also prohibited Python networking. Native model replies in those tests are authored CLI/SDK fixtures, not real-model output.

## Red/green integration findings

Parent receipts are under the owned `pcc-898-parent` scratch directory.

- The first actual Hermes loop failed because system instructions were projected into developer history but omitted from the current prompt suffix. A regression failed before system instructions were separated into the native system prompt.
- Hermes omits `name` from tool-result messages. A regression failed before the adapter recovered that name from the exact prior call ID.
- Ordered developer/user tails failed before all current prompt messages were submitted in order.
- A later tool round resubmitted old tool results. The latest-results regression failed before restricting submission to the latest proposal's result suffix.
- Signed replay duplicated an empty thinking start and omitted redacted thinking. The signed-replay regression failed before carrying complete final native blocks through provider-owned replay metadata.
- Profile regressions failed before declaring replay ownership, routing native effort, supplying a non-HTTP route marker, omitting HTTP temperature defaults and declaring unsupported structured formats.
- Served-model and streaming-shape regressions failed before reporting the native model and supporting attribute-accessible stream mappings.
- Terminating an actual worker settled its request and native fixture, but left the Python pipe handles open. The failure-pipes regression failed before retaining and disposing the exited transport handle. The fix was exercised against a rebuilt artifact.

The portable integration fixture initially exceeded the existing Unix socket path limit. Using the caller-owned short temp root fixed that fixture boundary without weakening the native driver. The synthetic SDK initialization was also missing its required runtime-version field; the fixture was corrected rather than relaxing production validation.

## Verified behavior

- Node offline suite: 627 passed, 6 skipped across 30 passing and 5 skipped test files.
- Python artifact/provider suite: 23 passed. It covers CLI and official SDK fixture transport, sync/async/stream calls, malformed/version-mismatched worker input, installer overwrite refusal, real Hermes host-tool execution, hard interruption, interleaved independent clients, worker termination, pipe closure and process reaping.
- Pi, OMP and Hermes TypeScript checks passed.
- ESLint, Prettier and `git diff --check` passed after scoped formatting fixes.
- A local built artifact was installed into fresh sandbox profiles and discovered through the normal provider loader, not merely imported from source.

## Approved live qualification

The newer global Claude Code 2.1.296 was rejected by the existing strict CLI guard before inference. The guard was not weakened. The CLI check used an already installed unmodified 2.1.285 executable; the SDK check used the official SDK's bundled version-paired runtime.

Both paths served `claude-opus-5-5` through the real Hermes conversation loop. Each made two Hermes API calls, executed the harmless host probe exactly once, returned the exact proposed tool-call ID and produced the marker supplied only by the host tool. Within each check, the worker PID stayed the same across tool rounds.

Machine-readable private receipts remain outside the repository:

- `pcc-898-parent/live-cli-candidate3/acceptance.json`
- `pcc-898-parent/live-sdk-candidate3/acceptance.json`

Live qualification used candidate 3. The subsequent EOF pipe-cleanup change affects failed/exited transports and was exercised offline on candidate 4. Final packaging reruns the installed-artifact suite without consuming more account allowance.

## Limits

Linux x64 was exercised. macOS/Windows live behavior and older Hermes revisions were not tested. Current Hermes primary external-process inference is non-streaming even though the facade supports stream deltas. Windows fallback cleanup does not establish full descendant-tree termination. Not every OpenAI control or Hermes auxiliary workflow is supported. Official-runtime execution and successful requests do not guarantee vendor endorsement, included billing or immunity from account enforcement.
