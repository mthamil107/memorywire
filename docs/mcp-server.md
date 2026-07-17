# memorywire MCP server

Use memorywire from **any MCP-aware agent** (Claude Desktop, IDE assistants, other MCP clients).
The server exposes memorywire's operations — including `recover` — as MCP tools. No code changes:
add it to your client's config and the agent gains persistent, governable, recoverable memory.

## Install

```bash
pip install "memorywire[mcp,sqlite-vec]"
```

This provides the `memorywire-mcp` command (stdio transport).

## Configure your MCP client

Add memorywire to your client's server config. For Claude Desktop
(`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "memorywire": {
      "command": "memorywire-mcp",
      "env": {
        "MEMORYWIRE_STORE": "sqlite-vec://./mem.db",
        "MEMORYWIRE_AGENT": "assistant"
      }
    }
  }
}
```

- `MEMORYWIRE_STORE` — store URL (default `sqlite-vec://./memorywire-mcp.db`). Any memorywire store
  URL works (`mem0://…`, `pgvector://…`, etc.).
- `MEMORYWIRE_AGENT` — the `agent_id` scope (default `mcp`).

## Tools

| Tool | What it does |
|---|---|
| `remember` | Store a memory. **Set `source`** (user, tool_result, web_page, …) — `recover` relies on it. |
| `recall` | Retrieve the top-`k` memories for a query. |
| `forget` | Delete by ids or filter (soft-delete by default). |
| `merge` | Collapse duplicates into a canonical memory. |
| `expire` | Apply a TTL policy (age / confidence). |
| `recover` | Detect and clean poisoned memory. Purges untrusted-source poison, **quarantines** directives hidden in trusted memories for review. `dry_run` is **true by default** — it previews without changing anything. |

## Provenance matters

`recover` works by provenance: it trusts `source`. For it to be effective, have your agent set
`source` on every `remember` (e.g. `source="tool_result"` for tool output, `source="web_page"` for
retrieved content, `source="user"` for user statements). Content the agent authored or the user
stated is trusted; tool/web content is not. Untagged writes default to untrusted-unknown and will
be flagged by `recover`.

## Notes

- v0.1 uses **stdio** transport. HTTP/SSE is a small follow-on.
- This is the "memorywire-as-MCP-tool" composition (see [`docs/MCP-RELATIONSHIP.md`](MCP-RELATIONSHIP.md)).
  A native MCP *extension* (`mcp.memory`) with the types lifted into MCP's own system is on the v0.5 roadmap.
