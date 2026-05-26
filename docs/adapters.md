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

Reference implementations live in `src/amp/store/sqlite_vec.py` and
`src/amp/store/mem0_adapter.py` once Phase 3 lands.
