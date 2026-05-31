"""The :class:`MemoryStore` Protocol that every memwire backend implements.

Spec section 4 fixes this surface. The router (Phase 4) is itself a
``MemoryStore`` composed of N child stores; adapters in Phase 3
(sqlite-vec, mem0, â€¦) implement this same Protocol.

``@runtime_checkable`` is applied so adapter tests can use
``isinstance(adapter, MemoryStore)`` for a structural check. Note that
``runtime_checkable`` only verifies method *names*, not signatures â€” the
authoritative contract is still the type annotations here, enforced by
mypy at static-check time.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from memwire.models import (
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    MergeRequest,
    MergeResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)


class Capability:
    """Well-known capability strings declared by :attr:`MemoryStore.capabilities`.

    These are the values the router (Phase 4) uses to decide which child
    stores to fan a given operation out to (e.g. skip a vector-only store
    on a graph-hop query). The set is open â€” backends MAY declare
    additional strings â€” but these names are the canonical ones used by
    the reference implementation.
    """

    # Memory-type support (matches MemoryType values).
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"
    EMOTIONAL = "emotional"

    # Backend-feature flags.
    FTS = "fts"
    VECTOR = "vector"
    GRAPH = "graph"
    GOVERNANCE = "governance"
    # Whether the backend tracks last-recalled-at per memory; required for
    # ``expire(policy={"no_recall_in_days": N})`` per spec section 3.5.
    RECALL_TRACKING = "recall_tracking"


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol every memwire backend (and the router itself) implements.

    See :file:`docs/spec/v0.md` Â§4 for the normative definition. All
    operations are asynchronous; backends that wrap synchronous libraries
    should run them in a thread/executor.
    """

    async def remember(self, req: RememberRequest) -> RememberResponse:
        """Write a new memory and return the stored-or-staged response."""
        ...

    async def recall(self, req: RecallRequest) -> RecallResponse:
        """Read memories matching the query and return fused hits."""
        ...

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        """Delete (soft or hard) memories matching ids or filter."""
        ...

    async def merge(self, req: MergeRequest) -> MergeResponse:
        """Collapse duplicate entities into a single canonical entity."""
        ...

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        """Apply a TTL/age/recency policy to a subset of memories."""
        ...

    async def health(self) -> dict[str, Any]:
        """Return a backend-defined health-status object."""
        ...

    @property
    def capabilities(self) -> set[str]:
        """Capability strings declaring what the backend supports."""
        ...


__all__ = ["Capability", "MemoryStore"]
