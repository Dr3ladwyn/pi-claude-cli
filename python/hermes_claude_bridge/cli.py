from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .setup_worker import cached_worker_path, install_worker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes-claude-bridge", description="Set up and inspect the local Hermes Claude worker.")
    parser.add_argument("--version", action="version", version=f"hermes-claude-bridge {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="download and verify the pinned worker, or import a local archive")
    setup.add_argument("--artifact", type=Path, help="local release archive for offline development/tests")
    commands.add_parser("status", help="show whether the explicit worker setup is present")
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            target = install_worker(local_artifact=args.artifact)
            print(f"Installed hermes-claude-bridge {__version__} worker at {target}")
        else:
            worker = cached_worker_path()
            print(json.dumps({"version": __version__, "workerReady": worker is not None, "worker": str(worker or ""), "setup": "hermes-claude-bridge setup"}, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"hermes-claude-bridge: {error}", file=sys.stderr)
        if args.command == "setup":
            print("Install the hermes-claude-bridge 0.5.1 wheel with its embedded Linux x64 worker manifest, then run `hermes-claude-bridge setup`.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
