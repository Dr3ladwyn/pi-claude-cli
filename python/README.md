# hermes-claude-bridge

`hermes-claude-bridge` 0.5.0 is the Python distribution for the existing `pi-claude-cli` Hermes provider. It installs a standard `hermes_agent.plugins` entry point and the `hermes-claude-bridge` setup/status command. Importing the package or discovering the provider doesn't download, build, or start the worker and doesn't inspect Claude authentication.

Python 3.10+ and Node.js 22.19+ are required. The initial release worker is Linux x64 only. Other platforms fail with a supported-platform message.

## Install and set up

```nu
python -m pip install hermes-claude-bridge==0.5.0
hermes-claude-bridge setup
hermes-claude-bridge status
hermes plugins enable pi-claude-cli
```

`setup` downloads only the Linux x64 asset named by the release manifest embedded in this wheel, from the immutable `ramarivera/pi-claude-cli` GitHub release tag `v0.5.0`. It checks SHA256, extracts only regular files and directories, checks artifact version/provider/protocol/platform metadata, then atomically installs under `~/.cache/hermes-claude-bridge/0.5.0/linux/x64`. Set `HERMES_CLAUDE_BRIDGE_CACHE` to choose a different cache root. Setup never changes a selected provider, profile, credentials, or login state. A matching cache is reused; an unowned or different artifact is never overwritten.

The installed plugin continues to use provider id `pi-claude-cli` and the same native signed carrier and cached-client behavior as the local bundle. Local bundles prefer their sibling `runtime/` directory. Pip installations resolve the explicitly set-up worker cache.

## Building distributions

Build from the repository's `python/` directory after the release worker manifest exists. Pass the exact release manifest supplied by the release build as `HERMES_CLAUDE_BRIDGE_WORKER_MANIFEST=/path/to/worker-manifest.json`. The manifest format is version 1 with package version, provider id, protocol version, and artifacts containing platform, architecture, asset basename, and SHA256. The production manifest must describe the actual immutable release asset. Do not use a fixture manifest to build a release distribution.

```nu
with-env { HERMES_CLAUDE_BRIDGE_WORKER_MANIFEST: "/path/to/worker-manifest.json" } { uv build python --out-dir /path/to/output }
```

The Python build hook copies the authoritative `hermes/__init__.py`, `hermes/client.py`, and `hermes/worker_location.py` into the wheel as provider source and embeds the supplied manifest. It doesn't maintain a second facade implementation. The sdist carries the manifest too, so it can build the same wheel offline from its embedded input.

For offline development only, `hermes-claude-bridge setup --artifact /path/to/local-worker.tar.gz` uses the identical manifest hash and artifact metadata checks. A test fixture manifest and fixture archive are test data, not release assets.
