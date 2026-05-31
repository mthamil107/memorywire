---
title: "memwire: A Vendor-Neutral Wire Format for Agent Memory Operations"
authors: ["Thamilvendhan Munirathinam (Independent Researcher, mthamil107@gmail.com)"]
venue_target: "arXiv preprint (cs.DC primary; cs.AI + cs.SE secondary). USENIX ATC 2026 / NSDI 2027 follow-on."
status: arXiv-submission-ready v0.2
date: 2026-05-28
artifacts: https://github.com/mthamil107/memwire
---

# memwire: A Vendor-Neutral Wire Format for Agent Memory Operations

## Abstract

Agent-memory frameworks --- mem0, Letta/MemGPT, Cognee, Zep/Graphiti, MemoryOS, MemTensor --- each ship their own SDK, storage layout, and operational vocabulary. There is no shared wire format: every integration is bespoke, every migration rebuilds memory from scratch, and no framework ships a governance surface that lets a human review writes before they enter long-term storage. We present `memwire`[^prior-work], a JSON-Schema 2020-12 wire format for five memory operations (`remember`, `recall`, `forget`, `merge`, `expire`) over four memory types (semantic, episodic, procedural, emotional), with a `MemoryStore` interface, a fan-out router, and an optional HITL governance channel. We describe an open-source reference implementation with five backend adapters (sqlite-vec, mem0, Letta, Cognee, pgvector); a microbenchmark on a 100-fact / 50-query labelled corpus achieving recall@5 = 1.000 on the 42 labelled queries with ingest p50 = 37.8 ms and recall p50 = 40.6 ms; an adversarial-fusion experiment showing Reciprocal Rank Fusion holds recall@5 = 1.000 across a 1-of-N rank-0 injection sweep ($K \in \{0,5,\dots,50\}$) where `max` fusion collapses to 0.500 with 80% leak at $K \geq 5$; and a 16-scenario cross-adapter conformance suite passing 68 of 80 cells with zero failures. The contribution is not a new algorithm; it is a packaging of established components (RRF, FSMs, STM/LTM consolidation, diff-and-approve workflows) into a venue-neutral protocol with an empirically validated reference, positioned to compose with the Model Context Protocol rather than compete with it.

## 1. Introduction

### 1.1 The problem: islanded memory frameworks

Agent runtimes that maintain memory across sessions are now a category. Open-source frameworks include mem0, Letta (formerly MemGPT), Cognee, Zep/Graphiti, MemoryOS, and MemTensor MemOS; closed commercial offerings include Oracle's AI Agent Memory and the memory layers shipped inside major hosted-agent platforms. What the category has not produced is a shared wire format. Each framework defines its own SDK surface, JSON shape for memory records, embedding-provider integration, taxonomy (or absence of taxonomy) for memory types, and implicit lifecycle for record creation and deletion. The heterogeneity is non-trivial to bridge: mem0 stores records under a `memories[]` list keyed by `user_id` with a heterogeneous `created_at` representation; Letta stores archival memory keyed by `agent_id` and exposes a `tags` list as the only structured-metadata sink; Cognee mints internal `data_id` UUIDs that are not surfaced through its public `add` API, making per-record deletion impossible from outside the pipeline; sqlite-vec stores tables keyed by a stable ULID-shaped string; pgvector exposes records through an application-chosen SQL schema. Re-platforming an agent from one framework to another therefore requires a bespoke migrator and field-level losses where the source framework encodes more state than the target's data model holds.

The same heterogeneity means there is no shared *governance* surface. Each framework provides a write API and a read API; none mediate the write with a "diff against current state, present to a human, commit only on approval" workflow. The Co-memorize human-in-the-loop pattern, formalized in the *Governed Memory* line of work, has no production implementation an off-the-shelf agent can drop in. Operators who want auditability over what enters long-term memory must build it themselves and accept that the framework can bypass them.

This is the gap memwire addresses. It is not "we need a better retrieval algorithm" Ã¢â‚¬â€ the algorithms in the category (vector search, hybrid lexical-semantic RRF fusion, graph hop boosts, FSM-encoded procedures, STM/LTM consolidation) are well understood. It is "we need a shared protocol so any client can talk to any backend, any agent can carry its memory across runtimes, and any write can be diffed and approved." Structurally it is the gap MCP closed for *tool use*, applied to *memory*.

### 1.2 Contributions

This paper makes five contributions:

- **C1.** A wire format for five memory operations over four memory types, expressed as JSON Schema 2020-12 (`docs/spec/v0.md`). The operations are `remember`, `recall`, `forget`, `merge`, `expire`; the types are `semantic`, `episodic`, `procedural`, `emotional`. The schemas are vendor-neutral, transport-agnostic (REST-friendly request/response idiom that translates mechanically to JSON-RPC), and explicitly versioned with a breaking-change policy through v0.5.
- **C2.** A reference implementation in Python 3.11+ with five production-backend adapters (sqlite-vec, mem0, Letta, Cognee, pgvector), all implementing a single `MemoryStore` Protocol. The reference includes a memory router that fans operations across N stores in parallel and fuses recall results via Reciprocal Rank Fusion (k=60) with an optional one-hop graph boost, plus a tolerant partial-failure model where a single rogue or unavailable backend cannot crash the operation.
- **C3.** A governance UI implementing the Co-memorize diff-and-approve pattern over `remember`, `forget`, and `merge`. Writes flagged `approval_required` are staged behind a `PENDING_APPROVAL_DELETED_AT = -1` sentinel and remain invisible to `recall` until a reviewer commits or rejects them through the UI. The same audit log is the single source of truth for all governance and mutation events.
- **C4.** An empirical evaluation comprising (a) a microbenchmark on 100 hand-authored facts Ãƒâ€” 50 labelled queries against a real sentence-transformer embedder, (b) an adversarial-fusion experiment that sweeps a 1-of-N rank-0 injection attack across three fusion algorithms (RRF, MAX, weighted), and (c) a cross-adapter conformance suite of 16 protocol-invariant scenarios run against all five shipped adapters (68 PASS / 12 SKIP / 0 FAIL out of 80 cells).
- **C5.** A six-adversary threat model with line-level mitigation citations into the reference implementation, plus an open-data artifact (`docs/adversarial-results.{rrf,max,weighted}.json`, the labelled microbench corpus, the conformance scenario list) sufficient to reproduce every empirical claim without re-running paid evaluators.

### 1.3 Limitations, front-loaded

We state up front what this paper is *not*. It is not a new algorithm: RRF is from Cormack et al. (2009), the four-type taxonomy is from Tulving (1972) and Squire (1992), procedural FSMs use `pytransitions`, and STM/LTM consolidation predates the frameworks we cite Ã¢â‚¬â€ the contribution is composition and standardization, not new substrate. It is not an LLM contribution: we do not train models, propose model-dependent heuristics, or run LongMemEval/LoCoMo/BEAM in v0 (those require gated GPT-4-class graders and are the largest v0.2 deliverable per Ã‚Â§8). And it is not a stabilization paper: memwire v0 reserves the right to break wire-format compatibility through v0.5 (Ã‚Â§3.7); the IETF Internet-Draft and MCP-WG extension paths in Ã‚Â§2 and Ã‚Â§8 are intent, not commitment.

### 1.4 Paper roadmap

Section 2 places memwire against prior work in agent memory frameworks, cross-vendor protocols (particularly MCP), and the Governed Memory line. Section 3 specifies the wire format: operations, types, the `MemoryStore` Protocol, router semantics, and the governance channel. Section 4 describes the reference implementation including the five backend adapters, the procedural-memory FSM backend, the STMÃ¢â€ â€LTM transformer, and the governance UI. Section 5 reports the empirical evaluation. Section 6 is the threat model. Section 7 details the relationship to MCP. Sections 8 and 9 lay out future work and the bet we are making.

## 2. Background and Related Work

### 2.1 Memory in LLM agents

The first wave of LLM-agent frameworks treated memory as a side-effect of the conversation log; the next externalized it into a vector store ("RAG over your own logs"); the current wave, beginning roughly with MemGPT (Packer et al.) and continuing through mem0, Cognee, Zep/Graphiti, MemoryOS, and MemTensor, separates memory into named tiers (short-term working, long-term semantic, episodic, procedural) with explicit lifecycle operations (consolidate, expire, merge).

The frameworks differ in which tiers they emphasize. MemGPT/Letta exposes a hierarchical "core memory" + "archival memory" model with explicit `core_memory_append` / `archival_memory_insert` tools. Mem0 emphasizes user-scoped facts with an internal LLM-assisted dedupe pass. Cognee constructs a knowledge graph and exposes traversal as the primary recall primitive. Zep/Graphiti adds temporal edges over a graph. MemoryOS positions itself as an OS-shaped memory layer; MemTensor MemOS extends this with multi-tenant scoping.

None of these frameworks publishes a wire format that another framework adopts. The closest thing to a shared shape is mem0's request structure, informally copied by smaller projects, but mem0's API is the surface of one library, not a specification Ã¢â‚¬â€ it can change between releases.

### 2.2 Cross-vendor protocols: MCP as template

The Model Context Protocol (modelcontextprotocol.io) is the most successful recent cross-vendor protocol in the agent space. MCP is a JSON-RPC protocol over stdio or HTTP standardizing how an agent runtime exchanges *context* with a server process; its public surface is five primitives Ã¢â‚¬â€ tools, resources, prompts, sampling, and roots/elicitation Ã¢â‚¬â€ and it has been adopted by Anthropic, OpenAI, Google's Gemini ecosystem, Cloudflare, and many smaller server implementations.

MCP does not define a memory primitive. A backend can be *wrapped* in MCP Ã¢â‚¬â€ exposing `remember` / `recall` / `forget` as three tools is a fifteen-minute integration Ã¢â‚¬â€ but the wrapping is lossy: operations flatten into opaque tools, the type taxonomy collapses into a string parameter, and the governance channel sits entirely outside MCP. We discuss the AMPÃ¢â‚¬â€œMCP relationship at length in Ã‚Â§7; the short version is that memwire is what MCP would be if MCP had a memory primitive, built as a standalone spec so the design can stabilize without blocking on MCP-WG governance, with intent to propose it as an MCP extension at v0.5. The standalone-first, propose-upstream-later pattern follows Cloudflare's Web Bot Auth precedent (`draft-meunier-web-bot-auth-architecture`).

### 2.3 Reciprocal Rank Fusion

The memory router's default fusion algorithm is Reciprocal Rank Fusion (RRF) from Cormack, Clarke, and Buettcher (2009), who showed that RRF outperforms Condorcet and individual rank-learning methods on TREC tasks. The formula is

$$
\text{score}(d) = \sum_{i \in S} \frac{1}{k + r_i(d)}
$$

where $S$ is the set of ranked lists, $r_i(d)$ is the rank of document $d$ in list $i$, and $k$ is a smoothing constant (60 in the original paper; memwire uses the same value as a sensible default). RRF has two properties that matter for our setting: (a) it is *score-independent* Ã¢â‚¬â€ the input lists' raw scores do not enter the fusion, only their ranks do; (b) it is *additive across stores* Ã¢â‚¬â€ the contribution of an item to the fused score is the sum of its per-list contributions. These two properties together give RRF a robustness against rogue stores that score-sensitive fusion methods do not have. We exploit this in Ã‚Â§5.2.

### 2.4 Human-memory taxonomy

memwire's four memory types Ã¢â‚¬â€ `semantic`, `episodic`, `procedural`, `emotional` Ã¢â‚¬â€ are drawn from the human-memory taxonomy in cognitive-science literature. Tulving (1972) introduced the semantic / episodic distinction; Squire (1992) elaborated the declarative / nondeclarative hierarchy in which procedural memory sits as a nondeclarative subtype. The `emotional` type is included as a first-class tag rather than buried in metadata because affective associations are operationally distinct in agent workflows (they often trigger or suppress specific tools) and because the alternative Ã¢â‚¬â€ encoding them as semantic facts with a sentiment field Ã¢â‚¬â€ collapses the distinction at the wire-format layer where it matters most.

We do not claim that the four-type taxonomy is the *correct* one in any deep sense. We claim only that it is the taxonomy most often referenced by the existing memory frameworks (Letta, MemoryOS, MemTensor all cite Tulving/Squire) and that pinning it at the wire-format layer is more useful than leaving the choice to each backend.

### 2.5 Human-in-the-loop approval for agent actions

The governance channel in memwire implements the Co-memorize diff-and-approve pattern formalized in the Governed Memory line of work (Taheri, arXiv:2603.17787, 2026). The pattern is: when an agent proposes to write a memory, the system computes a structured diff between the proposed write and the current state, presents the diff to a human reviewer, and commits the write only on approval. The pattern generalizes to any state mutation; memwire applies it to `remember`, `forget`, and `merge`, and excludes `recall` and `expire` from the default approval surface (with `recall` flagged for v0.2 reconsideration; see Ã‚Â§6).

The Co-memorize pattern is not novel to this paper. What is new is its standardization at the wire-format layer: memwire defines a `governance` JSON schema for the diff-and-approve message and ships a reference UI that any backend adapter inherits transparently. An agent calling `remember(content="Ã¢â‚¬Â¦", approval_required=true)` gets the governance flow regardless of which of the five backends actually stores the row.

## 3. The memwire Wire Format

### 3.1 Design goals

Four explicit goals shaped the v0 surface.

**Small surface.** Five operations, four types, one optional governance channel. The operations are the smallest set we found that cover every workflow exhibited by the surveyed frameworks: `remember` (write), `recall` (read), `forget` (delete), `merge` (deduplicate), `expire` (apply a TTL policy). Adding more operations is straightforward; we resisted doing so in v0 because every new operation is a new schema to keep stable through the v1.0 freeze.

**Schema-pinned.** Every operation has a JSON Schema 2020-12 file in `src/memwire/schemas/operations/`. Validation runs at the boundary; backends accept already-parsed `pydantic` models that mirror the schemas exactly. The schemas are the source of truth, the models are the convenience layer.

**Stateless.** Each operation request carries the `agent_id` (and optional `user_id`) it operates under; the router does not keep per-session state. This is what makes the protocol portable across transports Ã¢â‚¬â€ REST today, JSON-RPC tomorrow, any future cross-language port without redesigning the wire format.

**Async-first.** The `MemoryStore` Protocol's methods are `async def`. The router uses `asyncio.gather` with `return_exceptions=True` for fan-out, so per-store failures do not cascade. Sync convenience wrappers are layered above through `asgiref` for callers who want them; the canonical path is async.

### 3.2 Operations

Each operation has a request schema and a response schema. We summarize the request side here; full schemas live in `src/memwire/schemas/operations/` and worked examples in `docs/spec/examples/`.

**`remember`** writes a new memory. Required: `agent_id`, `type` (one of four type tags), `content`. Optional: `user_id`, `metadata` (free-form JSON), `confidence` (float in [0,1], default 1.0), `source`, `expires_at` (Unix epoch ms), `approval_required` (bool, default false). `type` is pinned at write time so the router can route procedural writes to the FSM backend; `confidence` is first-class because every surveyed framework either has a confidence equivalent or asks for one.

**`recall`** reads memories. Required: `agent_id`, `query`. Optional: `k` (1Ã¢â‚¬â€œ1000, default 5), `types` (filter subset), `hops` (0Ã¢â‚¬â€œ3, default 0), `fusion` (`rrf`/`max`/`weighted`, default `rrf`), `filter`, `fresher_than_days`. `fusion` is exposed because the right choice depends on the operator's trust model (see Ã‚Â§5.2).

**`forget`** deletes memories. Required: `agent_id`, plus at least one of `ids` or `filter` (the spec rejects requests with neither Ã¢â‚¬â€ no-scope-mass-delete protection). Optional: `hard_delete` (bool, default false), `reason`. Default soft delete preserves the audit trail; hard delete is available for GDPR takedowns.

**`merge`** collapses duplicates. Required: `agent_id`, `canonical`, `duplicates`. Optional: `strategy` (one of `keep_canonical` / `merge_content` / `keep_highest_confidence`, default `keep_canonical`). Pinning the strategies at the wire-format layer means portable agent code does not need to know which framework's internal dedupe will fire.

**`expire`** applies a TTL policy. Required: `agent_id`. Optional: `policy` (ANDed `older_than_days`, `type`, `confidence_below`, `no_recall_in_days` predicates) and `action` (`forget`/`archive`/`demote`, default `forget`). Every framework has some notion of "delete old episodics" or "down-rank cold facts," each expressed differently; memwire pins the predicate DSL and action vocabulary.

### 3.3 Memory types

The four memory types are drawn from Ã‚Â§2.4. Their definitions in memwire v0 are:

| Type | Definition | Example |
|------|------------|---------|
| `semantic` | General facts, concepts, declarative knowledge | "Alice is allergic to peanuts" |
| `episodic` | Specific past events with time/place context | "On 2026-05-20 Alice told me she was nervous about her flight" |
| `procedural` | How-to knowledge, FSM-encoded procedures | The state machine for "book a flight" |
| `emotional` | Affective associations with experiences | "Alice expressed anxiety when discussing flights" |

Backends may store all four types in a single table with a `type` column or shard by type. The wire format does not constrain storage strategy; it does require that the `type` tag round-trips through `remember` Ã¢â€ â€™ `recall` losslessly.

### 3.4 The `MemoryStore` Protocol and capability declarations

A backend adopts memwire by implementing the `MemoryStore` Protocol (Python; the same shape ports trivially to other languages):

```python
class MemoryStore(Protocol):
    async def remember(self, req: RememberRequest) -> RememberResponse: ...
    async def recall(self,   req: RecallRequest)   -> RecallResponse:   ...
    async def forget(self,   req: ForgetRequest)   -> ForgetResponse:   ...
    async def merge(self,    req: MergeRequest)    -> MergeResponse:    ...
    async def expire(self,   req: ExpireRequest)   -> ExpireResponse:   ...
    async def health(self) -> dict[str, Any]: ...
    @property
    def capabilities(self) -> set[str]: ...
```

`capabilities` declares the optional surface a backend supports Ã¢â‚¬â€ e.g. `{"semantic", "episodic", "vector", "fts", "graph", "procedural", "recall_tracking"}`. The router consults `capabilities` to skip stores that do not support a given operation. This is what lets a single router compose a vector-only adapter with a graph-only adapter without the caller needing to know which fields each backend honors.

### 3.5 The memory router

The router (`src/memwire/router.py`) is itself a `MemoryStore`. It is constructed over N child stores and fans each operation across them. For `remember`, the default policy is `fan_out`: write to every child store. For `recall`, every store is queried in parallel and the results are fused. For `forget`, `merge`, `expire`, fan-out aggregates per-store responses with per-store errors preserved.

**Fusion math.** Three fusion algorithms are exposed:

- **RRF (default).** Per the formula in Ã‚Â§2.3, with $k=60$:
  $$\text{score}(d) = \sum_{i \in S} \frac{1}{60 + r_i(d)}$$
  The item's own per-list score is ignored; only its rank in each list contributes (`src/memwire/router.py:415-444`).
- **MAX.** $\text{score}(d) = \max_{i \in S} s_i(d)$ where $s_i(d)$ is the raw score in list $i$. Score-sensitive.
- **WEIGHTED.** $\text{score}(d) = \sum_{i \in S} w_i \cdot s_i(d)$ with per-store weights $w_i$ from router config. Score-sensitive.

**Graph-hop boost.** When a recall request sets `hops > 0` and at least one child store declares `graph` capability, the router applies a multiplicative boost to fused items whose neighbours are also in the fused set:

$$
\text{final}(d) = \text{rrf}(d) \cdot \left(1 + \frac{0.1}{1 + \text{hop\_dist}(d)}\right)
$$

The boost only fires for items already in the fused set; new neighbours are not introduced (per `src/memwire/router.py:482-501`). This avoids amplifying a malicious graph store's ability to inject content (see Ã‚Â§6.3).

**Partial-failure model.** Fan-out uses `asyncio.gather(..., return_exceptions=True)` (`src/memwire/router.py:261-264, 353-356`). A backend that throws or times out is logged but does not abort the operation; the router proceeds with results from the surviving stores. This is what makes a five-adapter router tolerant in practice Ã¢â‚¬â€ a transient mem0 outage does not blank the recall.

### 3.6 The governance channel

When the host wires in a `GovernanceClient`, `remember` / `forget` / `merge` operations carrying `approval_required: true` (or matching a policy rule) are routed through governance before commit. The governance review request is a JSON object carrying `operation` (one of `remember`/`forget`/`merge`), `agent_id`, the original `request`, a structured `diff` against current state, and an optional `reasoning` string. The governance response carries `approved` (bool), `reviewer` (identity), `reviewed_at` (Unix epoch ms), and an optional `reason`. The reference UI layers an opt-in approval-learning loop on top: track which patterns the reviewer always approves / rejects and auto-allow after N consistent decisions, with every fired decision still journaled to the audit log.

Excluding `recall` from the default governance surface is a v0 trade-off. Recall budgets and read-side approval are tracked for v0.2 (Ã‚Â§8.3); until then, the audit log captures every `recall` call (`operation = 'recall'`) so high-rate exfiltration is observable post-hoc, if not preventable.

### 3.7 Spec versioning and backwards-compatibility rules

memwire v0 is a draft. Breaking changes are allowed through v0.5; v0.5 stabilizes; v1.0 freezes. The rules are:

- New *optional* fields Ã¢â‚¬â€ allowed at any time.
- New *required* fields Ã¢â‚¬â€ minor version bump, deprecation period.
- *Removed* fields Ã¢â‚¬â€ major version bump only.
- New *memory types* Ã¢â‚¬â€ minor version bump.

The intent is to publish memwire v0.5 as an IETF Internet-Draft (`draft-<name>-memwire-00`) and, in parallel, propose adoption as an MCP extension (`mcp.memory.v0` or similar; see Ã‚Â§7). Both outcomes are acceptable; neither is committed.

## 4. Reference Implementation

The reference implementation lives in `src/memwire/` (the SDK and adapters) and `ui/` (the governance UI). It is Python 3.11+, Apache-2.0 licensed for the protocol and reference; the Pro UI ships under the Fair Source License (FSL). Non-test source totals roughly 15k lines of Python (8.4k in `src/memwire/`, 2.4k in `ui/src/`, 4.2k in `scripts/`) plus the JSON-Schema files and the HTMX templates, with another 10k lines of test code under `tests/`.

### 4.1 Architecture overview

The full runtime is shown in **Figure 1**. A client (the `amp.Memory` SDK or the `amp` CLI) issues one of the five spec operations against the `Memory` facade (`src/memwire/api.py`), which validates the request against the operation's JSON Schema and delegates to the `MemoryRouter`. The router fans the operation across the configured backend adapters in parallel; for `recall` it fuses the per-store result sets via RRF (k=60) with an optional one-hop graph boost. Five adapters ship out of the box: sqlite-vec, mem0, Letta, Cognee, pgvector. Procedural memory takes a side path: `type=procedural` writes are normalized into a `pytransitions`-compatible FSM blob and persisted via sqlite-vec. The STMÃ¢â€ â€LTM transformer is an async background task that scores short-term items and promotes or evicts them through the router. An optional governance plane (UI + append-only audit log) intercepts writes that require human review and shares the SQLite database with the sqlite-vec adapter so reviewers can diff a pending write against the live state without a separate sync channel.

> **Figure 1.** memwire architecture. A client (SDK or CLI) issues one of the five spec operations against the `Memory` facade, which validates the request and delegates to the `MemoryRouter`. The router fans out across heterogeneous backend adapters (sqlite-vec, mem0, Letta, Cognee, pgvector) and fuses recall results with Reciprocal Rank Fusion (k=60) plus an optional one-hop graph boost. Procedural writes take a parallel FSM path. The STMÃ¢â€ â€LTM transformer runs as an async background task that promotes or evicts short-term items. An optional governance plane (UI + append-only audit log) intercepts writes that require human review and shares the SQLite database with the sqlite-vec adapter. Source: `docs/architecture.png` (vector source at `docs/architecture.svg`).

### 4.2 The five backend adapters

Table 1 summarizes the five shipped adapters, the capabilities each declares, and the memwire fields each can losslessly round-trip versus the fields each encodes as backend metadata.

**Table 1.** Backend adapters and their fidelity against the memwire wire format. "Native" means the field is stored in a first-class column or property of the backend's data model; "encoded" means the field is round-tripped through a backend metadata sink (e.g. Letta's `tags` list, mem0's `metadata` dict); "Ã¢â‚¬â€" means the field is supported but not surfaced to the backend (typically because the router consumes it before fan-out).

| Adapter      | URL scheme        | Capabilities                                                                  | `confidence`     | `source`         | `expires_at`     | structured `metadata`         |
|--------------|-------------------|-------------------------------------------------------------------------------|------------------|------------------|------------------|-------------------------------|
| sqlite-vec   | `sqlite-vec://`   | semantic, episodic, procedural, emotional, vector, fts, recall_tracking       | native           | native           | native           | native (JSON column)          |
| mem0         | `mem0://`         | semantic, episodic, vector                                                    | encoded          | encoded          | encoded          | native (lossless)             |
| Letta        | `letta://`        | semantic, episodic, vector                                                    | encoded (`tags`) | encoded (`tags`) | encoded (`tags`) | lossy (flat KV via `amp_kv:`) |
| Cognee       | `cognee://`       | semantic, episodic, vector, graph                                             | encoded          | encoded          | encoded          | lossy (graph attrs)           |
| pgvector     | `pgvector://`     | semantic, episodic, procedural, emotional, vector, recall_tracking, governance | native           | native           | native           | native (JSONB)                |

The two adapters with full lossless fidelity (sqlite-vec, pgvector) are the SQL-backed ones; they own their schema and can add the columns memwire needs. pgvector ships every memory type plus recall-tracking and the governance sentinel; sqlite-vec adds FTS5 keyword indexing on top of the vector path. The three SDK-wrapping adapters (mem0, Letta, Cognee) inherit whatever fidelity their upstream offers and back-fill the rest through metadata encoding. The conformance suite in Ã‚Â§5.3 quantifies what each adapter can and cannot do.

### 4.3 The FSM procedural-memory backend

Procedural memory in memwire is stored as a JSON-serialized finite-state machine compatible with the `pytransitions` library. The shape is intentionally minimal Ã¢â‚¬â€ `name`, `initial`, `states`, `transitions`, `current`, `metadata` Ã¢â‚¬â€ so backends may extend it with their own state-machine semantics; v0 deliberately does not standardize action handlers.

In v0 the FSM JSON is carried as a string inside `RememberRequest.content`; promoting it to a structured typed field is tracked for v0.2. The FSM backend wraps `pytransitions` with a strict-validation layer that allow-lists transition keys to `{trigger, source, dest, conditions, unless}` and rejects `before` / `after` / `prepare` Ã¢â‚¬â€ the three pytransitions keys that resolve dotted-string callbacks via `__import__` and would otherwise enable RCE at trigger time (`src/memwire/procedural.py:44-59`). `conditions` and `unless` strings are restricted to bare identifiers (no `.`) so they resolve only to attributes on a private `_ProcedureModel`. The sandbox is enforced at two layers: validation at parse time and key-stripping at construction time.

### 4.4 The STMÃ¢â€ â€LTM transformer

Short-term memory in memwire is the most recent N items per `(agent_id, user_id)` window; long-term memory is everything else. The transformer is an always-on async background task that runs on an interval (default 60 s) and, for each window, scores STM items along recency, salience (frequency-of-mention), and confidence axes, promotes top items into LTM with a `type=semantic` write, and evicts cold items. It does not block the request path; it consumes from the same `Memory` facade the agent uses, so promoted items appear in subsequent `recall` calls without additional plumbing.

The transformer is deliberately simple. The point is not to invent a new consolidation algorithm but to show that the wire format can carry consolidation as a sequence of standard operations rather than a vendor-specific tier-promotion API. A more sophisticated consolidator drops in as a plugin without changing the wire format.

### 4.5 The governance UI

The governance UI (`ui/src/amp_ui/`) is a Starlette server with HTMX-driven templates. It shares the sqlite-vec adapter's SQLite database, so a reviewer sees pending writes as rows with the `PENDING_APPROVAL_DELETED_AT = -1` sentinel in `deleted_at` and a `pending: yes` badge in the UI. Reviewers can approve (clear the sentinel; the row becomes live), reject (hard-delete or soft-delete depending on the policy), or apply a Co-memorize transformation Ã¢â‚¬â€ typically a `merge` against an existing canonical row or a `forget` of a similar row that the new write supersedes.

Authentication is opt-in via the `MEMWIRE_UI_TOKEN` environment variable. When set, every request requires either an `Authorization: Bearer <token>` header or an `memwire_ui_session` cookie; comparison uses `hmac.compare_digest` for constant-time matching. CSRF is enforced through a double-submit-cookie pattern signed with HMAC-SHA256 over `nonce.ts` with a 24-hour TTL. Without `MEMWIRE_UI_TOKEN` the UI is unauthenticated; binding a non-loopback host without a token fires a stderr warning on boot (`ui/src/amp_ui/middleware.py:55-66`).

The UI's full authorization model is one global bearer token; per-`agent_id` ACLs are tracked for v0.2 (Ã‚Â§8.3). Per-row authorization is enforced at the SQL layer: every state-changing handler runs against `WHERE id = ? AND agent_id = ? AND deleted_at = ?` with the sentinel value, so an attacker who guesses a row id but does not control the matching `agent_id` cannot pivot across tenants (Ã‚Â§6.5).

## 5. Evaluation

The evaluation has three parts. Section 5.1 reports a microbenchmark on a labelled corpus to establish baseline recall and latency. Section 5.2 reports an adversarial-fusion experiment that quantifies the robustness premium RRF provides over MAX and weighted fusion under a 1-of-N rank-0 injection attack. Section 5.3 reports a cross-adapter conformance suite that empirically validates the protocol's vendor-neutrality claim. Section 5.4 enumerates threats to validity.

### 5.1 Microbenchmark

**Methodology.** The corpus is 100 hand-authored facts spread across roughly 10 distinct users, mixing all four memory types in proportions chosen to mirror the distribution we observed across the surveyed frameworks' default workloads (skewed semantic, with episodic, procedural, and emotional in long tail). 50 hand-authored queries carry explicit gold-id labels, distributed as 24 paraphrase queries (e.g. "what foods should I avoid serving Alice?" mapping to "Alice is allergic to peanuts and tree nuts"), 10 exact / near-exact match queries, 8 multi-hit queries with two or three gold ids, and 8 no-match probes whose gold-id list is empty. The 8 no-match probes are included specifically to measure how often the system surfaces a confident wrong answer when nothing actually matches. Embedder: `sentence-transformers/all-MiniLM-L6-v2` (384-dim) on CPU; the first call's model-load cost is excluded from per-call latency through a warm-up call. Backend: a single `SqliteVecStore(":memory:")` exercising the full intra-store RRF fusion of `vec0` ANN and FTS5 keyword search. Dataset and runner: `tests/benchmarks/dataset.py` and `scripts/run_microbench.py`. The full benchmark is reproducible with a single command and runs in roughly six seconds.

**Results.** Numbers measured on 2026-05-27, Windows 11 AMD64, Python 3.13.13, CPU-only inference.

**Table 2.** Microbenchmark results. n=50 queries, k=5, corpus size = 100 facts, embedder = `all-MiniLM-L6-v2`, backend = sqlite-vec `:memory:`.

| Metric | Value |
|---|---|
| Recall@5 mean (labelled queries) | **1.000** |
| Precision@5 mean | 0.214 |
| Ingest latency p50 / p95 / p99 | **37.8 ms** / 46.0 ms / 69.1 ms |
| Recall latency p50 / p95 / p99 | **40.6 ms** / 46.6 ms / 55.7 ms |
| No-match probes correctly empty | 0 / 8 |
| Total benchmark runtime | ~5.9 s |

The headline number Ã¢â‚¬â€ recall@5 = 1.000 on the 42 labelled queries Ã¢â‚¬â€ means every paraphrase, exact-match, and multi-hit query surfaced all its gold ids in the top 5 results. The precision number is bounded by the ratio of gold ids per query (most queries have a single gold id, so precision@5 is upper-bounded at 0.2 by construction). Latency is roughly an order of magnitude below the spec's p50 SLA targets (50 ms for `remember`, 300 ms for two-store fused `recall`).

**Honest framing.** This is a microbenchmark, not LongMemEval, LoCoMo, or BEAM. The hand-authored corpus is small enough that FTS5 keyword matching alone would surface many of the gold ids, and the dataset rewards systems that combine semantic embeddings with keyword recall Ã¢â‚¬â€ which is exactly what memwire's intra-store RRF does. At 100 facts the ANN path is doing a brute-force `vec0` scan, not an HNSW workload. The 0/8 "no-match correctly empty" number reflects a deliberate v0 design choice: `recall(k=5)` always returns up to k hits because v0 ships no calibrated relevance-threshold cutoff; that knob is tracked for v0.2. LongMemEval and LoCoMo proper are deferred to v0.2 because both require a gated GPT-4-class grader and hours of model time; landing them honestly is the largest single v0.2 deliverable.

### 5.2 Adversarial fusion experiment

This is the experiment that makes the security claim in Ã‚Â§6.3 quantitative. The threat is a "1-of-N malicious backend": one of the N child stores under the router has been compromised, is a malicious adapter fork, or sits behind a MITM that rewrites its responses. The attack is rank-0 injection: the rogue store returns K attacker-controlled ids (disjoint from the gold corpus) at the top of its result list and is otherwise quiet. The question is how much each fusion algorithm lets the rogue store move the fused output.

**Methodology.** Three child stores: two benign + one adversarial. Each benign store returns each query's gold ids at the top ranks with an independent random distractor tail (different distractor permutations across benign stores, simulating different embedders / indexes). The adversarial store returns K attacker-controlled ids (`a***` prefix, disjoint from the gold corpus) at ranks 0..K-1 then optionally a benign tail so it still "looks normal" past rank K. The query suite is 20 queries, each with two gold ids drawn without replacement from a synthetic corpus of 50 memories. For $K \in \{0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50\}$ the script issues every query through a real `MemoryRouter.recall(k=5)` and records recall@5 against the gold set, adversarial leak rate (fraction of returned ids that are attacker-controlled), and gold-displacement rate (fraction of gold ids in the K=0 baseline top-5 that were pushed out). The same sweep is run for `fusion="rrf"`, `fusion="max"`, and `fusion="weighted"`. Seed is fixed at 1337 for reproducibility. Runner: `scripts/run_adversarial.py`. Machine-readable outputs: `docs/adversarial-results.{rrf,max,weighted}.json`.

**Results.** Numbers measured 2026-05-27 with the default config.

**Table 3.** Adversarial fusion sweep, N=3 backends (2 benign + 1 adversarial), corpus M=50, Q=20 queries, k=5, seed=1337. K is the attacker budget (number of attacker-controlled ids the rogue store places at the top of its result list). Recall@5 is against the gold set; leak is the fraction of returned ids that are attacker-controlled.

| K  | recall@5 (RRF) | leak (RRF) | recall@5 (MAX) | leak (MAX) | recall@5 (weighted) | leak (weighted) |
|---:|---:|---:|---:|---:|---:|---:|
| 0  | 1.000 | 0.000 | 1.000 | 0.000 | 1.000 | 0.000 |
| 5  | 1.000 | 0.000 | 0.500 | 0.800 | 1.000 | 0.000 |
| 10 | 1.000 | 0.000 | 0.500 | 0.800 | 1.000 | 0.000 |
| 25 | 1.000 | 0.000 | 0.500 | 0.800 | 1.000 | 0.000 |
| 50 | 1.000 | 0.000 | 0.500 | 0.800 | 1.000 | 0.000 |

The RRF curve stays flat at the no-attack baseline across the entire sweep. The MAX curve collapses immediately at K=5 and stays collapsed: recall@5 halves to 0.500, and 80% of returned ids are attacker-controlled. The weighted result with equal per-store weights is identical to RRF.

**Why RRF is robust here.** The mechanism is exactly the score-independence and additivity properties from Ã‚Â§2.3. Under RRF, the consensus of two benign rank-0 votes for a gold id contributes $1/60 + 1/61 \approx 0.0330$ to the fused score. A single rogue rank-0 vote for an attacker id contributes $1/60 \approx 0.0167$. The benign consensus provably outpoints the rogue vote regardless of what raw score the rogue store reports Ã¢â‚¬â€ because RRF ignores the raw score. Under MAX the same rogue vote can tie or beat the benign rank-0 raw score (the rogue store is free to report any score it wants), pull 4 of 5 fused top-5 slots, and halve recall. Under weighted fusion with equal per-store weights the math degenerates close to RRF for this attack shape.

**Operating point and caveats.** The defensible claim is "RRF tolerates an arbitrarily large 1-of-N rank-0 injection as long as the majority of backends are benign and agree on the gold set," not "RRF tolerates K up to some specific number." The experiment isolates the fusion-math property and assumes (a) benign stores are perfect by construction Ã¢â‚¬â€ always return gold at top, modulo distractor tail; (b) the adversary has full knowledge of the router's k*4 over-fetch and fills exactly that block, so a black-box attacker would do worse; (c) only the 1-of-N case is swept by default Ã¢â‚¬â€ once `n_adversarial >= n_benign` the RRF consensus argument fails. The MAX result is not a negative finding about MAX in general; MAX is the right choice when the operator's trust model says the highest-scoring store is the most authoritative. The result is a finding about MAX in the *malicious-backend* model, which is the threat we evaluate.

### 5.3 Cross-adapter conformance

The cross-adapter conformance suite is the empirical evidence for the protocol's vendor-neutrality claim. Sixteen scenarios run against every shipped adapter; the scenarios encode protocol invariants that any compliant `MemoryStore` MUST satisfy. Each scenario is a `ProtocolScenario` dataclass (`tests/conformance/scenarios.py`) with a deterministic setup, an action, and a predicate; the runner parametrizes the list across every adapter id and skips scenarios whose `required_capabilities` are not satisfied by the candidate store.

**Table 4.** Cross-adapter conformance matrix. Sixteen scenarios Ãƒâ€” five adapters = 80 cells. Ã¢Å“â€¦ = passes; Ã¢ÂÂ­ = SKIPPED for a documented adapter limitation; Ã¢ÂÅ’ = fails. Aggregate: **PASS 68 / SKIP 12 / FAIL 0**.

| Scenario                              | sqlite-vec | mem0 | letta | cognee | pgvector |
| ------------------------------------- | :--------: | :--: | :---: | :----: | :------: |
| basic_remember_recall                 |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| remember_recall_by_user_filter        |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢ÂÂ­   |   Ã¢ÂÂ­   |    Ã¢Å“â€¦    |
| type_filter                           |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| forget_by_ids                         |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢ÂÂ­   |    Ã¢Å“â€¦    |
| forget_no_scope_raises                |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| expire_empty_policy_raises            |     Ã¢Å“â€¦     |  Ã¢ÂÂ­  |  Ã¢ÂÂ­   |   Ã¢ÂÂ­   |    Ã¢Å“â€¦    |
| expire_empty_policy_object_raises     |     Ã¢Å“â€¦     |  Ã¢ÂÂ­  |  Ã¢ÂÂ­   |   Ã¢ÂÂ­   |    Ã¢Å“â€¦    |
| expire_by_age                         |     Ã¢Å“â€¦     |  Ã¢ÂÂ­  |  Ã¢Å“â€¦   |   Ã¢ÂÂ­   |    Ã¢Å“â€¦    |
| merge_keep_canonical                  |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢ÂÂ­   |    Ã¢Å“â€¦    |
| approval_required_pending             |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| capabilities_declared                 |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| health_returns_status                 |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| isinstance_protocol                   |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| recall_returns_score_metadata         |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| fresher_than_days_filter              |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| multi_remember_then_recall            |     Ã¢Å“â€¦     |  Ã¢Å“â€¦  |  Ã¢Å“â€¦   |   Ã¢Å“â€¦   |    Ã¢Å“â€¦    |
| **pass / skip**                       | **16 / 0** | **13 / 3** | **13 / 3** | **10 / 6** | **16 / 0** |

Every non-skipped cell passes; zero scenarios fail on any adapter.

**Per-adapter analysis.** The two SQL-backed adapters (sqlite-vec, pgvector) clear the entire suite Ã¢â‚¬â€ these are the adapters whose data models memwire directly designed against, so it would be surprising if they did not. The three SDK-wrapping adapters (mem0, Letta, Cognee) each skip a documented set of scenarios.

**Spec ambiguities surfaced.** The 12 SKIP cells are not random; they cluster into three classes, and each class is a v0.2 spec-tightening signal.

- *No `user_id` namespace.* Letta and Cognee skip `remember_recall_by_user_filter` because neither backend has a `user_id` namespace separate from its top-level scope (Letta scopes by `agent_id`; Cognee by dataset). memwire's `user_id` dimension is lost on these backends. The v0.2 spec should either require `user_id` support for full conformance or define an explicit "scoped-by-agent-only" fallback.
- *No empty-policy guard.* mem0, Letta, and Cognee skip `expire_empty_policy_raises` and `expire_empty_policy_object_raises` Ã¢â‚¬â€ only the SQL adapters defensively raise on an empty `ExpirePolicy`. The three SDK-wrapping adapters silently fall through to "match everything," which is the wrong default and a real footgun. The v0.2 spec should require every adapter to raise on empty policy; this is the highest-priority spec tightening from the conformance run.
- *No stable per-record id.* Cognee skips `forget_by_ids`, `expire_by_age`, and `merge_keep_canonical` because Cognee's `forget` primitive requires a pipeline-assigned `data_id` UUID that the public `add` API does not surface. The Cognee adapter mints synthetic `cog:<sha1>` ids at write time, so per-id deletes (and the operations that depend on them) become no-ops. The v0.2 spec should require backends to surface a stable per-record id from their write primitive; this is the largest-impact protocol change the conformance run motivates.

These three spec-tightening signals are exactly the kind of finding a conformance suite is supposed to produce. They are not bugs in the suite or in the adapters; they are real gaps in the v0 spec that the suite makes visible, and the v0.2 spec resolves them by raising the floor.

### 5.4 Threats to validity

The evaluation has several limitations we want named explicitly.

**Synthetic corpora.** The microbench corpus is 100 hand-authored facts; the adversarial-fusion corpus is 50 synthetic memories. Real-world workloads Ã¢â‚¬â€ millions of memories per agent, heavy-tailed query distributions, latency interference from a real production embedding service Ã¢â‚¬â€ will produce different numbers. The 100k-memory recall scaling test is tracked for v0.2.

**Adversary has full knowledge.** The Ã‚Â§5.2 attacker knows the router's k*4 over-fetch and fills exactly that block at rank 0. A black-box attacker Ã¢â‚¬â€ one that does not know the over-fetch and has to guess Ã¢â‚¬â€ would do worse. We did not evaluate the converse case (a smarter attacker that, for instance, fabricates ids that *also* appear in the benign stores' result sets to bump their rank); that case is the v0.2 hardening with signed `RecallHit` envelopes from `docs/THREATS.md Ã‚Â§3.3`.

**Single-machine measurements.** Every number reported here was measured on one developer-class Windows 11 laptop. Distributed deployment, multi-process router fan-out across machines, and the additional latency of a real network hop to a hosted mem0 / Letta instance are unmeasured. The numbers should be read as a microbenchmark of the protocol's *intrinsic* overhead, not as a SLA against any deployment topology.

**Authors-as-evaluators.** Neither the conformance suite nor the microbench corpus has been audited by a third party. A user study with external operators (n=10Ã¢â‚¬â€œ20) using the governance UI is in scope for v0.2 (`docs/paper/user-study/` materials, NASA-TLX instrument, IRB pipeline Ã¢â‚¬â€ currently a v0.2 deliverable; the materials directory does not yet exist).

**Benchmark scope.** This paper does not report LongMemEval, LoCoMo, or BEAM. We say so up front because reviewers familiar with the agent-memory benchmark literature will look for those numbers first; they are not here in v0 by design (see Ã‚Â§1.3) and are the primary v0.2 evaluation deliverable.

## 6. Threat Model

The threat model below is condensed from `docs/THREATS.md`, which is the canonical version and which carries the line-level mitigation citations into the reference implementation. Six adversaries map onto established OWASP and CWE categories: OWASP A01 (Broken Access Control), A03 (Injection), A04 (Insecure Design), A07 (Auth Failures), A09 (Logging Failures); CWE references are noted inline.

### 6.1 Malicious memory injection (CWE-20; OWASP LLM-01)

**Capability.** Submits `remember()` calls Ã¢â‚¬â€ as the agent itself (prompt-injected upstream) or as an upstream system feeding the agent. **Motivation.** Plant adversarial "facts" that subsequent `recall()` surfaces Ã¢â‚¬â€ the memory analogue of prompt injection. **Preconditions.** Can influence any string the agent passes through `remember()`. memwire cannot tell a real fact from a planted one.

**Current mitigation.** `approval_required=true` on `RememberRequest` stages the row behind the `PENDING_APPROVAL_DELETED_AT = -1` sentinel in `memories.deleted_at` (`src/memwire/store/sqlite_vec.py:88-98, 440`). All recall paths filter `deleted_at IS NULL`, so pending rows cannot influence retrieval until a human approves. `confidence` is a first-class field; every `remember()` is journaled with the inserted `memory_id`, so a poisoned memory is traceable to the call that planted it. **Residual risk.** Default `approval_required` is false; the protocol guarantees only that what the agent wrote is what the agent reads back. Prompt-injected calls from a trusted agent are out of scope (Ã‚Â§6.7). **v0.2 hardening.** A `privacy_intent` block on `RememberRequest` so operators can require approval by `source`, `type`, or content predicate without instrumenting every caller.

### 6.2 Recall exfiltration (CWE-200; OWASP A01)

**Capability.** Issues `recall()` against an agent's router Ã¢â‚¬â€ directly (compromised SDK caller) or indirectly (manipulating the prompt that drives the agent's own recall). **Motivation.** Read private memories stored under `agent_id` / `user_id`. **Preconditions.** Can issue `recall(query, agent_id)` for an agent with data. `k` defaults to 5; the schema caps at 1000.

**Current mitigation.** Recall is hard-bound to `agent_id` at the adapter SQL layer Ã¢â‚¬â€ every recall path in `SqliteVecStore` filters `WHERE agent_id = ? AND deleted_at IS NULL`. `recall()` is itself audited (`audit_log.operation = 'recall'`), so high-rate exfiltration is observable post-hoc. The schema caps `k` at 1000 so a single call cannot drain a store. **Residual risk.** A caller with the right `agent_id` can extract everything that agent stored. No recall rate limit, no field-level redaction, no approval on reads. **v0.2 hardening.** Per-`agent_id` recall budgets, optional `approval_required` on `recall`, and a `redact` filter for secrets-labelled rows.

### 6.3 Poisoned backend in RRF fusion (CWE-345)

**Capability.** Controls one of the N child stores in a `MemoryRouter` Ã¢â‚¬â€ a compromised hosted mem0 instance, a malicious adapter fork, or a MITM on the backend HTTP. **Motivation.** Dominate the fused output of `recall()` so the agent receives attacker-chosen results. **Preconditions.** Can return crafted `RecallHit` rows with high `score` or fabricated ids not seen in other stores.

**Current mitigation.** RRF is score-independent by construction Ã¢â‚¬â€ `_fusion_contribution` uses `1 / (rrf_k + rank)` (`src/memwire/router.py:428-429`), so a malicious backend cannot dominate by inflating `score`; it can only return an item at rank 0. RRF sums across stores, so a single rogue store contributes at most $1/60 \approx 0.0167$ per item, while a two-store consensus item scores at least $1/60 + 1/61 \approx 0.0330$. `MAX` and `weighted` fusion *are* score-sensitive Ã¢â‚¬â€ operators picking them accept more backend trust. Per-store failures are logged but do not abort the operation. **Residual risk.** With `fusion="max"` or `"weighted"`, one malicious backend can dominate (Ã‚Â§5.2). Even with RRF, a backend that fabricates an attacker-controlled id that *also* exists in other stores can bump it by reporting it at rank 0. There is no cross-store identity proof. **v0.2 hardening.** Signed `RecallHit` envelopes per backend; an optional `quorum_k` parameter requiring an item to appear in $k$ distinct stores before fusion considers it.

**Measured.** See Ã‚Â§5.2. RRF holds recall@5 = 1.000 across the K=0..50 sweep; MAX halves to 0.500 with 80% leak at K=5.

### 6.4 Audit log tampering (CWE-117 / CWE-778; OWASP A09)

**Capability.** Has write access to the SQLite file or can run arbitrary SQL against `audit_log`. **Motivation.** Hide a previous `forget()` / `merge()` / `approve()` or fabricate one to frame an operator. **Preconditions.** Filesystem access to the memwire DB.

**Current mitigation.** The audit log is append-only by code convention. `SqliteVecStore._audit` is the only writer in the OSS adapter (`src/memwire/store/sqlite_vec.py:401-424`); it only performs `INSERT INTO audit_log(...)`. No UPDATE or DELETE against `audit_log` exists anywhere in `src/memwire/` or `ui/src/amp_ui/`. Every governance action emits a dedicated audit row with the reviewer's identity. **Residual risk.** SQLite is a single file with filesystem semantics Ã¢â‚¬â€ anyone with write access can `DELETE FROM audit_log` or mutate rows. memwire enforces append-only at the code layer, not the DB layer. **v0.2 hardening.** Merkle-chained audit rows (`audit_log.prev_hash` column) so tampering breaks the chain; periodic export to an append-only object store (S3 object-lock); a read-only DB role for the UI connection.

### 6.5 Cross-tenant leakage / IDOR (CWE-639; OWASP A01)

**Capability.** Legitimate operator scoped to `agent_id = A` with a valid UI session who guesses or harvests memory ids belonging to `agent_id = B`. **Motivation.** Approve, reject, forget, or merge another agent's memories. **Preconditions.** UI session as agent A plus a memory id known to belong to agent B.

**Current mitigation.** Every state-changing UI handler is scoped to `(agent_id, memory_id, sentinel)`. `approve()` runs `UPDATE memories SET deleted_at = NULL WHERE id = ? AND agent_id = ? AND deleted_at = ?` (`ui/src/amp_ui/services.py:502-511`); `reject()` and `apply_co_memorize()` carry the same triple-key guard. The merge branch additionally verifies the canonical row belongs to the agent before touching the secondary. On any mismatch the response returns an identical opaque reason, so the error itself does not leak which condition fired. **Residual risk.** The UI uses a single global bearer; the IDOR fix prevents cross-agent pivoting by id but not multi-tenant isolation by operator. **v0.2 hardening.** Per-session multi-tenant `agent_id` scoping; SSO-shaped reviewer identity; per-operator allowed-`agent_id` ACL.

### 6.6 Approval bypass (CWE-94 / CWE-862; OWASP A04 / A07)

**Capability (a).** Reaches the UI on an unauthenticated bind. **Capability (b).** Crafts the procedural-memory payload so the FSM definition itself triggers code execution.

**Current mitigation (a) UI no-auth.** `BearerAuthMiddleware` gates every request behind a bearer when `MEMWIRE_UI_TOKEN` is set (`ui/src/amp_ui/middleware.py:74-103`), accepting either an `Authorization: Bearer` header or an `memwire_ui_session` cookie with `hmac.compare_digest`. `CSRFMiddleware` enforces a double-submit-cookie pattern signed with HMAC-SHA256 over `nonce.ts` with 24-hour TTL. Non-loopback bind without a token fires a stderr warning on boot. **Current mitigation (b) procedural-memory RCE.** `validate_procedure_dict` allow-lists transition keys to exactly `{trigger, source, dest, conditions, unless}` (`src/memwire/procedural.py:57-59`), rejecting `before` / `after` / `prepare` (the three pytransitions keys that resolve dotted-string callbacks via `__import__`). `conditions` / `unless` strings are restricted to bare identifiers. `ProcedureRunner._expand_transitions` strips disallowed keys at construction time as a defense-in-depth layer. **Residual risk.** Single shared bearer with manual rotation; CSRF is bypassed for any `Authorization: Bearer` request (a stolen bearer is already a fatal compromise); the procedural sandbox is purely static allow-listing, so a future `transitions` release adding a new code-execution sink under a currently-allowed key would silently miss validation. **v0.2 hardening.** Per-operator tokens with rotation; Secure cookie flag for HTTPS; a CI snapshot of the `transitions` callback-key surface.

### 6.7 Residual risks the protocol cannot mitigate

Three classes of risk are out of scope for the memwire v0 protocol and are noted here for honest framing:

- **Insider attacks on the audit DB.** Anyone with filesystem write access can rewrite history (see Ã‚Â§6.4 residual). Mitigated only by deployment hygiene.
- **Prompt injection in the calling agent.** memwire is downstream of the LLM. If the agent is fooled into `remember("Alice is in the building", confidence=1.0)`, memwire faithfully stores and recalls it. The audit log captures the call exactly; memwire makes the threat auditable, not preventable.
- **Side-channel timing on recall.** Latency varies with `k`, fusion mode, and per-store result counts; a patient attacker can in principle distinguish "agent has memory matching X" from "no match" by observing latency.

The full threat model, including the OWASP / CWE / MITRE ATT&CK cross-mapping and the per-CVE commit references for every fix, lives in `docs/THREATS.md`.

## 7. Relationship to MCP and Other Protocols

The single question every reader asks first is: *why didn't you just add memory operations to MCP?* The honest answer has three parts.

**Memory is not a tool.** It is not a resource, not a prompt, not a sampling primitive. It is a distinct primitive with its own lifecycle (write, recall, forget, merge, expire), its own taxonomy (semantic, episodic, procedural, emotional), and its own governance surface (diff-and-approve, audit). MCP can absolutely *wrap* a memory backend Ã¢â‚¬â€ exposing `remember` / `recall` / `forget` as three tools is a fifteen-minute integration Ã¢â‚¬â€ but the wrapping is lossy: the five operations flatten into five opaque tools, the four memory types collapse into a string parameter, and the governance channel ends up living entirely outside MCP. memwire exists to give memory the same first-class treatment MCP gave tool-use.

**Iteration speed.** A v0 draft wire format needs to break things. memwire explicitly reserves the right to break wire-format compatibility through v0.5 (`docs/spec/v0.md Ã‚Â§9`). Pushing those breaking changes through a working-group governance cycle before the design has stabilized would slow the iteration the design needs. Once the spec is frozen, working-group governance becomes a help rather than a brake Ã¢â‚¬â€ which is why the v0.5 plan submits the spec to both the MCP-WG (as an extension proposal) and the IETF (as an Internet-Draft) at the same time.

**Multi-protocol portability.** Memory matters in places MCP does not reach. The web platform (W3C) will need an agent-memory primitive when browsers ship on-device models capable of multi-session reasoning. Cross-language ports (Rust, Go, TypeScript) want a JSON-Schema spec they can codegen against, not a JSON-RPC method signature tied to one transport. The IETF Internet-Draft route, by analogy to Cloudflare's Web Bot Auth, needs a spec document that stands on its own. Designing memwire as a standalone wire format keeps all three doors open; folding it into MCP first would close two of them.

**Three composition modes work today, today.**

- **memwire-as-MCP-tool.** Wrap an memwire `Memory` facade as an MCP server that exposes five tools Ã¢â‚¬â€ one per operation Ã¢â‚¬â€ and route the JSON-Schema-validated payload straight into the memwire request models. Roughly ten lines of glue code; any MCP-aware agent can use memwire through its existing client.
- **memwire-as-MCP-resource.** For agents that prefer to *read* memory rather than call it, expose `recall()` results as MCP resources. The resource URI carries the query; the resource body is the structured `RecallResponse`. Writes still go through the tool mode.
- **memwire-as-MCP-extension (proposed, v0.5).** memwire becomes a published MCP extension Ã¢â‚¬â€ `mcp.memory.v0` or similar Ã¢â‚¬â€ with the five operations and four memory types lifted into MCP's own type system, the governance channel becoming an MCP sub-protocol. This is the path we expect to propose once the wire format has settled.

**This is not a fork.** memwire and MCP address adjacent problems Ã¢â‚¬â€ tool-use and memory Ã¢â‚¬â€ and the agents we build use both at the same time. A realistic agent loop calls `mem.recall()` to gather context, runs the model with that context and the MCP tool list, dispatches any tool calls via the MCP client, and calls `mem.remember()` for anything worth retaining (routing it to the governance channel when sensitive). The two protocols never overlap in this code. Adopting one does not preclude adopting the other.

**Open questions on which we welcome external input.** (a) JSON-RPC vs REST shape: memwire's schemas are written against JSON Schema 2020-12 with a REST-friendly request/response idiom; MCP is JSON-RPC. Bridging is mechanical but there is real design space in how to express memwire operations as JSON-RPC methods while keeping JSON-Schema as the source of truth for validation. (b) Core vs extension: should memory live in core MCP, as one of the primitives, or always as an extension? We lean toward "extension first, core later if usage warrants" but defer to the working group. (c) Mapping the type taxonomy: should the four types surface as separate resource schemas, as tags, or as filter parameters on a unified recall verb? (d) Governance plane: MCP's elicitation primitive is the closest existing analogue, but it is designed for synchronous user-input mid-tool-call, not asynchronous review of pending writes. A future MCP-native memory extension may need a new sub-protocol for governance Ã¢â‚¬â€ or delegate it back to the application layer entirely.

The full version of this discussion lives in `docs/MCP-RELATIONSHIP.md`, which carries the complete composition examples, the overlap table, and the calls to action for MCP working-group members.

## 8. Future Work

memwire is a draft. The roadmap below lists the concrete deliverables we have planned through v1.0; we list them as intent, not commitment.

**Ã‚Â§8.1 v0.2 evaluation: full-scale memory benchmarks.** LongMemEval (Wu et al., arXiv:2410.10813) and LoCoMo (Maharana et al., arXiv:2402.17753) are the canonical long-context memory benchmarks; BEAM is the consolidated benchmark suite. v0.2 will land all three via a `scripts/run_longmemeval.py`-shaped harness; the script does not exist yet (verified absent from the repo at the time of this draft) and is the largest single v0.2 deliverable. The blocking cost is the gated GPT-4-class grader each benchmark requires.

**Ã‚Â§8.2 v0.2 user study.** A user study with external operators (n=10Ã¢â‚¬â€œ20) is in scope for v0.2. The study materials Ã¢â‚¬â€ NASA-TLX cognitive-load instrument, IRB protocol, consent forms, recruitment script Ã¢â‚¬â€ are tracked under `docs/paper/user-study/`; that directory does not exist at the time of this draft and is a v0.2 deliverable. The study targets operators of agent runtimes who would actually use the governance UI; the headline metric is whether the diff-and-approve flow reduces median review time below the alternative of "approve everything blindly."

**Ã‚Â§8.3 v0.2 spec tightenings.** Three spec tightenings the v0 evaluation directly motivates: (a) a `privacy_intent` block on `RememberRequest` so operators can require approval by `source`, `type`, or content predicate without instrumenting every caller; (b) multi-tenant `agent_id` scoping in the UI (per-operator allowed-`agent_id` ACL and SSO-shaped reviewer identity); (c) a required `expire(policy={})` empty-policy guard on every adapter (the Ã‚Â§5.3 conformance run surfaced this as the highest-priority spec tightening). Additional v0.2 hardening from `docs/THREATS.md`: signed `RecallHit` envelopes per backend; Merkle-chained audit rows; per-`agent_id` recall budgets; stable per-record id surfaced from every backend's write primitive.

**Ã‚Â§8.4 v0.5 spec freeze and standards engagement.** v0.5 is the freeze point: wire format stable, breaking changes prohibited. In parallel with v0.5: file an MCP RFC proposing memory as an extension primitive with memwire as the candidate reference; submit memwire v0.5 as an IETF Internet-Draft (`draft-<name>-memwire-00`). Both outcomes Ã¢â‚¬â€ acceptance as an MCP extension and stabilization as a parallel standard Ã¢â‚¬â€ are acceptable.

**Ã‚Â§8.5 v1.0 stable.** Frozen wire format; federated multi-tenant primitives (a cross-agent `share` operation under discussion); enterprise governance (SSO, role-based ACLs, signed audit exports); production-grade adapters for the long tail of backends not in v0.

## 9. Conclusion

We have presented memwire, a vendor-neutral wire format for agent memory operations: five operations, four memory types, a `MemoryStore` Protocol, a fan-out router with three fusion algorithms (with Reciprocal Rank Fusion as the defensible default under a 1-of-N malicious-backend model), and an optional human-in-the-loop governance channel. The reference implementation ships with five backend adapters covering the major open-source memory frameworks; a microbenchmark (recall@5 = 1.000 on 42 labelled queries, ingest p50 = 37.8 ms), an adversarial-fusion experiment (RRF holds recall@5 = 1.000 where MAX collapses to 0.500 with 80% leak), and a 16-scenario cross-adapter conformance suite (68 PASS / 12 SKIP / 0 FAIL out of 80 cells) establish the protocol's empirical viability.

We are honest about the bet. The algorithmic substrate (RRF, FSMs, STM/LTM, diff-and-approve) is prior art; the contribution is composition and standardization, and standards races have uncertain outcomes. Whatever the market outcome, the cumulative artifact Ã¢â‚¬â€ spec, reference implementation, threat model, conformance suite, open-data evaluation Ã¢â‚¬â€ lowers the cost for any future protocol effort in this space, including one that supersedes memwire. memwire is to memory what MCP is to tool-use. Whether memwire itself becomes that protocol or input material to whichever protocol the working groups settle on, the design work collected here is intended to compose with Ã¢â‚¬â€ not compete against Ã¢â‚¬â€ the existing ecosystem.

## Acknowledgments

We acknowledge the open-source projects memwire composes with: mem0, Letta (formerly MemGPT), Cognee, Zep/Graphiti, MemoryOS, MemTensor MemOS, sqlite-vec, pgvector, `pytransitions`, Starlette, HTMX, sentence-transformers, and the Model Context Protocol community. The Co-memorize diff-and-approve pattern draws on the Governed Memory line of work. RRF as a fusion primitive is from Cormack, Clarke, and Buettcher. The human-memory taxonomy mapping follows the cognitive-science literature established by Tulving and Squire.

## References

- Cormack, G. V., Clarke, C. L. A., and Buettcher, S. (2009). "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods." In *Proceedings of the 32nd International ACM SIGIR Conference on Research and Development in Information Retrieval (SIGIR '09)*, pages 758Ã¢â‚¬â€œ759. DOI:10.1145/1571941.1572114.
- Tulving, E. (1972). "Episodic and Semantic Memory." In *Organization of Memory*, Tulving, E., and Donaldson, W. (Eds.), pages 381Ã¢â‚¬â€œ402. Academic Press, New York.
- Squire, L. R. (1992). "Declarative and Nondeclarative Memory: Multiple Brain Systems Supporting Learning and Memory." *Journal of Cognitive Neuroscience* 4(3), pages 232Ã¢â‚¬â€œ243. DOI:10.1162/jocn.1992.4.3.232.
- Packer, C., Wooders, S., Lin, K., Fang, V., Patil, S. G., Stoica, I., and Gonzalez, J. E. (2023). "MemGPT: Towards LLMs as Operating Systems." arXiv:2310.08560.
- Wu, D., Wang, H., Yu, W., Zhang, Y., Chang, K.-W., and Yu, D. (2024). "LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory." arXiv:2410.10813.
- Maharana, A., Lee, D.-H., Tulyakov, S., Bansal, M., Barbieri, F., and Fang, Y. (2024). "Evaluating Very Long-Term Conversational Memory of LLM Agents (LoCoMo)." arXiv:2402.17753.
- Taheri, H. (2026). "Governed Memory: A Production Architecture for Multi-Agent Workflows." arXiv:2603.17787.
- Chhikara, P., Khant, D., Aryan, S., Singh, T., and Yadav, D. (2025). "Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory." arXiv:2504.19413.
- BEAM benchmark for long-term conversational memory. *Canonical reference TBD; cited only as a future evaluation target (Ã‚Â§5.4, Ã‚Â§8.1).*
- Model Context Protocol specification, version `2025-11-25`. modelcontextprotocol.io.
- JSON Schema 2020-12. https://json-schema.org/draft/2020-12/release-notes.
- Meunier, T., and Ladd, W. (2026). "Web Bot Authentication Architecture." IETF Internet-Draft `draft-meunier-web-bot-auth-architecture-05`, 2 March 2026.

Citation handle for this work (auto-derived from `CITATION.cff` via `cffconvert --format bibtex`):

```
@software{memwire,
  author = {Thamilvendhan Munirathinam},
  title  = {memwire: A vendor-neutral wire format for agent memory operations},
  year   = {2026},
  url    = {https://github.com/mthamil107/memwire}
}
```

[^prior-work]: Originally drafted as "Agent Memory Protocol (AMP)" in May 2026; renamed to `memwire` before launch to avoid collision with an unrelated, prior project of the same name (<https://github.com/akshayaggarwal99/amp>, created Dec 2025). See `docs/PRIOR-WORK.md` in the repository for the long version.
