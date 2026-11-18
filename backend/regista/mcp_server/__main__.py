"""Standalone MCP server over stdio, with its own replay and a ``seek`` tool.

    python -m regista.mcp_server [match.json] [--minute 60]

For an MCP client config: {"command": "python", "args": ["-m", "regista.mcp_server"], "cwd": "<repo>/backend"}.
Inside the API the same tools are served read-only at /mcp, on the clock viewers watch.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..api.app import DEFAULT_MATCH, load_match
from ..api.replay import Replay
from .server import build_server


def main() -> None:
    """Load the match, move the replay to ``--minute`` and serve over stdio."""
    ap = argparse.ArgumentParser(prog="python -m regista.mcp_server")
    ap.add_argument("match", nargs="?", type=Path, default=DEFAULT_MATCH)
    ap.add_argument("--minute", type=float, default=0.0, help="start the replay at this match minute")
    args = ap.parse_args()
    replay = Replay(load_match(args.match))
    replay.seek(replay.elapsed_for_minute(args.minute) if args.minute > 0 else 0.0)
    build_server(lambda: replay, can_seek=True).run("stdio")


if __name__ == "__main__":
    main()
