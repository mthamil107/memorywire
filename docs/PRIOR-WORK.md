# Prior work and naming

This project was originally drafted under the name "AMP — Agent Memory
Protocol" in May 2026. After submission we discovered that
[akshayaggarwal99/amp](https://github.com/akshayaggarwal99/amp) had
already published a project under the same name (created Dec 2025).

Their project is an MCP-native memory server you run locally —
plug-and-play with Claude Desktop / Cursor / VS Code Copilot,
with visualizations (Galaxy view, Force view, semantic query) and
a three-layer working-memory / long-term / graph design.

This project (memwire) is a different shape: a vendor-neutral wire
format for agent memory operations + a reference implementation with
five backend adapters (sqlite-vec, mem0, Letta, Cognee, pgvector) +
a governance UI for diff-and-approve workflows on memory writes.

To disambiguate, we renamed this project to `memwire` before launch.
Both projects are open source under permissive licenses and address
overlapping problem spaces from different angles.
