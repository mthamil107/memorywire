# Agent Memory Protocol (AMP)

> Vendor-neutral protocol and reference implementation for agent memory operations.

AMP is to agent memory what MCP is to agent tool-use: a small, stable wire format so any memory client can talk to any memory backend, and any agent can carry its memory across runtimes.

**Status: v0 draft.** Spec and reference implementation under active development. See [`docs/spec/v0.md`](docs/spec/v0.md) once published.

## What AMP defines

- **5 operations** — `remember`, `recall`, `forget`, `merge`, `expire`
- **4 memory types** — `semantic`, `episodic`, `procedural`, `emotional`
- **A `MemoryStore` interface** that backends implement
- **A memory router** with RRF fusion (k=60) + optional 1-hop graph boost across N backends
- **An FSM-based procedural memory backend** (via `pytransitions`)
- **An always-on STM↔LTM transformer** for background consolidation
- **An optional governance channel** for human-in-the-loop diff-and-approve workflows

## Quick install (once published)

```bash
pip install agent-memory-protocol
# or with backend extras
pip install "agent-memory-protocol[sqlite-vec,mem0]"
```

## Minimal example

```python
import asyncio
from amp import Memory, MemoryType

async def main():
    mem = Memory(
        agent_id="my-agent",
        stores=["sqlite-vec://./mem.db", "mem0://default"],
    )
    await mem.remember(
        "Alice is allergic to peanuts",
        type=MemoryType.SEMANTIC,
        user_id="alice@example.com",
    )
    hits = await mem.recall("what should I avoid feeding alice?", k=5)
    for h in hits:
        print(h.score, h.content)

asyncio.run(main())
```

## Project layout

```
src/amp/              # protocol + reference implementation
  schemas/            # JSON Schema 2020-12 files (operations + types)
  store/              # MemoryStore adapters (sqlite-vec, mem0, ...)
  governance/         # diff / health / audit modules
ui/                   # governance UI (Starlette + HTMX, Pro tier)
docs/                 # spec + adapter guide + benchmarks
docs/kickoff/         # original kickoff materials (vision, findings, plan)
examples/             # runnable end-to-end demos
tests/                # unit / integration / benchmarks
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Spec edits are PRs against `docs/spec/v0.md`. Adapter contributions are welcome — see [`docs/adapters.md`](docs/adapters.md) for the integration contract.

## License

Apache-2.0. See [`LICENSE`](LICENSE).

The governance UI in `ui/` is source-available under a separate Functional Source License (FSL); see `ui/LICENSE` once published.
