"""Tests for :mod:`memwire.transformer` â€” the STMâ†”LTM consolidator (Phase 5).

The transformer is an always-on async background task that promotes
high-value short-term memory entries to long-term storage via a
:class:`memwire.store.MemoryStore`-shaped target. These tests exercise:

* the in-buffer ``push`` / ``record_recall`` shapes;
* the consolidation algorithm in :meth:`STMToLTMTransformer.tick`;
* the built-in scoring heuristic and the pluggable-scorer hook;
* the ``start`` / ``stop`` / async-context-manager lifecycle;
* concurrency safety under :func:`asyncio.gather`.

All tests run under ``asyncio_mode = "auto"`` (see ``pyproject.toml``), so
no explicit ``@pytest.mark.asyncio`` decorator is required.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from memwire.models import (
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    MemoryType,
    MergeRequest,
    MergeResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)
from memwire.store import Capability
from memwire.transformer import STMItem, STMToLTMTransformer

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeTargetStore:
    """Minimal :class:`MemoryStore`-shaped target for transformer tests.

    Records every ``remember`` / ``forget`` call. ``remember`` returns a
    deterministic response unless ``raise_on_remember`` is set, in which
    case it raises :class:`RuntimeError` on every invocation.
    """

    BACKEND_NAME = "fake-target"

    def __init__(self, *, raise_on_remember: bool = False) -> None:
        self._raise_on_remember = raise_on_remember
        self.remember_calls: list[RememberRequest] = []
        self.forget_calls: list[ForgetRequest] = []

    @property
    def capabilities(self) -> set[str]:
        return {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.PROCEDURAL,
            Capability.EMOTIONAL,
        }

    async def remember(self, req: RememberRequest) -> RememberResponse:
        if self._raise_on_remember:
            raise RuntimeError("target.remember boom")
        self.remember_calls.append(req)
        return RememberResponse(
            id=f"ltm-{len(self.remember_calls)}",
            stored_at=1_700_000_000_000,
            stores=[self.BACKEND_NAME],
            pending_approval=False,
        )

    # The remaining MemoryStore methods are unused by the transformer; we
    # implement them as no-ops so this class still satisfies the Protocol
    # for static type-checkers via duck-typing.
    async def recall(self, req: RecallRequest) -> RecallResponse:  # pragma: no cover
        raise NotImplementedError

    async def forget(self, req: ForgetRequest) -> ForgetResponse:  # pragma: no cover
        self.forget_calls.append(req)
        raise NotImplementedError

    async def merge(self, req: MergeRequest) -> MergeResponse:  # pragma: no cover
        raise NotImplementedError

    async def expire(self, req: ExpireRequest) -> ExpireResponse:  # pragma: no cover
        raise NotImplementedError

    async def health(self) -> dict[str, Any]:  # pragma: no cover
        return {"status": "ok", "backend": self.BACKEND_NAME}


def _make_item(
    *,
    importance: float = 0.8,
    pushed_at_ms: int | None = None,
    recall_count: int = 0,
    metadata: dict[str, Any] | None = None,
    type: MemoryType = MemoryType.SEMANTIC,
) -> STMItem:
    """Construct an STMItem with test-friendly defaults."""
    fields: dict[str, Any] = {
        "content": "hello",
        "agent_id": "agent-a",
        "user_id": None,
        "type": type,
        "importance": importance,
        "metadata": metadata,
        "recall_count": recall_count,
    }
    if pushed_at_ms is not None:
        fields["pushed_at"] = pushed_at_ms
    return STMItem(**fields)


# ---------------------------------------------------------------------------
# 1. Constructor + push behaviour
# ---------------------------------------------------------------------------


async def test_push_adds_to_stm_buffer() -> None:
    """``push()`` returns an STMItem and increments the buffer size."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(target=target, cadence_seconds=60.0, stm_max_size=100)
    assert t.stm_size == 0

    item1 = await t.push(content="a", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=0.5)
    item2 = await t.push(content="b", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=0.9)

    assert isinstance(item1, STMItem)
    assert isinstance(item2, STMItem)
    assert item1.id != item2.id
    assert t.stm_size == 2


# ---------------------------------------------------------------------------
# 2. tick() consolidates high-importance items
# ---------------------------------------------------------------------------


async def test_tick_consolidates_high_importance_item() -> None:
    """An item with importance well above threshold writes to the target."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(
        target=target,
        cadence_seconds=60.0,
        stm_max_size=100,
        importance_threshold=0.5,
    )

    await t.push(
        content="critical fact",
        agent_id="agent-a",
        user_id="user-1",
        type=MemoryType.SEMANTIC,
        importance=1.0,
        metadata={"k": "v"},
    )

    result = await t.tick()

    assert result.consolidated == 1
    assert result.evicted == 0
    assert result.skipped == 0
    assert result.errors == []
    assert t.stm_size == 0

    # Verify the target saw a properly-shaped RememberRequest.
    assert len(target.remember_calls) == 1
    call = target.remember_calls[0]
    assert call.content == "critical fact"
    assert call.agent_id == "agent-a"
    assert call.user_id == "user-1"
    assert call.type is MemoryType.SEMANTIC
    assert call.metadata == {"k": "v"}
    # Confidence carries the computed score back into the LTM record.
    assert call.confidence is not None
    assert 0.0 <= call.confidence <= 1.0


# ---------------------------------------------------------------------------
# 3. low-importance + recent â†’ skipped
# ---------------------------------------------------------------------------


async def test_tick_skips_low_importance_recent_item() -> None:
    """A recent low-importance item stays in STM and is counted as skipped."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(
        target=target,
        cadence_seconds=60.0,
        importance_threshold=0.6,
    )

    # importance=0.0, fresh -> below threshold but not aged out.
    await t.push(content="meh", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=0.0)

    result = await t.tick()

    assert result.consolidated == 0
    assert result.evicted == 0
    assert result.skipped == 1
    assert t.stm_size == 1
    assert target.remember_calls == []


# ---------------------------------------------------------------------------
# 4. low-importance + aged out â†’ evicted
# ---------------------------------------------------------------------------


async def test_tick_evicts_low_importance_aged_item() -> None:
    """An aged-out low-importance item is dropped and fires on_evict."""
    target = FakeTargetStore()

    # Make the item look old by stuffing pushed_at in the deep past via a
    # frozen clock that's 10x cadence further along.
    cadence = 0.1
    fixed_now = time.time()
    # Build the transformer with a clock that returns ``fixed_now``.
    evictions: list[STMItem] = []

    async def on_evict(it: STMItem) -> None:
        evictions.append(it)

    t = STMToLTMTransformer(
        target=target,
        cadence_seconds=cadence,
        importance_threshold=0.6,
        on_evict=on_evict,
        clock=lambda: fixed_now,
    )

    # Push then manually backdate the item's pushed_at to simulate age.
    item = await t.push(
        content="ancient",
        agent_id="agent-a",
        type=MemoryType.SEMANTIC,
        importance=0.0,
    )
    item.pushed_at = int((fixed_now - cadence * 100) * 1000)

    result = await t.tick()

    assert result.consolidated == 0
    assert result.evicted == 1
    assert result.skipped == 0
    assert t.stm_size == 0
    assert len(evictions) == 1
    assert evictions[0].id == item.id


# ---------------------------------------------------------------------------
# 5. Built-in scorer math
# ---------------------------------------------------------------------------


def test_default_scorer_math() -> None:
    """Reproduce the heuristic spelled out in the docstring."""
    target = FakeTargetStore()
    fixed_now = 1_000_000.0  # seconds
    t = STMToLTMTransformer(target=target, clock=lambda: fixed_now)

    # Construct an item that's exactly 60 seconds old, importance 0.8, two
    # recalls, user-flagged.
    item = _make_item(
        importance=0.8,
        pushed_at_ms=int((fixed_now - 60.0) * 1000),
        recall_count=2,
        metadata={"user_flagged": True},
    )

    # Manually compute the expected score:
    #   importance term : 0.5 * 0.8                       = 0.40
    #   recall term     : 0.2 * min(1, 2/5)               = 0.08
    #   recency term    : 0.2 * max(0, 1 - 60/3600)       = 0.2 * (59/60)
    #                                                     â‰ˆ 0.19666...
    #   flagged term    : 0.1 * 1                         = 0.10
    expected = 0.5 * 0.8 + 0.2 * min(1.0, 2 / 5) + 0.2 * max(0.0, 1.0 - 60.0 / 3600.0) + 0.1
    score = t._default_scorer(item)
    assert score == pytest.approx(expected, rel=1e-9, abs=1e-9)


def test_default_scorer_clamps_above_one() -> None:
    """The safe-scoring wrapper clamps to [0, 1]."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(target=target, scorer=lambda _it: 1.5)
    item = _make_item()
    assert t._safe_score(item) == 1.0


def test_default_scorer_clamps_below_zero() -> None:
    """The safe-scoring wrapper clamps negative scores to 0."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(target=target, scorer=lambda _it: -0.5)
    item = _make_item()
    assert t._safe_score(item) == 0.0


# ---------------------------------------------------------------------------
# 6. Pluggable scorer
# ---------------------------------------------------------------------------


async def test_pluggable_scorer_always_one_consolidates_everything() -> None:
    """A custom scorer returning 1.0 promotes every item to LTM."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(
        target=target,
        importance_threshold=0.5,
        scorer=lambda _it: 1.0,
    )
    # Push three items with low importance â€” but the custom scorer ignores
    # the importance field entirely.
    for content in ("a", "b", "c"):
        await t.push(
            content=content,
            agent_id="agent-a",
            type=MemoryType.SEMANTIC,
            importance=0.0,
        )

    result = await t.tick()

    assert result.consolidated == 3
    assert result.evicted == 0
    assert result.skipped == 0
    assert t.stm_size == 0
    assert len(target.remember_calls) == 3


# ---------------------------------------------------------------------------
# 7. Custom clock
# ---------------------------------------------------------------------------


async def test_custom_clock_drives_recency_calculation() -> None:
    """Injecting a fast-forward clock makes an item age out immediately."""
    target = FakeTargetStore()

    # We control time entirely. After push, advance the clock so the item
    # appears to be hours old; with the default scorer, low importance +
    # zero recency credit yields a score below threshold, and the age
    # exceeds cadence*2, so the item is evicted.
    state = {"now": 1_000_000.0}

    def clock() -> float:
        return state["now"]

    evictions: list[STMItem] = []

    async def on_evict(it: STMItem) -> None:
        evictions.append(it)

    t = STMToLTMTransformer(
        target=target,
        cadence_seconds=60.0,
        importance_threshold=0.6,
        on_evict=on_evict,
        clock=clock,
    )

    item = await t.push(content="x", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=0.0)
    # Backdate the push timestamp to align with the simulated clock.
    item.pushed_at = int(state["now"] * 1000)

    # Advance the clock by 1 hour â€” > cadence*2 = 120 s, so it's "aged out".
    state["now"] += 3600.0

    result = await t.tick()
    assert result.evicted == 1
    assert len(evictions) == 1


# ---------------------------------------------------------------------------
# 8. on_consolidate callback fires
# ---------------------------------------------------------------------------


async def test_on_consolidate_callback_fires_with_pair() -> None:
    """The on_consolidate callback receives the (item, response) pair."""
    target = FakeTargetStore()
    seen: list[tuple[STMItem, RememberResponse]] = []

    async def on_consolidate(item: STMItem, response: RememberResponse) -> None:
        seen.append((item, response))

    t = STMToLTMTransformer(
        target=target,
        importance_threshold=0.5,
        on_consolidate=on_consolidate,
        scorer=lambda _it: 1.0,
    )

    item = await t.push(content="x", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=1.0)
    await t.tick()

    assert len(seen) == 1
    cb_item, cb_resp = seen[0]
    assert cb_item.id == item.id
    assert isinstance(cb_resp, RememberResponse)
    assert cb_resp.id.startswith("ltm-")


# ---------------------------------------------------------------------------
# 9. target.remember exception â†’ recorded in errors, item stays
# ---------------------------------------------------------------------------


async def test_remember_exception_recorded_and_item_kept() -> None:
    """A target that raises produces an error row; item stays in STM."""
    target = FakeTargetStore(raise_on_remember=True)
    t = STMToLTMTransformer(
        target=target,
        importance_threshold=0.5,
        scorer=lambda _it: 1.0,
    )

    item = await t.push(content="x", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=1.0)

    result = await t.tick()

    assert result.consolidated == 0
    assert result.errors and result.errors[0][0] == item.id
    assert "RuntimeError" in result.errors[0][1]
    # Item still in STM for retry next tick.
    assert t.stm_size == 1


# ---------------------------------------------------------------------------
# 10. start() / stop() lifecycle
# ---------------------------------------------------------------------------


async def test_start_and_stop_lifecycle_runs_final_drain() -> None:
    """``stop()`` cancels the loop and runs a final drain tick."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(
        target=target,
        cadence_seconds=0.01,
        importance_threshold=0.5,
        scorer=lambda _it: 1.0,
    )

    await t.start()
    assert t._task is not None and not t._task.done()

    # Push something so the drain tick has work to do.
    await t.push(content="x", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=1.0)

    await t.stop()
    # Task is cleared and the buffer was drained.
    assert t._task is None
    assert t.stm_size == 0
    assert len(target.remember_calls) >= 1


# ---------------------------------------------------------------------------
# 11. start() twice is idempotent
# ---------------------------------------------------------------------------


async def test_start_twice_is_a_noop() -> None:
    """Calling ``start()`` while already running does not spawn a second task."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(target=target, cadence_seconds=0.01)

    await t.start()
    first_task = t._task
    assert first_task is not None

    await t.start()
    second_task = t._task
    assert second_task is first_task

    await t.stop()


# ---------------------------------------------------------------------------
# 12. stm_max_size overflow triggers an immediate tick
# ---------------------------------------------------------------------------


async def test_overflow_triggers_immediate_tick() -> None:
    """Pushing past ``stm_max_size`` schedules a background tick immediately."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(
        target=target,
        cadence_seconds=60.0,
        stm_max_size=2,
        importance_threshold=0.5,
        scorer=lambda _it: 1.0,
    )

    # First push: under threshold, no tick.
    await t.push(content="a", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=1.0)
    # Second push: hits threshold (len >= stm_max_size), tick scheduled.
    await t.push(content="b", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=1.0)

    # Yield to the event loop so the create_task'd tick can run to
    # completion. A single zero-delay sleep is sufficient â€” tick() doesn't
    # await anything blocking under our FakeTargetStore.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(target.remember_calls) == 2
    assert t.stm_size == 0


# ---------------------------------------------------------------------------
# 13. Async context manager
# ---------------------------------------------------------------------------


async def test_async_context_manager_starts_and_stops() -> None:
    """``async with`` form starts on enter and stops + drains on exit."""
    target = FakeTargetStore()
    async with STMToLTMTransformer(
        target=target,
        cadence_seconds=0.01,
        importance_threshold=0.5,
        scorer=lambda _it: 1.0,
    ) as t:
        assert t._task is not None and not t._task.done()
        await t.push(content="x", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=1.0)

    # After exit the task is gone and the drain ran.
    assert t._task is None
    assert t.stm_size == 0
    assert len(target.remember_calls) >= 1


# ---------------------------------------------------------------------------
# 14. record_recall semantics
# ---------------------------------------------------------------------------


async def test_record_recall_increments_existing_item() -> None:
    """``record_recall()`` bumps the recall_count of an item still in STM."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(target=target)

    item = await t.push(content="x", agent_id="agent-a", type=MemoryType.SEMANTIC, importance=0.5)
    assert item.recall_count == 0

    ok = await t.record_recall(item.id)
    assert ok is True
    # Snapshot reflects the bump.
    snapshot = t.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].recall_count == 1


async def test_record_recall_unknown_id_is_noop() -> None:
    """``record_recall()`` for an unknown id returns False, no mutation."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(target=target)

    ok = await t.record_recall("does-not-exist")
    assert ok is False


# ---------------------------------------------------------------------------
# 15. Concurrent push() under asyncio.gather
# ---------------------------------------------------------------------------


async def test_concurrent_push_does_not_race() -> None:
    """N concurrent pushes all land in the buffer with distinct ids."""
    target = FakeTargetStore()
    t = STMToLTMTransformer(
        target=target,
        cadence_seconds=60.0,
        stm_max_size=10_000,  # avoid triggering an overflow tick mid-test
        importance_threshold=0.5,
    )

    n = 50

    async def one_push(i: int) -> STMItem:
        return await t.push(
            content=f"content-{i}",
            agent_id="agent-a",
            type=MemoryType.SEMANTIC,
            importance=0.5,
        )

    items = await asyncio.gather(*(one_push(i) for i in range(n)))

    assert len(items) == n
    assert len({it.id for it in items}) == n  # all distinct
    assert t.stm_size == n
