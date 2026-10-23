# Changelog

## 0.5.1

- Accept Claude Code `>=2.1.285 <2.2.0` and Pi `>=0.99.1 <0.100.0` without exact-version pins. Older or malformed versions still fail clearly before inference or registration.
- Accept newer stable releases with one warning per component per process. Set `PI_CLAUDE_CLI_STRICT_VERSION=1` to reject versions above the supported range.
- Widen Pi peers to the supported range. Keep OMP peers at `^18.8.6`, tested development versions pinned, and Agent SDK 0.3.285 paired with its bundled runtime.
- Prepare matching npm, Hermes worker and Python distribution versions at 0.5.1.
