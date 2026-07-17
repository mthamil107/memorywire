"""memorywire MCP server — expose memorywire operations (including recover) as MCP tools.

Run as ``memorywire-mcp`` (stdio). Any MCP-aware agent can then remember / recall / forget /
merge / expire / recover memory. See :mod:`memorywire.mcp.server`.
"""
from __future__ import annotations

__all__ = ["main"]


def main() -> None:  # thin re-export so `python -m memorywire.mcp` and the entry point agree
    from .server import main as _main

    _main()
