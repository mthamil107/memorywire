"""Tests for the :class:`amp.store.MemoryStore` Protocol.

We define a tiny in-memory ``MockStore`` here (not in ``src/`` — adapters
under ``src/amp/store/`` are Phase 3 deliverables) and use it both to
sanity-check the Protocol's structural shape and to exercise the
round-trip path through the request/response models.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

from amp.models import (
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    MemoryRecord,
    MemoryType,
    MergeRequest,
    MergeResponse,
    RecallHit,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)
from amp.store import Capability, MemoryStore


def _now_ms() -> int:
    """Return the current Unix time in milliseconds (AMP timestamp format)."""
    return int(time.time() * 1000)


class MockStore:
    """In-memory reference implementation of :class:`MemoryStore`.

    Used only inside the test suite. The store keeps records in a flat dict
    keyed by id and runs naive substring matching for ``recall``. It is
    deliberately small — adapters under :mod:`amp.store` carry the real
    semantics.
    """

    BACKEND_NAME = "mock"

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    # ------------------------------------------------------------------
    # MemoryStore Protocol surface
    # ------------------------------------------------------------------

    async def remember(self, req: RememberRequest) -> RememberResponse:
        """Store one memory and return the response.

        Uses :func:`uuid.uuid4` for ids — spec-gap: uuid7 is preferred for
        time-ordered ids but is not in the Python stdlib yet (added in
        3.14). When the runtime is 3.14+ the implementation should switch
        to ``uuid.uuid7``.
        """
        record_id = str(uuid.uuid4())
        stored_at = _now_ms()
        self._records[record_id] = MemoryRecord(
            id=record_id,
            agent_id=req.agent_id,
            user_id=req.user_id,
            type=req.type,
            content=req.content,
            metadata=req.metadata,
            confidence=req.confidence,
            source=req.source,
            created_at=stored_at,
            expires_at=req.expires_at,
        )
        return RememberResponse(
            id=record_id,
            stored_at=stored_at,
            stores=[self.BACKEND_NAME],
            pending_approval=False,
            approval_url=None,
        )

    async def recall(self, req: RecallRequest) -> RecallResponse:
        """Return up to ``k`` records whose content matches the query string."""
        started_ms = _now_ms()
        needle = req.query.lower()
        k = req.k if req.k is not None else 5
        type_filter = set(req.types) if req.types else None

        hits: list[RecallHit] = []
        for rec in self._records.values():
            if rec.agent_id != req.agent_id:
                continue
            if type_filter is not None and rec.type not in type_filter:
                continue
            if needle not in rec.content.lower():
                continue
            hits.append(
                RecallHit(
                    id=rec.id,
                    type=rec.type,
                    content=rec.content,
                    score=1.0,
                    metadata=rec.metadata,
                    created_at=rec.created_at,
                    supporting=[],
                    source_store=self.BACKEND_NAME,
                )
            )
            if len(hits) >= k:
                break

        return RecallResponse(
            results=hits,
            fusion_used=req.fusion
            if req.fusion is not None
            else __import__("amp.models", fromlist=["FusionAlgorithm"]).FusionAlgorithm.RRF,
            stores_queried=[self.BACKEND_NAME],
            latency_ms=max(_now_ms() - started_ms, 0),
        )

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        """Remove records by id or by a flat key/value filter."""
        from amp.models import ForgetStoreResult

        target_ids: list[str] = []
        if req.ids:
            target_ids.extend(rid for rid in req.ids if rid in self._records)
        if req.filter:
            for rid, rec in self._records.items():
                if rid in target_ids:
                    continue
                if _matches_filter(rec, req.filter):
                    target_ids.append(rid)

        for rid in target_ids:
            self._records.pop(rid, None)

        return ForgetResponse(
            forgotten_ids=target_ids,
            hard_delete=bool(req.hard_delete),
            stores=[ForgetStoreResult(store=self.BACKEND_NAME, count=len(target_ids))],
            pending_approval=False,
            approval_url=None,
        )

    async def merge(self, req: MergeRequest) -> MergeResponse:
        """Stub: drop the duplicates, keep the canonical id."""
        from amp.models import MergeStrategy

        removed = 0
        for dup_id in req.duplicates:
            if self._records.pop(dup_id, None) is not None:
                removed += 1
        strategy = req.strategy if req.strategy is not None else MergeStrategy.KEEP_CANONICAL
        return MergeResponse(
            canonical=req.canonical,
            merged_count=removed,
            strategy_used=strategy,
            stores=[self.BACKEND_NAME],
        )

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        """Stub: count matching rows, perform no mutation."""
        from amp.models import ExpireAction

        matched = sum(
            1
            for rec in self._records.values()
            if req.policy is None or _policy_matches(rec, req.policy)
        )
        action = req.action if req.action is not None else ExpireAction.FORGET
        return ExpireResponse(
            matched_count=matched,
            action_taken=action,
            stores=[self.BACKEND_NAME],
        )

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "backend": self.BACKEND_NAME}

    @property
    def capabilities(self) -> set[str]:
        return {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.PROCEDURAL,
            Capability.EMOTIONAL,
        }


# ---------------------------------------------------------------------------
# Filter helpers — pulled out of MockStore for readability.
# ---------------------------------------------------------------------------


def _matches_filter(rec: MemoryRecord, flt: dict[str, Any]) -> bool:
    """Flat key/value match against record metadata + top-level fields.

    Used by :meth:`MockStore.forget` to resolve filter-only delete requests.
    """
    metadata = rec.metadata or {}
    for key, value in flt.items():
        if key == "type":
            if rec.type.value != value and rec.type != value:
                return False
            continue
        top = getattr(rec, key, None)
        if top is not None:
            if top != value:
                return False
            continue
        if metadata.get(key) != value:
            return False
    return True


def _policy_matches(rec: MemoryRecord, policy: Any) -> bool:
    """Apply a (subset of) :class:`ExpirePolicy` to a record."""
    if policy.type is not None and rec.type != policy.type:
        return False
    return not (
        policy.confidence_below is not None
        and (rec.confidence is None or rec.confidence >= policy.confidence_below)
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mockstore_is_a_memory_store() -> None:
    """``isinstance`` against the ``@runtime_checkable`` Protocol must succeed."""
    assert isinstance(MockStore(), MemoryStore)


async def test_remember_then_recall_returns_record() -> None:
    """A round-trip through ``remember`` + ``recall`` returns the same content."""
    store = MockStore()
    write = await store.remember(
        RememberRequest(
            agent_id="agent-1",
            type=MemoryType.SEMANTIC,
            content="Alice is allergic to peanuts.",
            user_id="user-a",
        )
    )
    assert write.pending_approval is False
    assert write.stores == [MockStore.BACKEND_NAME]
    assert write.id  # non-empty

    read = await store.recall(RecallRequest(agent_id="agent-1", query="peanut", k=5))
    assert len(read.results) == 1
    hit = read.results[0]
    assert hit.id == write.id
    assert hit.type is MemoryType.SEMANTIC
    assert "peanut" in str(hit.content).lower()
    assert hit.source_store == MockStore.BACKEND_NAME


async def test_forget_by_id_removes_record() -> None:
    """Forgetting by explicit id list deletes the record and reports it."""
    store = MockStore()
    write = await store.remember(
        RememberRequest(
            agent_id="agent-2",
            type=MemoryType.EPISODIC,
            content="Deploy run #42 retried twice.",
        )
    )
    result = await store.forget(ForgetRequest(agent_id="agent-2", ids=[write.id]))
    assert result.forgotten_ids == [write.id]
    assert result.hard_delete is False
    assert result.stores[0].store == MockStore.BACKEND_NAME
    assert result.stores[0].count == 1

    # The record should be gone.
    follow = await store.recall(RecallRequest(agent_id="agent-2", query="deploy"))
    assert follow.results == []


async def test_forget_by_filter_removes_matching_records() -> None:
    """A filter-only forget must resolve matching ids itself."""
    store = MockStore()
    await store.remember(
        RememberRequest(
            agent_id="agent-3",
            user_id="alice@example.com",
            type=MemoryType.EPISODIC,
            content="Alice booked a flight.",
        )
    )
    await store.remember(
        RememberRequest(
            agent_id="agent-3",
            user_id="bob@example.com",
            type=MemoryType.EPISODIC,
            content="Bob booked a flight.",
        )
    )
    result = await store.forget(
        ForgetRequest(
            agent_id="agent-3",
            filter={"user_id": "alice@example.com", "type": "episodic"},
        )
    )
    assert len(result.forgotten_ids) == 1
    assert result.stores[0].count == 1


def test_capabilities_set_is_expected() -> None:
    """The capability set matches the documented baseline for the mock."""
    assert MockStore().capabilities == {
        Capability.SEMANTIC,
        Capability.EPISODIC,
        Capability.PROCEDURAL,
        Capability.EMOTIONAL,
    }


async def test_health_reports_status() -> None:
    """``health`` returns the canonical status object."""
    health = await MockStore().health()
    assert health == {"status": "ok", "backend": "mock"}


@pytest.mark.parametrize("strategy_value", ["keep_canonical", "merge_content"])
async def test_merge_drops_duplicates(strategy_value: str) -> None:
    """``merge`` removes duplicate rows and reports the strategy used."""
    from amp.models import MergeStrategy

    store = MockStore()
    write_a = await store.remember(
        RememberRequest(agent_id="agent-4", type=MemoryType.SEMANTIC, content="Alice (canon)")
    )
    write_b = await store.remember(
        RememberRequest(agent_id="agent-4", type=MemoryType.SEMANTIC, content="alice (dup)")
    )
    result = await store.merge(
        MergeRequest(
            agent_id="agent-4",
            canonical=write_a.id,
            duplicates=[write_b.id],
            strategy=MergeStrategy(strategy_value),
        )
    )
    assert result.merged_count == 1
    assert result.canonical == write_a.id
    assert result.strategy_used is MergeStrategy(strategy_value)
