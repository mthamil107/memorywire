"""memorywire MCP server (stdio).

Exposes the memorywire operations as MCP tools so any MCP-aware agent can use memorywire memory
— and clean it with ``recover`` — by adding this server to its client config. Store and agent are
configured via environment variables:

    MEMORYWIRE_STORE   store URL (default: sqlite-vec://./memorywire-mcp.db)
    MEMORYWIRE_AGENT   agent_id scope (default: mcp)

Run:  ``memorywire-mcp``
"""
from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from memorywire import ExpireAction, Memory, MemoryType, MergeStrategy
from memorywire.recovery import Recoverer

INSTRUCTIONS = (
    "memorywire memory operations. Store memories with `remember` (set `source` to where the "
    "memory came from — user, tool_result, web_page, etc.; recovery depends on it). Read with "
    "`recall`. Clean a poisoned store with `recover` (dry_run=true previews without changing "
    "anything)."
)

mcp = FastMCP("memorywire", instructions=INSTRUCTIONS)

_mem: Memory | None = None


def _memory() -> Memory:
    global _mem
    if _mem is None:
        store = os.environ.get("MEMORYWIRE_STORE", "sqlite-vec://./memorywire-mcp.db")
        agent = os.environ.get("MEMORYWIRE_AGENT", "mcp")
        _mem = Memory(agent_id=agent, stores=[store])
    return _mem


def _dump(obj: Any) -> Any:
    return obj.model_dump(mode="json", exclude_none=True) if hasattr(obj, "model_dump") else obj


@mcp.tool()
async def remember(
    content: str,
    type: str = "semantic",
    source: str | None = None,
    user_id: str | None = None,
    confidence: float = 1.0,
) -> dict:
    """Store a memory. `type` is one of semantic|episodic|procedural|emotional. Set `source` to
    the memory's origin (user, system, tool_result, web_page, ...) — `recover` relies on it."""
    r = await _memory().remember(
        content, type=MemoryType(type), source=source, user_id=user_id, confidence=confidence
    )
    return {"id": r.id}


@mcp.tool()
async def recall(query: str, k: int = 5, types: list[str] | None = None) -> dict:
    """Retrieve up to `k` memories matching `query`."""
    hits = await _memory().recall(
        query, k=k, types=[MemoryType(t) for t in types] if types else None
    )
    return {"results": [_dump(h) for h in hits]}


@mcp.tool()
async def forget(
    ids: list[str] | None = None,
    filter: dict | None = None,
    hard_delete: bool = False,
    reason: str | None = None,
) -> dict:
    """Delete memories by `ids` or `filter` (at least one required). Soft-delete by default."""
    r = await _memory().forget(ids=ids, filter=filter, hard_delete=hard_delete, reason=reason)
    return {"forgotten": len(r.forgotten_ids)}


@mcp.tool()
async def merge(canonical: str, duplicates: list[str], strategy: str = "keep_canonical") -> dict:
    """Collapse `duplicates` into `canonical`. strategy: keep_canonical|merge_content|keep_highest_confidence."""
    r = await _memory().merge(canonical, duplicates, strategy=MergeStrategy(strategy))
    return _dump(r)


@mcp.tool()
async def expire(policy: dict, action: str = "forget") -> dict:
    """Apply a TTL policy (e.g. {"older_than_days": 30, "confidence_below": 0.5}). action: forget|archive|demote."""
    r = await _memory().expire(policy, action=ExpireAction(action))
    return _dump(r)


@mcp.tool()
async def recover(
    trusted_sources: list[str] | None = None,
    mode: str = "provenance",
    use_detectors: bool = False,
    hard_delete: bool = False,
    dry_run: bool = True,
) -> dict:
    """Detect and recover poisoned memory. Purges memories from untrusted sources, quarantines
    trusted-source entries that look like embedded directives (for human review), and optionally
    expires low-confidence rows. `dry_run` (default true) previews without changing anything."""
    trusted = set(trusted_sources) if trusted_sources else {"user", "system"}
    detectors = None
    if use_detectors:
        from memorywire.recovery.strategies import directive_detector

        detectors = [directive_detector]
    rec = Recoverer(_memory(), trusted_sources=trusted, detectors=detectors)
    report = await rec.recover(
        expire_low_conf=(mode == "provenance+expire"),
        hard_delete=hard_delete,
        dry_run=dry_run,
    )
    return report.to_dict()


def main() -> None:
    _memory()  # fail fast on bad store config before entering the stdio loop
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
