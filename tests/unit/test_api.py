"""Tests for the :class:`amp.api.Memory` facade.

The facade is a thin wrapper around :class:`amp.router.MemoryRouter` and a
URL → adapter dispatcher. These tests cover both halves:

* :func:`amp.api._build_store` round-trips known schemes and rejects unknown
  ones.
* :class:`Memory` builds the right pydantic request from kwargs, dispatches
  through the router, and reshapes the response (e.g. :meth:`recall`
  returns a bare list).

A small ``MockStore`` is reused from the Phase 2 test module to avoid
pulling in the real adapters' optional deps.
"""

from __future__ import annotations

from typing import Any

import pytest

from amp import (
    Capability,
    ExpireAction,
    FusionAlgorithm,
    Memory,
    MemoryStore,
    MemoryType,
    MergeStrategy,
    RecallHit,
)
from amp.api import _build_store
from amp.models import (
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    ForgetStoreResult,
    MergeRequest,
    MergeResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)
from amp.store.mem0_adapter import Mem0Store
from amp.store.sqlite_vec import SqliteVecStore

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class MockStore:
    """Tiny in-process :class:`MemoryStore` for facade tests.

    Independent of :class:`tests.unit.test_store_protocol.MockStore` to keep
    each test module self-contained.
    """

    BACKEND_NAME = "mock"

    def __init__(
        self,
        *,
        backend_name: str = "mock",
        capabilities: set[str] | None = None,
        recall_hits: list[RecallHit] | None = None,
    ) -> None:
        self.BACKEND_NAME = backend_name
        self._capabilities = capabilities or {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.PROCEDURAL,
            Capability.EMOTIONAL,
        }
        self._recall_hits = recall_hits or []
        self.remember_calls: list[RememberRequest] = []
        self.recall_calls: list[RecallRequest] = []
        self.forget_calls: list[ForgetRequest] = []
        self.merge_calls: list[MergeRequest] = []
        self.expire_calls: list[ExpireRequest] = []
        self.closed: bool = False

    @property
    def capabilities(self) -> set[str]:
        return self._capabilities

    async def remember(self, req: RememberRequest) -> RememberResponse:
        self.remember_calls.append(req)
        return RememberResponse(
            id=f"{self.BACKEND_NAME}-id-{len(self.remember_calls)}",
            stored_at=1_700_000_000_000,
            stores=[self.BACKEND_NAME],
            pending_approval=False,
            approval_url=None,
        )

    async def recall(self, req: RecallRequest) -> RecallResponse:
        self.recall_calls.append(req)
        return RecallResponse(
            results=list(self._recall_hits),
            fusion_used=req.fusion if req.fusion is not None else FusionAlgorithm.RRF,
            stores_queried=[self.BACKEND_NAME],
            latency_ms=1,
        )

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        self.forget_calls.append(req)
        forgotten = list(req.ids or [])
        return ForgetResponse(
            forgotten_ids=forgotten,
            hard_delete=bool(req.hard_delete),
            stores=[ForgetStoreResult(store=self.BACKEND_NAME, count=len(forgotten))],
            pending_approval=False,
            approval_url=None,
        )

    async def merge(self, req: MergeRequest) -> MergeResponse:
        self.merge_calls.append(req)
        return MergeResponse(
            canonical=req.canonical,
            merged_count=len(req.duplicates),
            strategy_used=req.strategy
            if req.strategy is not None
            else MergeStrategy.KEEP_CANONICAL,
            stores=[self.BACKEND_NAME],
        )

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        self.expire_calls.append(req)
        return ExpireResponse(
            matched_count=0,
            action_taken=req.action if req.action is not None else ExpireAction.FORGET,
            stores=[self.BACKEND_NAME],
        )

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "backend": self.BACKEND_NAME}

    def close(self) -> None:
        self.closed = True


def _hit(memory_id: str, *, score: float = 0.5) -> RecallHit:
    """Build a small :class:`RecallHit` for facade-test responses."""
    return RecallHit(
        id=memory_id,
        type=MemoryType.SEMANTIC,
        content=f"content-{memory_id}",
        score=score,
        metadata=None,
        created_at=1_700_000_000_000,
        supporting=[],
        source_store="mock",
    )


# ---------------------------------------------------------------------------
# 1. URL dispatch
# ---------------------------------------------------------------------------


def test_build_store_sqlite_vec_url() -> None:
    """``sqlite-vec://:memory:`` resolves to :class:`SqliteVecStore`."""

    # Inject a fake embedder via the post-construction attribute so we don't
    # pull sentence-transformers. _build_store doesn't expose the embedder
    # kwarg directly — but SqliteVecStore.from_url uses the default model
    # only on first embed call, so just verifying type is enough.
    store = _build_store("sqlite-vec://:memory:")
    assert isinstance(store, SqliteVecStore)
    store.close()


def test_build_store_mem0_url() -> None:
    """``mem0://default`` resolves to :class:`Mem0Store`."""
    store = _build_store("mem0://default")
    assert isinstance(store, Mem0Store)


def test_build_store_unknown_scheme_raises() -> None:
    """An unknown scheme raises :class:`ValueError` with the URL in the message."""
    with pytest.raises(ValueError, match="unknown store URL scheme"):
        _build_store("unknown-scheme://whatever")


def test_memory_accepts_store_instance() -> None:
    """Passing a pre-built :class:`MemoryStore` instance works without URL parsing."""
    mock = MockStore()
    mem = Memory(agent_id="a", stores=[mock])
    # The router's first store should be the same object identity.
    assert mem.router.stores[0] is mock


def test_memory_constructor_rejects_empty_stores() -> None:
    """No stores is a constructor-time error."""
    with pytest.raises(ValueError, match="at least one store"):
        Memory(agent_id="a", stores=[])


def test_memory_constructor_rejects_empty_agent_id() -> None:
    """Empty agent_id is a constructor-time error."""
    with pytest.raises(ValueError, match="agent_id"):
        Memory(agent_id="", stores=[MockStore()])


# ---------------------------------------------------------------------------
# 2. Method dispatch
# ---------------------------------------------------------------------------


async def test_remember_dispatches_through_router() -> None:
    """``Memory.remember`` builds a :class:`RememberRequest` and routes it."""
    mock = MockStore()
    mem = Memory(agent_id="agent-x", stores=[mock])

    resp = await mem.remember(
        "Alice likes peanuts.",
        type=MemoryType.SEMANTIC,
        user_id="alice@example.com",
        metadata={"topic": "diet"},
        confidence=0.9,
    )

    assert len(mock.remember_calls) == 1
    sent = mock.remember_calls[0]
    assert sent.agent_id == "agent-x"
    assert sent.user_id == "alice@example.com"
    assert sent.type is MemoryType.SEMANTIC
    assert sent.content == "Alice likes peanuts."
    assert sent.metadata == {"topic": "diet"}
    assert sent.confidence == 0.9
    assert resp.id == "mock-id-1"


async def test_recall_returns_bare_list() -> None:
    """``Memory.recall`` returns ``list[RecallHit]``, not a ``RecallResponse``."""
    mock = MockStore(recall_hits=[_hit("m1"), _hit("m2")])
    mem = Memory(agent_id="a", stores=[mock])

    hits = await mem.recall("anything", k=10)

    assert isinstance(hits, list)
    assert all(isinstance(h, RecallHit) for h in hits)
    # The recall request the router saw should carry our kwargs. Note the
    # router over-fetches per-store (k*4), so we don't check k directly.
    sent = mock.recall_calls[0]
    assert sent.query == "anything"
    assert sent.agent_id == "a"


async def test_recall_passes_types_and_filter() -> None:
    """``types`` and ``filter`` kwargs are forwarded to the request."""
    mock = MockStore()
    mem = Memory(agent_id="a", stores=[mock])

    await mem.recall(
        "q",
        types=[MemoryType.SEMANTIC],
        filter={"user_id": "u"},
        fresher_than_days=30,
    )

    sent = mock.recall_calls[0]
    assert sent.types == [MemoryType.SEMANTIC]
    assert sent.filter == {"user_id": "u"}
    assert sent.fresher_than_days == 30


async def test_forget_by_ids_dispatches() -> None:
    """``forget(ids=[...])`` routes a populated :class:`ForgetRequest`."""
    mock = MockStore()
    mem = Memory(agent_id="a", stores=[mock])

    resp = await mem.forget(ids=["id-1", "id-2"], reason="cleanup")

    assert resp.forgotten_ids == ["id-1", "id-2"]
    sent = mock.forget_calls[0]
    assert sent.ids == ["id-1", "id-2"]
    assert sent.reason == "cleanup"


async def test_forget_without_scope_raises() -> None:
    """No ids and no filter → :class:`ValueError`, no router call."""
    mock = MockStore()
    mem = Memory(agent_id="a", stores=[mock])
    with pytest.raises(ValueError, match="forget requires"):
        await mem.forget()
    assert mock.forget_calls == []


async def test_merge_round_trip() -> None:
    """``merge(canonical, [dups])`` routes a :class:`MergeRequest`."""
    mock = MockStore()
    mem = Memory(agent_id="a", stores=[mock])

    resp = await mem.merge("canon", ["d1", "d2"], strategy=MergeStrategy.MERGE_CONTENT)

    assert resp.merged_count == 2
    sent = mock.merge_calls[0]
    assert sent.canonical == "canon"
    assert sent.duplicates == ["d1", "d2"]
    assert sent.strategy is MergeStrategy.MERGE_CONTENT


async def test_expire_round_trip() -> None:
    """``expire(policy=...)`` parses the policy and routes the request."""
    mock = MockStore()
    mem = Memory(agent_id="a", stores=[mock])

    resp = await mem.expire({"older_than_days": 90}, action=ExpireAction.FORGET)

    assert isinstance(resp, ExpireResponse)
    sent = mock.expire_calls[0]
    assert sent.policy is not None
    assert sent.policy.older_than_days == 90
    assert sent.action is ExpireAction.FORGET


async def test_health_returns_router_shape() -> None:
    """``health()`` returns the router-aggregated dict shape."""
    mock = MockStore()
    mem = Memory(agent_id="a", stores=[mock])

    health = await mem.health()

    assert health["status"] == "ok"
    assert health["backend"] == "memory-router"
    assert isinstance(health["stores"], list)
    assert health["stores"][0]["backend"] == "mock"


def test_capabilities_is_union_of_children() -> None:
    """``Memory.capabilities`` is the set-union of every child's capabilities."""
    s1 = MockStore(backend_name="s1", capabilities={Capability.SEMANTIC, Capability.VECTOR})
    s2 = MockStore(backend_name="s2", capabilities={Capability.EPISODIC, Capability.GRAPH})
    mem = Memory(agent_id="a", stores=[s1, s2])

    assert mem.capabilities == {
        Capability.SEMANTIC,
        Capability.VECTOR,
        Capability.EPISODIC,
        Capability.GRAPH,
    }


async def test_close_invokes_child_close() -> None:
    """``close()`` calls ``close`` on any child store that exposes it."""
    s1 = MockStore(backend_name="s1")
    s2 = MockStore(backend_name="s2")
    mem = Memory(agent_id="a", stores=[s1, s2])

    await mem.close()

    assert s1.closed is True
    assert s2.closed is True


async def test_close_tolerates_missing_close_method() -> None:
    """Stores without ``close`` are skipped silently."""

    class Closeless:
        """A :class:`MemoryStore` without a ``close`` method."""

        BACKEND_NAME = "closeless"

        @property
        def capabilities(self) -> set[str]:
            return {Capability.SEMANTIC}

        async def remember(self, req: RememberRequest) -> RememberResponse:  # pragma: no cover
            raise NotImplementedError

        async def recall(self, req: RecallRequest) -> RecallResponse:  # pragma: no cover
            raise NotImplementedError

        async def forget(self, req: ForgetRequest) -> ForgetResponse:  # pragma: no cover
            raise NotImplementedError

        async def merge(self, req: MergeRequest) -> MergeResponse:  # pragma: no cover
            raise NotImplementedError

        async def expire(self, req: ExpireRequest) -> ExpireResponse:  # pragma: no cover
            raise NotImplementedError

        async def health(self) -> dict[str, Any]:  # pragma: no cover
            return {"status": "ok", "backend": self.BACKEND_NAME}

    closeless = Closeless()
    assert isinstance(closeless, MemoryStore)  # sanity — structural Protocol
    mem = Memory(agent_id="a", stores=[closeless])

    # Should not raise.
    await mem.close()
