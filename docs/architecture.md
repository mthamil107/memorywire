# memorywire Architecture Ã¢â‚¬â€ Figure 1

![memorywire architecture: client, orchestration, storage and governance layers](architecture.svg)

Vector source of truth: [`architecture.svg`](architecture.svg). Rasterised mirror for blog and social embeds: [`architecture.png`](architecture.png) (1200x675).

## What the diagram shows

The figure captures the full memorywire runtime in one frame. On the left, a client (the `amp.Memory` SDK or the `amp` CLI) issues one of the five spec operations Ã¢â‚¬â€ `remember`, `recall`, `forget`, `merge`, `expire`. The request lands on the `Memory` facade (`src/memorywire/api.py`), which validates against the JSON Schema 2020-12 operation files and hands off to the `MemoryRouter`. The router fans the operation across N backend adapters in parallel and, on `recall`, fuses their result sets via Reciprocal Rank Fusion (k=60) with an optional one-hop graph boost. Five adapters ship out of the box: `sqlite-vec`, `mem0`, `Letta`, `Cognee`, and `pgvector`. Each adapter advertises its capabilities set (semantic / episodic / vector / fts / graph / procedural / recall-tracking) so the router can skip stores that do not support a given operation. Procedural memory takes a side path: `type=procedural` writes are normalised into a pytransitions-compatible FSM blob and persisted via `sqlite-vec`. The STMÃ¢â€ â€LTM transformer is a separate async background task that scores short-term items and promotes or evicts them through the router.

## How to read the layers

The diagram is organised in four colour-coded layers from left to right and top to bottom: **client** (blue, request origin), **orchestration** (amber, the memorywire runtime itself), **storage** (green, the `MemoryStore` adapters), and **governance** (purple, the Pro-tier control plane). Solid edges are synchronous request flow; dashed edges are out-of-band Ã¢â‚¬â€ the STMÃ¢â€ â€LTM transformer's background promote/evict cycle and the governance interception path triggered by `approval_required`. Edge labels carry the operation type (`remember Ã‚Â· recall Ã‚Â· forget Ã‚Â· merge Ã‚Â· expire`, `fan-out Ã‚Â· recall`, `type=procedural`, `log op`) so the reader can trace any single call from client to backend without consulting the spec. The dashed amber box around the STMÃ¢â€ â€LTM transformer signals "not on the request path"; everything else inside the orchestration subgraph is on the hot path.

## Legend

| Colour | Layer | Components |
|---|---|---|
| Blue | Client | `Agent / SDK`, `amp CLI` |
| Amber | Orchestration | `Memory` facade, `MemoryRouter`, Procedural FSM backend, STMÃ¢â€ â€LTM transformer |
| Green | Storage (`MemoryStore` protocol) | `sqlite-vec`, `mem0`, `Letta`, `Cognee`, `pgvector` |
| Purple | Governance | Governance UI (Starlette + HTMX, FSL), append-only Audit log |

The Governance UI and the `sqlite-vec` adapter share the same SQLite database (shown as a long horizontal connector across layer boundaries); this is what lets reviewers diff a pending write against the live state without a separate sync channel. The Audit log is reached from every layer that mutates state Ã¢â‚¬â€ the facade, the router, and the FSM backend Ã¢â‚¬â€ and the UI both reads and exports it.

## For citing in paper

This figure is **Figure 1** of the memorywire technical paper. Suggested in-prose references:

- *"The full memorywire runtime is shown in Figure 1."*
- *"As illustrated in Figure 1, the `MemoryRouter` fans each operation across N adapters and fuses recall results via RRF (k=60) with an optional one-hop graph boost."*
- *"Figure 1 separates the four layers of the system Ã¢â‚¬â€ client, orchestration, storage, and governance Ã¢â‚¬â€ and shows the audit log as a sink reached from every mutating component."*

Suggested LaTeX caption (paste under an `\includegraphics{architecture.pdf}` or `architecture.png`):

> **Figure 1.** memorywire architecture. A client (SDK or CLI) issues one of the five spec operations against the `Memory` facade, which validates the request and delegates to the `MemoryRouter`. The router fans out across heterogeneous backend adapters (sqlite-vec, mem0, Letta, Cognee, pgvector) and fuses recall results with Reciprocal Rank Fusion (k=60) plus an optional one-hop graph boost. Procedural writes take a parallel FSM path. The STMÃ¢â€ â€LTM transformer runs as an async background task that promotes or evicts short-term items. An optional governance plane (UI + append-only audit log) intercepts writes that require human review and shares the SQLite database with the sqlite-vec adapter.

Citation handle for BibTeX (auto-derived from [`CITATION.cff`](../CITATION.cff) via `cffconvert --format bibtex`):

```
@software{amp_protocol,
  author = {M. Thamil},
  title  = {memorywire: A vendor-neutral wire format for agent memory operations},
  year   = {2026},
  url    = {https://github.com/mthamil107/memorywire}
}
```
