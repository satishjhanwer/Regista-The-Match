"""Match state over the Model Context Protocol (needs the ``mcp`` package, in the ``api`` extra)."""

from .server import build_server

__all__ = ["build_server"]
