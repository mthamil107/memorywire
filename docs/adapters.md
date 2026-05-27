# Writing a new MemoryStore adapter

> **WIP** — finalized when the `MemoryStore` Protocol lands in Phase 2.

A backend adopts AMP by implementing the `amp.store.base.MemoryStore` Protocol:

```python
from typing import Protocol, Any
from amp.models import (
    RememberRequest, RememberResponse,
    RecallRequest,   RecallResponse,
    ForgetRequest,   ForgetResponse,
    MergeRequest,    MergeResponse,
    ExpireRequest,   ExpireResponse,
)

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

`capabilities` is a set of strings declaring what your backend supports —
e.g. `{"semantic", "episodic", "fts", "vector", "graph"}`. The memory router
uses this to skip stores that don't support a given operation.

## Checklist

1. Implement the Protocol in `src/amp/store/<backend>.py`.
2. Add a `[project.optional-dependencies]` entry in `pyproject.toml`.
3. Unit tests with a mocked backend in `tests/unit/store/`.
4. Integration tests in `tests/integration/store/` marked `@pytest.mark.integration`.
5. Document the URL scheme used to construct your adapter (e.g. `sqlite-vec://...`).

Reference implementations live in `src/amp/store/sqlite_vec.py`,
`src/amp/store/mem0_adapter.py`, and `src/amp/store/letta_adapter.py`
once Phase 3 lands.

## URL schemes

| Scheme           | Adapter                                            | Notes                                                                                       |
| ---------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `sqlite-vec://`  | `amp.store.sqlite_vec.SqliteVecStore`              | Path = SQLite database file. `sqlite-vec://:memory:` runs in-process.                       |
| `mem0://`        | `amp.store.mem0_adapter.Mem0Store`                 | `mem0://default` uses the mem0 SDK defaults; other profile names are reserved.              |
| `letta://`       | `amp.store.letta_adapter.LettaStore`               | `letta://<host>[:<port>][?token=...&agent_id=...]`. `letta://default` uses SDK env defaults. |

### `letta://` anatomy

* `letta://default` — use the Letta SDK's environment-driven defaults
  (`LETTA_API_KEY`, `LETTA_BASE_URL`). The Letta-side `agent_id` MUST be
  supplied via the query string (`?agent_id=...`) or set on the
  `LettaStore` instance before any operation runs; the adapter raises
  `ValueError` if it is missing.
* `letta://<host>[:<port>]` — explicit Letta server. The host:port is
  composed into the SDK's `base_url` (e.g. `http://localhost:8283`).
* Query parameters: `token` (forwarded as `api_key`), `agent_id`,
  `base_url` (overrides the host:port form).

Letta archival memory has no free-form metadata field on its public API.
The adapter encodes AMP-specific fields (`type`, `confidence`, `source`,
`expires_at`, caller metadata) onto Letta's `tags` list using
`amp_type:`, `amp_conf:`, `amp_src:`, `amp_exp:`, and `amp_kv:k=v`
prefixes; the recall path parses them back out. Structured (nested)
metadata is lossy under this encoding — see the module docstring for
the full list of spec-gap notes.

## Conformance matrix

16 protocol scenarios from `tests/conformance/scenarios.py`, evaluated
against every shipped adapter. The suite is the empirical evidence that
the `MemoryStore` Protocol is in fact vendor-neutral: the same setup +
action + predicate runs against the SQLite reference implementation and
the four backend-mocked adapters.

Legend: ✅ = passes; ⏭ = SKIPPED for a documented adapter limitation
(see `tests/conformance/conftest.py::SKIP_OVERRIDES` and the per-adapter
module docstrings for the spec-gap notes referenced below); ❌ = fails.

| Scenario                              | sqlite-vec | mem0 | letta | cognee | pgvector |
| ------------------------------------- | :--------: | :--: | :---: | :----: | :------: |
| basic_remember_recall                 |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| remember_recall_by_user_filter        |     ✅     |  ✅  |  ⏭   |   ⏭   |    ✅    |
| type_filter                           |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| forget_by_ids                         |     ✅     |  ✅  |  ✅   |   ⏭   |    ✅    |
| forget_no_scope_raises                |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| expire_empty_policy_raises            |     ✅     |  ⏭  |  ⏭   |   ⏭   |    ✅    |
| expire_empty_policy_object_raises     |     ✅     |  ⏭  |  ⏭   |   ⏭   |    ✅    |
| expire_by_age                         |     ✅     |  ⏭  |  ✅   |   ⏭   |    ✅    |
| merge_keep_canonical                  |     ✅     |  ✅  |  ✅   |   ⏭   |    ✅    |
| approval_required_pending             |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| capabilities_declared                 |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| health_returns_status                 |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| isinstance_protocol                   |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| recall_returns_score_metadata         |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| fresher_than_days_filter              |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| multi_remember_then_recall            |     ✅     |  ✅  |  ✅   |   ✅   |    ✅    |
| **pass / skip**                       | **16 / 0** | **13 / 3** | **13 / 3** | **10 / 6** | **16 / 0** |

Aggregate: **PASS 68 / SKIP 12 / FAIL 0** out of 80 cells (16 scenarios ×
5 adapters). Every non-skipped cell passes.

### Documented skip reasons

* **letta + cognee, `remember_recall_by_user_filter`** — neither backend
  has a `user_id` namespace separate from its top-level scope (Letta
  scopes by `agent_id`, Cognee by dataset). AMP's `user_id` dimension is
  lost on the backend.
* **mem0 + letta + cognee, `expire_empty_policy_raises` /
  `expire_empty_policy_object_raises`** — only the SQL adapters
  (sqlite-vec, pgvector) defensively raise on an empty `ExpirePolicy`.
  The three SDK-wrapping adapters silently fall through to
  match-everything. **v0.2 should tighten this in the spec and require
  every adapter to raise.**
* **mem0, `expire_by_age`** — mem0's `created_at` format is heterogenous
  (int seconds, int ms, ISO-8601 strings) depending on the SDK build; the
  conformance mock doesn't model this. The translation is verified in
  `tests/unit/store/test_mem0_adapter.py`.
* **cognee, `forget_by_ids` / `expire_by_age` / `merge_keep_canonical`**
  — Cognee's `forget` primitive requires a pipeline-assigned `data_id`
  UUID. The adapter mints synthetic `cog:<sha1>` ids at write time
  because Cognee's `add` doesn't surface per-record ids, so per-id
  deletes (and the operations that depend on them — expire-forget and
  merge-then-drop) are no-ops. **v0.2 should require backends to surface
  a stable per-record id from their write primitive.**
