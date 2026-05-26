# Agent Memory Protocol (AMP) — Specification v0

**Version:** 0.1.0-draft · **Status:** DRAFT — subject to change · **Generated:** 2026-05-26

> This document is the wire-format specification for AMP. It defines operations, memory types, and the data shapes that flow between memory clients, the memory router, and backend memory stores. Reference implementation lives at `src/amp/`. Schemas use JSON Schema Draft 2020-12.

---

## 1. Goals

AMP exists to do for agent memory what MCP did for agent tool-use: provide a vendor-neutral wire format so any memory client can talk to any memory backend, and any agent can carry its memory across runtimes.

**Specifically AMP defines:**

1. A small set of operations (`remember`, `recall`, `forget`, `merge`, `expire`) with stable JSON schemas
2. Four memory-type tags drawn from the human-memory taxonomy (`semantic`, `episodic`, `procedural`, `emotional`)
3. A `MemoryStore` interface backends MUST implement
4. A `Recall` result format clients SHOULD assume
5. An optional `governance` channel for HITL approval workflows

**AMP does NOT define:**

- Which embedding model to use
- Which vector store technology to use
- Specific FSM semantics for procedural memory (uses pytransitions-compatible JSON; spec is open)
- Authentication or transport security (delegate to the surrounding application)

---

## 2. Memory Types

Each memory record carries one `type` tag from this fixed vocabulary:

| Type | Definition | Example |
|------|------------|---------|
| `semantic` | General facts, concepts, declarative knowledge | "Alice is allergic to peanuts" |
| `episodic` | Specific past events with time/place context | "On 2026-05-20 Alice told me she was nervous about her flight" |
| `procedural` | How-to knowledge, FSM-encoded procedures | The state machine for "book a flight" |
| `emotional` | Affective associations with experiences | "Alice expressed anxiety when discussing flights" |

These map 1:1 to the human-memory taxonomy referenced in standard cognitive-science literature and in the D. Biswas agentic AI module 7.

Backends MAY store all four types in one table with a `type` column, or MAY shard by type. Clients MUST NOT assume a particular storage strategy.

---

## 3. Operations

### 3.1 `remember`

Write a new memory.

**Request schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://amp.dev/schemas/v0/remember",
  "type": "object",
  "required": ["agent_id", "type", "content"],
  "properties": {
    "agent_id":   { "type": "string", "minLength": 1, "maxLength": 256 },
    "user_id":    { "type": "string", "maxLength": 256 },
    "type":       { "enum": ["semantic", "episodic", "procedural", "emotional"] },
    "content":    { "type": "string", "minLength": 1 },
    "metadata":   { "type": "object", "additionalProperties": true },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1, "default": 1.0 },
    "source":     { "type": "string" },
    "expires_at": { "type": "integer", "description": "Unix epoch ms; optional TTL" },
    "approval_required": { "type": "boolean", "default": false }
  }
}
```

**Response:**

```json
{
  "id":         "01HZK...",
  "stored_at":  1716700000000,
  "stores":     ["sqlite-vec", "mem0"],
  "pending_approval": false,
  "approval_url": null
}
```

If `approval_required: true` (or the governance policy forces it), the response includes `pending_approval: true` and `approval_url` pointing to the governance UI. The memory is staged but not committed until approval.

### 3.2 `recall`

Read memories matching a query.

**Request schema:**

```json
{
  "$id": "https://amp.dev/schemas/v0/recall",
  "type": "object",
  "required": ["agent_id", "query"],
  "properties": {
    "agent_id": { "type": "string" },
    "user_id":  { "type": "string" },
    "query":    { "type": "string", "minLength": 1 },
    "k":        { "type": "integer", "minimum": 1, "maximum": 1000, "default": 5 },
    "types":    {
      "type": "array",
      "items": { "enum": ["semantic", "episodic", "procedural", "emotional"] }
    },
    "hops":     { "type": "integer", "minimum": 0, "maximum": 3, "default": 0 },
    "fusion":   { "enum": ["rrf", "max", "weighted"], "default": "rrf" },
    "filter":   { "type": "object", "additionalProperties": true },
    "fresher_than_days": { "type": "integer", "minimum": 0 }
  }
}
```

**Response:**

```json
{
  "results": [
    {
      "id":         "01HZK...",
      "type":       "semantic",
      "content":    "Alice is allergic to peanuts",
      "score":      0.94,
      "metadata":   { ... },
      "created_at": 1716700000000,
      "supporting": [],  // related memory ids contributing to the score
      "source_store": "sqlite-vec"
    }
  ],
  "fusion_used": "rrf",
  "stores_queried": ["sqlite-vec", "mem0"],
  "latency_ms": 247
}
```

### 3.3 `forget`

Delete memories matching a filter.

```json
{
  "$id": "https://amp.dev/schemas/v0/forget",
  "type": "object",
  "required": ["agent_id"],
  "properties": {
    "agent_id":   { "type": "string" },
    "user_id":    { "type": "string" },
    "ids":        { "type": "array", "items": { "type": "string" } },
    "filter":     { "type": "object", "additionalProperties": true },
    "hard_delete": { "type": "boolean", "default": false },
    "reason":     { "type": "string" }
  }
}
```

Soft delete (`hard_delete: false`) marks `deleted_at` but retains the record for audit. Hard delete removes the row. The audit log keeps the operation either way.

### 3.4 `merge`

Collapse two entities into one canonical entity. Used for deduplication.

```json
{
  "$id": "https://amp.dev/schemas/v0/merge",
  "type": "object",
  "required": ["agent_id", "canonical", "duplicates"],
  "properties": {
    "agent_id":   { "type": "string" },
    "canonical":  { "type": "string", "description": "the surviving entity id or name" },
    "duplicates": { "type": "array", "items": { "type": "string" }, "minItems": 1 },
    "strategy":   { "enum": ["keep_canonical", "merge_content", "keep_highest_confidence"], "default": "keep_canonical" }
  }
}
```

### 3.5 `expire`

Apply a TTL policy to a memory subset.

```json
{
  "$id": "https://amp.dev/schemas/v0/expire",
  "type": "object",
  "required": ["agent_id"],
  "properties": {
    "agent_id":   { "type": "string" },
    "policy": {
      "type": "object",
      "properties": {
        "older_than_days":     { "type": "integer", "minimum": 1 },
        "type":                { "enum": ["semantic", "episodic", "procedural", "emotional"] },
        "confidence_below":    { "type": "number", "minimum": 0, "maximum": 1 },
        "no_recall_in_days":   { "type": "integer", "minimum": 1 }
      }
    },
    "action": { "enum": ["forget", "archive", "demote"], "default": "forget" }
  }
}
```

---

## 4. The `MemoryStore` interface

Backends adopt AMP by implementing a `MemoryStore` Protocol. Reference Python signature:

```python
from typing import Protocol, Any
from amp.models import (
    RememberRequest, RememberResponse,
    RecallRequest, RecallResponse,
    ForgetRequest, ForgetResponse,
    MergeRequest, MergeResponse,
    ExpireRequest, ExpireResponse,
)

class MemoryStore(Protocol):
    async def remember(self, req: RememberRequest) -> RememberResponse: ...
    async def recall(self, req: RecallRequest)   -> RecallResponse: ...
    async def forget(self, req: ForgetRequest)   -> ForgetResponse: ...
    async def merge(self, req: MergeRequest)     -> MergeResponse: ...
    async def expire(self, req: ExpireRequest)   -> ExpireResponse: ...

    async def health(self) -> dict[str, Any]: ...
    @property
    def capabilities(self) -> set[str]: ...
```

`capabilities` is a set of strings declaring what the backend supports — `{"semantic", "episodic", "fts", "vector", "graph", "procedural"}` etc. The router uses this to skip stores that don't support a given operation.

---

## 5. Memory Router semantics

The router is a `MemoryStore` itself, composed of N child stores. On each operation:

- **`remember`**: by default fans out to all child stores; `policy: "primary_only"` writes only to the first
- **`recall`**: fans out to all stores in parallel, fuses results per `fusion` parameter
- **`forget`/`merge`/`expire`**: fans out to all stores; aggregates per-store responses

Fusion algorithms:

- **`rrf`** (default): Reciprocal Rank Fusion, k=60
  ```
  score(item) = Σ (1 / (60 + rank_i(item)))  for each store i
  ```
- **`max`**: take the highest score per item across stores (no aggregation)
- **`weighted`**: per-store weights from config; sum weighted scores

Graph-hop boost (when `hops > 0`):
```
final_score(item) = rrf_score(item) * (1 + 0.1 * (1 / (1 + min_hop_distance)))
```

---

## 6. Governance channel (optional)

When a client is configured with a `GovernanceClient`, `remember` and `forget` operations with `approval_required: true` (or matching a policy rule) are routed through governance before commit.

**Governance request:**

```json
{
  "$id": "https://amp.dev/schemas/v0/governance/review",
  "type": "object",
  "required": ["operation", "request", "agent_id"],
  "properties": {
    "operation":   { "enum": ["remember", "forget", "merge"] },
    "agent_id":    { "type": "string" },
    "request":     { "$ref": "https://amp.dev/schemas/v0/remember" },
    "diff":        {
      "type": "object",
      "description": "Structured diff against current memory state",
      "properties": {
        "added":    { "type": "array" },
        "removed":  { "type": "array" },
        "modified": { "type": "array" }
      }
    },
    "reasoning":   { "type": "string" }
  }
}
```

**Governance response:**

```json
{
  "approved":   true,
  "reviewer":   "user@example.com",
  "reviewed_at": 1716700000000,
  "reason":     "Looks correct; aligned with policy"
}
```

The governance UI implements this contract. Pro-tier UI ships an approval-learning loop: track which patterns the reviewer always approves / always rejects and auto-allow after N consistent decisions.

---

## 7. Procedural memory format

Procedures are stored as JSON-serialized FSMs compatible with `pytransitions`:

```json
{
  "name": "book-flight",
  "initial": "searching",
  "states": ["searching", "comparing", "selecting", "paying", "confirmed", "cancelled"],
  "transitions": [
    { "trigger": "found_options",  "source": "searching",  "dest": "comparing" },
    { "trigger": "picked",         "source": "comparing",  "dest": "selecting" },
    { "trigger": "paid",           "source": "selecting",  "dest": "paying" },
    { "trigger": "receipt",        "source": "paying",     "dest": "confirmed" },
    { "trigger": "cancel",         "source": "*",          "dest": "cancelled" }
  ],
  "current": "searching",
  "metadata": {
    "agent_id": "travel-agent-v2",
    "version": "1.0.0",
    "created_at": 1716700000000
  }
}
```

This schema is intentionally minimal so backends can extend with their own state-machine semantics. Future versions of AMP may standardize action handlers.

---

## 8. Worked end-to-end example

```python
import asyncio
from amp import Memory, MemoryType

async def main():
    mem = Memory(
        agent_id="customer-support-bot",
        stores=["sqlite-vec://./mem.db", "mem0://default"],
    )

    # Write a semantic fact
    r = await mem.remember(
        "Customer 12345 prefers email over phone",
        type=MemoryType.SEMANTIC,
        user_id="customer-12345",
        confidence=0.95,
    )
    print(r.id, r.stores)  # 01HZK..., ['sqlite-vec', 'mem0']

    # Write an episodic memory
    await mem.remember(
        "On 2026-05-26 customer 12345 reported a billing issue",
        type=MemoryType.EPISODIC,
        user_id="customer-12345",
    )

    # Recall both
    hits = await mem.recall(
        "what do I know about customer 12345?",
        k=10,
        types=[MemoryType.SEMANTIC, MemoryType.EPISODIC],
        fusion="rrf",
    )
    for hit in hits:
        print(hit.score, hit.type, hit.content)

    # Forget old episodic
    await mem.expire(policy={"older_than_days": 90, "type": "episodic"})

asyncio.run(main())
```

---

## 9. Spec versioning & evolution

- AMP v0 is **draft**. Breaking changes allowed until v0.5.
- v0.5 → v1.0: stabilization. Operations and schemas frozen.
- v1.0 → publish as IETF Internet-Draft for cross-language adoption.

Backwards compatibility rules:

- New optional fields: allowed at any time
- New required fields: minor version bump, deprecation period
- Removed fields: major version bump only
- New memory types: minor version bump

---

## 10. Open questions for v0

These are deliberately not yet decided:

- **Embedding metadata** — should `remember()` accept a pre-computed embedding? Or always compute server-side?
- **Cross-agent sharing** — should AMP define a `share` operation for inter-agent memory transfer? Likely v0.2.
- **Streaming `recall`** — `recall_stream()` for very large k? Defer to v1.
- **Privacy-intent flags** — the "Layer 3 gap" from Module 11. Should `remember()` carry `privacy_intent: {"retain": "30d", "share_with": ["agent-x"], "user_consent_id": "..."}`? Likely v0.2.
- **Federated memory** — multi-tenant scoping primitives. Defer to v1.

---

## 11. References

Standards we're modeling after:

- [JSON Schema 2020-12](https://json-schema.org/draft/2020-12/release-notes)
- [Model Context Protocol](https://modelcontextprotocol.io) — for the cross-vendor, MCP-shaped pattern
- [OpenTelemetry semconv](https://opentelemetry.io/docs/specs/semconv/) — for stable identifier patterns
- [GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) — for cross-tool tracing

Memory research informing the design:

- LongMemEval benchmark
- LoCoMo benchmark
- BEAM benchmark
- "Remember Me, Refine Me" — procedural memory
- "Governed Memory" arXiv 2603.17787 — Co-memorize HITL
- Mem0 architecture writeup
- Letta (MemGPT) hierarchical memory paper
