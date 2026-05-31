# Writing a new MemoryStore adapter

> **WIP** Ã¢â‚¬â€ finalized when the `MemoryStore` Protocol lands in Phase 2.

A backend adopts memwire by implementing the `memwire.store.base.MemoryStore` Protocol:

```python
from typing import Protocol, Any
from memwire.models import (
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

`capabilities` is a set of strings declaring what your backend supports Ã¢â‚¬â€
e.g. `{"semantic", "episodic", "fts", "vector", "graph"}`. The memory router
uses this to skip stores that don't support a given operation.

## Checklist

1. Implement the Protocol in `src/memwire/store/<backend>.py`.
2. Add a `[project.optional-dependencies]` entry in `pyproject.toml`.
3. Unit tests with a mocked backend in `tests/unit/store/`.
4. Integration tests in `tests/integration/store/` marked `@pytest.mark.integration`.
5. Document the URL scheme used to construct your adapter (e.g. `sqlite-vec://...`).

Reference implementations live in `src/memwire/store/sqlite_vec.py`,
`src/memwire/store/mem0_adapter.py`, and `src/memwire/store/letta_adapter.py`
once Phase 3 lands.

## URL schemes

| Scheme           | Adapter                                            | Notes                                                                                       |
| ---------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `sqlite-vec://`  | `memwire.store.sqlite_vec.SqliteVecStore`              | Path = SQLite database file. `sqlite-vec://:memory:` runs in-process.                       |
| `mem0://`        | `memwire.store.mem0_adapter.Mem0Store`                 | `mem0://default` uses the mem0 SDK defaults; other profile names are reserved.              |
| `letta://`       | `memwire.store.letta_adapter.LettaStore`               | `letta://<host>[:<port>][?token=...&agent_id=...]`. `letta://default` uses SDK env defaults. |

### `letta://` anatomy

* `letta://default` Ã¢â‚¬â€ use the Letta SDK's environment-driven defaults
  (`LETTA_API_KEY`, `LETTA_BASE_URL`). The Letta-side `agent_id` MUST be
  supplied via the query string (`?agent_id=...`) or set on the
  `LettaStore` instance before any operation runs; the adapter raises
  `ValueError` if it is missing.
* `letta://<host>[:<port>]` Ã¢â‚¬â€ explicit Letta server. The host:port is
  composed into the SDK's `base_url` (e.g. `http://localhost:8283`).
* Query parameters: `token` (forwarded as `api_key`), `agent_id`,
  `base_url` (overrides the host:port form).

Letta archival memory has no free-form metadata field on its public API.
The adapter encodes memwire-specific fields (`type`, `confidence`, `source`,
`expires_at`, caller metadata) onto Letta's `tags` list using
`amp_type:`, `amp_conf:`, `amp_src:`, `amp_exp:`, and `amp_kv:k=v`
prefixes; the recall path parses them back out. Structured (nested)
metadata is lossy under this encoding Ã¢â‚¬â€ see the module docstring for
the full list of spec-gap notes.

## Conformance matrix

16 protocol scenarios from `tests/conformance/scenarios.py`, evaluated
against every shipped adapter. The suite is the empirical evidence that
the `MemoryStore` Protocol is in fact vendor-neutral: the same setup +
action + predicate runs against the SQLite reference implementation and
the four backend-mocked adapters.

Legend: Ã¢Å“â€¦ = passes; Ã¢ÂÂ­ = SKIPPED for a documented adapter limitation
(see `tests/conformance/conftest.py::SKIP_OVERRIDES` and the per-adapter
module docstrings for the spec-gap notes referenced below); Ã¢ÂÅ’ = fails.

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

Aggregate: **PASS 68 / SKIP 12 / FAIL 0** out of 80 cells (16 scenarios Ãƒâ€”
5 adapters). Every non-skipped cell passes.

### Documented skip reasons

* **letta + cognee, `remember_recall_by_user_filter`** Ã¢â‚¬â€ neither backend
  has a `user_id` namespace separate from its top-level scope (Letta
  scopes by `agent_id`, Cognee by dataset). memwire's `user_id` dimension is
  lost on the backend.
* **mem0 + letta + cognee, `expire_empty_policy_raises` /
  `expire_empty_policy_object_raises`** Ã¢â‚¬â€ only the SQL adapters
  (sqlite-vec, pgvector) defensively raise on an empty `ExpirePolicy`.
  The three SDK-wrapping adapters silently fall through to
  match-everything. **v0.2 should tighten this in the spec and require
  every adapter to raise.**
* **mem0, `expire_by_age`** Ã¢â‚¬â€ mem0's `created_at` format is heterogenous
  (int seconds, int ms, ISO-8601 strings) depending on the SDK build; the
  conformance mock doesn't model this. The translation is verified in
  `tests/unit/store/test_mem0_adapter.py`.
* **cognee, `forget_by_ids` / `expire_by_age` / `merge_keep_canonical`**
  Ã¢â‚¬â€ Cognee's `forget` primitive requires a pipeline-assigned `data_id`
  UUID. The adapter mints synthetic `cog:<sha1>` ids at write time
  because Cognee's `add` doesn't surface per-record ids, so per-id
  deletes (and the operations that depend on them Ã¢â‚¬â€ expire-forget and
  merge-then-drop) are no-ops. **v0.2 should require backends to surface
  a stable per-record id from their write primitive.**
