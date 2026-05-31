<h1 align="center">memorywire</h1>

<p align="center">
  <strong>A vendor-neutral wire format for agent memory operations.</strong>
</p>

<p align="center">
  <a href="https://github.com/mthamil107/memorywire/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/mthamil107/memorywire/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <a href="https://www.python.org"><img alt="Python" src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg"></a>
  <img alt="Status" src="https://img.shields.io/badge/status-v0%20draft-orange.svg">
  <img alt="Tests" src="https://img.shields.io/badge/tests-437%20passing-brightgreen.svg">
  <img alt="Adapters" src="https://img.shields.io/badge/adapters-5-brightgreen.svg">
</p>

<p align="center">
  <a href="https://memorywire-governance-demo.fly.dev">Try the governance UI live</a>
  &nbsp;&middot;&nbsp;
  <a href="docs/spec/v0.md">Read the spec</a>
  &nbsp;&middot;&nbsp;
  <a href="docs/MCP-RELATIONSHIP.md">How memorywire relates to MCP</a>
</p>

---

<p align="center">
  <img alt="memorywire in 13 seconds: islanded frameworks &rarr; memorywire layer &rarr; pending approval &rarr; diff &rarr; approve &rarr; audit log" src="docs/demos/memorywire-explainer.gif" width="560">
</p>

> **Everyone else built a memory _store_. memorywire is the vendor-neutral protocol and governance layer that sits _above_ all of them.**

## Positioning

Memory _storage_ for AI agents is saturated &mdash; mem0, Letta, Cognee, Zep, and a dozen others each ship their own format, their own database, and their own lock-in. memorywire is not another store. It's the thin, stable layer above them: one wire format so any agent can talk to any backend, carry its memory across runtimes, and let a human review and approve what gets remembered before it's committed.

If you already run mem0, Letta, or Cognee, keep them. memorywire gives you a single interface across all of them, plus a governance plane to audit what they remember.

## Why memorywire is different

memorywire's edge is **position**, not feature count. Four things set it apart from the rest of the agent-memory ecosystem.

**1. It's an interop layer, not a silo.** memorywire defines five operations (`remember`, `recall`, `forget`, `merge`, `expire`) as a stable JSON-Schema wire format, and routes them across pluggable backends &mdash; sqlite-vec, mem0, Letta, Cognee, and pgvector on day one. Every other project asks you to adopt _its_ store and _its_ format. memorywire lets you keep what you have and talk to all of it through one surface.

**2. Governance is built in &mdash; and almost no one else has it.** When `approval_required` is set, a `remember` call _stages_ instead of commits. The governance UI shows a structured diff against current state; a reviewer approves or rejects; the decision is audit-logged. Controlling and auditing what an agent is _allowed_ to remember is a real production need that the major memory frameworks simply don't address. This is memorywire's single strongest differentiator.

**3. Routers compose.** The memory router itself implements the `MemoryStore` protocol, so a router can be a backend for another router. Fan-out, fusion, and graph-boost all nest cleanly &mdash; an architectural property most memory systems don't have.

**4. Procedural memory is first-class.** Agent how-to is stored as serializable `transitions` state machines you can replay and inspect &mdash; not flattened into text or vectors. memorywire treats `semantic`, `episodic`, `procedural`, and `emotional` as distinct, spec-defined types rather than one undifferentiated blob.

### What memorywire does _not_ claim to invent

In the interest of an honest pitch: STM&harr;LTM consolidation and tiering are shared with systems like MemOS; RRF is a standard retrieval-fusion technique &mdash; the adversarial-fusion result in [&sect;5 of the paper](docs/paper/memorywire-paper.md) measures the well-known Byzantine-robustness of RRF in the agent-memory routing context, not a new theorem; and MCP composition is documented at [`docs/MCP-RELATIONSHIP.md`](docs/MCP-RELATIONSHIP.md) (three composition modes: memorywire-as-MCP-tool today, memorywire-as-MCP-extension targeted for v0.5). memorywire's claim isn't that these are new &mdash; it's that wrapping them in a **vendor-neutral protocol with a governance plane** is the part nobody else is doing.

## Demo

**Governance UI &mdash; diff and approve a pending memory, audit the decision:**

<p align="center">
  <img alt="memorywire governance UI diff-and-approve flow" src="docs/demos/ui.gif" width="820">
</p>

**`memorywire` CLI &mdash; remember, recall, forget:**

<p align="center">
  <img alt="memorywire CLI quickstart" src="docs/demos/cli.gif" width="720">
</p>

Reproduce: [`docs/demos/README.md`](docs/demos/README.md).

## Status

| Component | State |
| --- | --- |
| Spec v0 (5 operations &times; 4 memory types, JSON Schema 2020-12) | [draft published](docs/spec/v0.md) |
| Reference implementation (`pip install memorywire`) | shipped &mdash; not yet on PyPI |
| Backend adapters (5) | `sqlite-vec`, `mem0`, `letta`, `cognee`, `pgvector` |
| Memory router (RRF fusion + 1-hop graph boost) | shipped |
| FSM procedural memory (`transitions` library) | shipped |
| STM&harr;LTM async transformer | shipped |
| `memorywire` CLI (`remember` / `recall` / `forget`) | shipped |
| Governance UI (Starlette + HTMX, Pro tier) | shipped, see [`ui/`](ui/) |
| LongMemEval / LoCoMo benchmark | v0.2 (microbench live &mdash; see [Benchmarks](#benchmarks)) |
| IETF Internet-Draft | v0.5 |

Spec and reference implementation are Apache-2.0. The governance UI is source-available under FSL (becomes Apache-2.0 after 2 years).

## Install

```bash
# From source until first PyPI release
git clone https://github.com/mthamil107/memorywire
cd memorywire
uv venv && uv pip install -e ".[sqlite-vec]"

# With every backend
uv pip install -e ".[sqlite-vec,mem0,letta,cognee,postgres]"
```

When the package lands on PyPI:

```bash
pip install "memorywire[sqlite-vec,mem0,letta,cognee,postgres]"
```

## Quickstart

```python
import asyncio
from memorywire import Memory, MemoryType

async def main():
    mem = Memory(
        agent_id="customer-bot",
        stores=["sqlite-vec://./mem.db", "mem0://default"],
    )

    await mem.remember(
        "Alice is allergic to peanuts",
        type=MemoryType.SEMANTIC,
        user_id="alice@example.com",
    )
    await mem.remember(
        "On 2026-03-10 Alice reported a billing issue",
        type=MemoryType.EPISODIC,
        user_id="alice@example.com",
    )

    hits = await mem.recall(
        "what should I avoid feeding alice?",
        k=5,
        hops=1,
    )
    for h in hits:
        print(f"{h.score:.2f}  {h.type}  {h.content}")

asyncio.run(main())
```

End-to-end demos that actually run: [`examples/01_quickstart.py`](examples/01_quickstart.py) (50 facts &rarr; recall &rarr; forget) and [`examples/03_procedural_fsm.py`](examples/03_procedural_fsm.py) (FSM procedural memory).

## Architecture

```
                          +----------------------+
                          |  Governance UI       |
                          |  approvals . audit   |  Pro tier (FSL)
                          |  health . patterns   |
                          +----------+-----------+
                                     | same SQLite DB
                                     v
   +------------------+      +-------------------+      +---------------------+
   |  Agent / SDK     | ---> |  Memory router    | ---> |  MemoryStore        |
   |  memorywire CLI     |      |  RRF k=60         |      |  sqlite-vec | mem0  |
   |  memorywire.Memory  |      |  + graph boost    |      |  letta | (your own) |
   +------------------+      +-------------------+      +---------------------+
                                     |
                          +----------+----------+
                          v          v          v
                    procedural   STM<->LTM   governance
                    FSM (FSM     transformer   channel
                    via transitions)         (HITL approve)
```

## Concepts

**Five operations.** `remember`, `recall`, `forget`, `merge`, `expire`. Each is a JSON-Schema-defined request/response shape.

**Four memory types.** `semantic` (facts), `episodic` (events with time/place), `procedural` (how-to, encoded as `transitions`-compatible FSMs), `emotional` (sentiment associations).

**`MemoryStore` Protocol.** A runtime-checkable async Protocol with `remember` / `recall` / `forget` / `merge` / `expire` / `health` / `capabilities`. Any backend implementing it composes.

**Memory router.** Fans queries out across N stores, fuses results with RRF (k=60 by default), applies an optional 1-hop graph boost, returns a unified `RecallHit` list. The router itself implements `MemoryStore`, so routers compose.

**FSM procedural memory.** Store agent how-to procedures as `transitions` state machines &mdash; serialize, replay, inspect, edit in the UI. Spec &sect;7 fixes the JSON shape.

**STM&harr;LTM transformer.** Always-on async background task. Scores short-term items on importance + recency + recall-count and promotes them to long-term storage; evicts the rest. Pluggable scorer; deterministic clock injection for tests.

**Governance channel.** Optional. When configured, `remember`-with-`approval_required` calls stage instead of commit; the UI shows a structured diff against current state; reviewers approve or reject and the decision is audit-logged.

The full surface is one page: [`docs/spec/v0.md`](docs/spec/v0.md).

## Benchmarks

> Recall@5 = **1.000** on 42 labelled queries, ingest p50 **37.8 ms**, recall p50 **40.6 ms** &mdash; `sentence-transformers/all-MiniLM-L6-v2` + `sqlite-vec` &lcub;`:memory:`&rcub;, CPU-only.

This is a microbench, not LongMemEval/LoCoMo (deferred to v0.2). 100 hand-authored facts, 50 labelled queries (paraphrase / exact-match / multi-hit / no-match). Reproduce with `python scripts/run_microbench.py`. Full methodology and caveats in [`docs/benchmarks.md`](docs/benchmarks.md).

## How memorywire relates to existing memory frameworks

memorywire is a layer **above** the storage frameworks &mdash; not a competitor. The router calls into them.

| Project | Storage | Cross-vendor wire format | Diff-and-approve UI | FSM procedural memory |
| --- | :---: | :---: | :---: | :---: |
| **memorywire** | uses theirs | &check; | &check; | &check; |
| mem0 | own | &mdash; | &mdash; | &mdash; |
| Letta | own | &mdash; | &mdash; | &mdash; |
| Cognee | own | &mdash; | &mdash; | &mdash; |
| Zep / Graphiti | own | &mdash; | &mdash; | &mdash; |
| MCP memory extension | n/a | proposed | &mdash; | &mdash; |

If you already use mem0 or Letta or Cognee &mdash; keep using them. memorywire gives you a stable interface across them and a governance plane to audit what they remember.

## Why does this exist

Memory storage is saturated. Memory operations, governance, and the cross-vendor protocol layer above storage are not. The discovery story &mdash; four sequential research scouts converging on the same meta-pattern &mdash; lives in [`docs/kickoff/FINDINGS-CONTEXT.md`](docs/kickoff/FINDINGS-CONTEXT.md). The honest roadmap (best / likely / worst case + acquisition signals) is in [`docs/kickoff/FUTURE.md`](docs/kickoff/FUTURE.md).

## Project layout

```
src/memorywire/          # protocol + reference implementation (Apache-2.0)
  schemas/            # JSON Schema 2020-12 files (operations + types)
  store/              # MemoryStore adapters (sqlite-vec, mem0, letta)
  governance/         # diff / health / audit helpers
ui/                   # governance UI (Starlette + HTMX, FSL)
docs/                 # spec + adapter guide + benchmarks
  spec/v0.md          # the memorywire wire format
  kickoff/            # origin story, architecture, findings
examples/             # runnable end-to-end demos
tests/                # unit (380) / integration (env-gated) / benchmarks (opt-in)
scripts/              # verify_spec, run_microbench
```

## Roadmap

**v0.2 (post-launch hardening, 4&ndash;6 weeks)** &mdash; LongMemEval + LoCoMo grader runs, calibrated recall threshold cutoff, `privacy_intent` flags (consent / retention / share-scope), MCP working-group RFC, governance UI multi-tenant per-session agent scoping.

**v0.5 (Q3 2026)** &mdash; Spec frozen, IETF Internet-Draft submitted (`draft-<name>-memorywire-00`), cross-language ports begin (Rust / TypeScript), benchmark leaderboard.

**v1.0 (Q1 2027)** &mdash; Stable wire format, federated multi-tenant primitives, enterprise governance (SSO / RBAC), W3C Community Group.

Kill triggers and pivots: [`docs/kickoff/PROJECT-PLAN.md`](docs/kickoff/PROJECT-PLAN.md).

## Contributing

Spec edits, new adapters, and bug fixes welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`docs/adapters.md`](docs/adapters.md). Conventional Commits; one concern per PR.

Local dev:

```bash
uv venv && uv pip install -e ".[sqlite-vec,mem0,letta]"
uv pip install pytest pytest-asyncio pytest-cov ruff mypy
.venv/Scripts/python.exe -m pytest -m "not integration and not benchmark"
```

## License

- **Protocol + reference implementation:** [Apache-2.0](LICENSE)
- **Governance UI (`ui/`):** [Functional Source License 1.1](ui/LICENSE) &mdash; source-available; auto-converts to Apache-2.0 two years after each release

## Acknowledgments

Modelled on [MCP](https://modelcontextprotocol.io) (cross-vendor protocol shape), informed by the [LongMemEval](https://arxiv.org/abs/2410.10813), [LoCoMo](https://arxiv.org/abs/2402.17753), and Governed Memory papers, and by the published architecture writeups of mem0, Letta, Cognee, Zep/Graphiti.

The diff-and-approve workflow draws on the Co-memorize HITL pattern surfaced in the *Governed Memory* literature.

## Prior work and naming

This project was originally drafted as "AMP &mdash; Agent Memory Protocol" in May 2026. A prior project named AMP exists at [github.com/akshayaggarwal99/amp](https://github.com/akshayaggarwal99/amp) (an MCP-native memory server, created Dec 2025) &mdash; a different shape than this one. We renamed to `memorywire` before launch to avoid confusion. Full context: [`docs/PRIOR-WORK.md`](docs/PRIOR-WORK.md).

<sub>Made for the upcoming wave of agent-memory infrastructure. Honest about what it is: a wire format + reference + UI, not an algorithmic invention.</sub>
