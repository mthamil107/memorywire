# memorywire

> Vendor-neutral protocol and reference implementation for agent memory operations.

Status: **v0 draft**, under active development.

## Where to start

| If you want toâ€¦ | Read |
|---|---|
| Understand the wire format | [`spec/v0.md`](spec/v0.md) (published in Phase 1) |
| Use memorywire in an app | [`getting-started.md`](getting-started.md) |
| Add a new backend | [`adapters.md`](adapters.md) |
| Govern memory writes with HITL | [`governance-ui.md`](governance-ui.md) |
| Compare against LongMemEval/LoCoMo/BEAM | [`benchmarks.md`](benchmarks.md) |
| Read the project's origin story | [`kickoff/KICKOFF.md`](kickoff/KICKOFF.md) and siblings |

## Vision in one paragraph

memorywire is to agent memory what MCP is to agent tool-use: a small, stable wire format so any memory client can talk to any memory backend, and any agent can carry its memory across runtimes. v0 defines five operations (`remember`/`recall`/`forget`/`merge`/`expire`), four memory types (`semantic`/`episodic`/`procedural`/`emotional`), a `MemoryStore` interface, and a memory router that fuses results across N backends with RRF (k=60) + optional 1-hop graph boost. A governance channel layers diff-and-approve workflows on top for compliance contexts.
