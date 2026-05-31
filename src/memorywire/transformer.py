"""STMâ†”LTM transformer â€” consolidate short-term memory into long-term storage.

This is the reference implementation for the consolidator sketched in
:file:`docs/kickoff/ARCHITECTURE.md` Â§7. The transformer is an always-on
async background task that:

1. Watches an in-memory STM (short-term memory) buffer of recent ops.
2. On a configurable cadence (default 60 s) *or* when the STM grows past a
   threshold (default 100 items), scores each item with a heuristic
   (importance + recency + recall-frequency + a user-flag bump). Items
   above ``importance_threshold`` get written to LTM via the configured
   target (a router or single store). Low-scored items that have aged out
   are evicted with an optional callback so the governance UI can surface
   them for human review.
3. Surfaces consolidation and eviction decisions via two async callbacks
   (``on_consolidate`` / ``on_evict``) for observability and governance
   hooks.

Design notes
------------
* The transformer is *not* itself a :class:`memorywire.store.MemoryStore` â€” it is a
  layer in *front* of one. The ``target`` argument is duck-typed against
  the :class:`MemoryStore` protocol's :meth:`remember` method; either an
  individual store or a :class:`memorywire.router.MemoryRouter` works.
* All mutation of the STM buffer is guarded by an :class:`asyncio.Lock` so
  concurrent ``push`` / ``tick`` / ``record_recall`` calls cannot race.
* The background task created by :meth:`start` is cancellable and
  idempotent â€” calling ``start()`` twice is a no-op; ``stop()`` cancels,
  awaits termination, suppresses the cancel exception, and runs one final
  drain ``tick`` so anything still in STM gets a last consolidation pass.
* The built-in scorer matches the formula spelled out in the task brief â€”
  it is intentionally simple. Production deployments should pass a custom
  ``scorer`` callable.
* :func:`time.time` is the default clock; tests can inject a deterministic
  callable via the ``clock`` constructor kwarg.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from memorywire.models import MemoryType, RememberRequest, RememberResponse
from memorywire.store.base import MemoryStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# STMItem â€” pydantic model for in-buffer entries
# ---------------------------------------------------------------------------


def _new_id() -> str:
    """Return a fresh uuid hex string for a new STM item id."""
    return uuid.uuid4().hex


def _now_ms() -> int:
    """Return the current Unix time in milliseconds (memorywire timestamp format)."""
    return int(time.time() * 1000)


class STMItem(BaseModel):
    """A single short-term-memory buffer entry.

    Fields mirror the constructor arguments of :meth:`STMToLTMTransformer.push`
    plus a server-side ``id``, ``pushed_at`` timestamp, and a mutable
    ``recall_count`` used by the built-in scorer.
    """

    # Mirror the memorywire-wide model config (forward-compatible extras, alias
    # population, retain enum identity) so this model behaves consistently
    # with the rest of the package.
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        use_enum_values=False,
    )

    id: str = Field(default_factory=_new_id)
    content: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1, max_length=256)
    user_id: str | None = Field(default=None, max_length=256)
    type: MemoryType
    importance: float = Field(..., ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None
    # Unix epoch milliseconds.
    pushed_at: int = Field(default_factory=_now_ms)
    recall_count: int = 0


# ---------------------------------------------------------------------------
# TickResult â€” return value of a consolidation pass
# ---------------------------------------------------------------------------


@dataclass
class TickResult:
    """Aggregate result of a single :meth:`STMToLTMTransformer.tick` pass.

    Attributes
    ----------
    consolidated:
        Number of items written to LTM via the target.
    evicted:
        Number of items dropped without consolidation (low score + aged out).
    skipped:
        Number of items left in STM untouched (low score but still young).
    errors:
        ``(item_id, exception_repr)`` pairs for items that raised during
        consolidation. Such items stay in STM so a later tick can retry.
    """

    consolidated: int = 0
    evicted: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ScorerFn = Callable[[STMItem], float]
ClockFn = Callable[[], float]
OnEvictFn = Callable[[STMItem], Awaitable[None]]
OnConsolidateFn = Callable[[STMItem, RememberResponse], Awaitable[None]]


# ---------------------------------------------------------------------------
# STMToLTMTransformer
# ---------------------------------------------------------------------------


class STMToLTMTransformer:
    """Background consolidator that promotes high-value STM entries to LTM.

    Parameters
    ----------
    target:
        Anything implementing :class:`memorywire.store.MemoryStore`'s ``remember``
        method. Typically a :class:`memorywire.router.MemoryRouter`.
    cadence_seconds:
        Minimum interval between background :meth:`tick` passes. Also acts
        as the basis for the "aged out" eviction threshold
        (``cadence_seconds * 2``).
    stm_max_size:
        Once the STM buffer grows beyond this length, a tick is scheduled
        immediately rather than waiting for the cadence.
    importance_threshold:
        Score at or above which an item gets ``remember()``-ed; below
        which it is either kept (if still young) or evicted (if aged out).
    on_evict:
        Optional async callback fired with the :class:`STMItem` whenever an
        item is dropped without consolidation. Intended for governance UI
        surfacing of the "co-memorize" loop.
    on_consolidate:
        Optional async callback fired with ``(item, response)`` after every
        successful :meth:`remember` call. Intended for observability.
    scorer:
        Optional pluggable scoring function. Defaults to the built-in
        heuristic described in the module docstring.
    clock:
        Optional wallclock provider returning seconds since the epoch.
        Defaults to :func:`time.time`. Injectable for tests.
    """

    def __init__(
        self,
        target: MemoryStore,
        *,
        cadence_seconds: float = 60.0,
        stm_max_size: int = 100,
        importance_threshold: float = 0.6,
        on_evict: OnEvictFn | None = None,
        on_consolidate: OnConsolidateFn | None = None,
        scorer: ScorerFn | None = None,
        clock: ClockFn | None = None,
    ) -> None:
        self._target: MemoryStore = target
        self._cadence_seconds: float = float(cadence_seconds)
        self._stm_max_size: int = int(stm_max_size)
        self._importance_threshold: float = float(importance_threshold)
        self._on_evict: OnEvictFn | None = on_evict
        self._on_consolidate: OnConsolidateFn | None = on_consolidate
        self._scorer: ScorerFn = scorer if scorer is not None else self._default_scorer
        self._clock: ClockFn = clock if clock is not None else time.time

        # The buffer itself. Deque gives O(1) push and arbitrary remove via
        # rebuild â€” we don't expect deletions in the hot path because tick
        # rebuilds the buffer with only the kept items.
        self._stm: deque[STMItem] = deque()
        # Guards every mutation of self._stm. async-aware so push/tick can
        # interleave with await points cleanly.
        self._lock: asyncio.Lock = asyncio.Lock()
        # The background task spawned by start(); None until then.
        self._task: asyncio.Task[None] | None = None
        # Sentinel so start() is idempotent without checking task state.
        self._started: bool = False
        # Tracks tick() tasks created by push() overflow so they're not
        # garbage-collected mid-flight (per asyncio.create_task contract).
        self._pending_ticks: set[asyncio.Task[TickResult]] = set()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def stm_size(self) -> int:
        """Current number of items in the STM buffer.

        Read-only snapshot; safe to call without holding the lock because
        :meth:`deque.__len__` is GIL-atomic in CPython.
        """
        return len(self._stm)

    def snapshot(self) -> list[STMItem]:
        """Return a list copy of the current STM buffer (for tests / UI)."""
        return list(self._stm)

    # ------------------------------------------------------------------
    # push / record_recall
    # ------------------------------------------------------------------

    async def push(
        self,
        *,
        content: str,
        agent_id: str,
        user_id: str | None = None,
        type: MemoryType,
        importance: float,
        metadata: dict[str, Any] | None = None,
    ) -> STMItem:
        """Add a new entry to the STM buffer.

        If the buffer's length is at or above :attr:`stm_max_size` after
        the new item is appended, a background :meth:`tick` is scheduled
        immediately (via :func:`asyncio.create_task`) so we don't outrun
        the cadence in burst workloads.
        """
        item = STMItem(
            content=content,
            agent_id=agent_id,
            user_id=user_id,
            type=type,
            importance=importance,
            metadata=metadata,
            # id, pushed_at, recall_count are defaulted by the model.
        )
        async with self._lock:
            self._stm.append(item)
            overflow = len(self._stm) >= self._stm_max_size
        if overflow:
            # Fire-and-forget a tick. We don't await it so push() stays
            # cheap; the tick itself acquires the lock and runs to
            # completion in its own task. Hold a reference in
            # ``_pending_ticks`` to keep the task alive (asyncio drops
            # weakly-held tasks).
            tick_task: asyncio.Task[TickResult] = asyncio.create_task(self.tick())
            self._pending_ticks.add(tick_task)
            tick_task.add_done_callback(self._pending_ticks.discard)
        return item

    async def record_recall(self, item_id: str) -> bool:
        """Increment the ``recall_count`` of the buffered item with ``item_id``.

        Returns ``True`` if a match was found and incremented; ``False``
        otherwise (e.g. the item has already been consolidated/evicted, or
        was never pushed). The intended caller is the memory router after a
        successful recall hit; for v0 this is just a hook â€” wiring is left
        to the application.
        """
        async with self._lock:
            for it in self._stm:
                if it.id == item_id:
                    it.recall_count += 1
                    return True
        return False

    # ------------------------------------------------------------------
    # tick â€” one consolidation pass
    # ------------------------------------------------------------------

    async def tick(self) -> TickResult:
        """Run a single consolidation pass over the current STM buffer.

        Algorithm:

        * Snapshot the buffer under the lock, then release the lock so
          async :meth:`remember` calls don't block other producers.
        * For each item, compute ``scorer(item)``:
            - ``score >= threshold`` â†’ call ``target.remember(...)``. On
              success, fire ``on_consolidate`` and remove from STM.
            - ``score < threshold`` AND item older than
              ``cadence_seconds * 2`` â†’ fire ``on_evict``, drop.
            - Otherwise â†’ keep in STM, count as skipped.
        * Re-acquire the lock and rewrite the buffer with the survivors.

        Items that raise during ``remember()`` stay in STM; the error is
        recorded in :attr:`TickResult.errors` so callers can retry. Errors
        raised by the user-supplied callbacks are caught and logged but do
        not abort the pass.
        """
        result = TickResult()

        # Snapshot under the lock so concurrent push()es don't shift the
        # iteration set under our feet.
        async with self._lock:
            snapshot: list[STMItem] = list(self._stm)

        # ``kept_ids`` is the set of items that should remain in STM after
        # this pass. Items NOT in this set will be dropped when we rewrite
        # the buffer below.
        kept_ids: set[str] = set()
        now_seconds: float = self._clock()
        aged_out_seconds = self._cadence_seconds * 2.0

        for item in snapshot:
            score = self._safe_score(item)
            if score >= self._importance_threshold:
                # Consolidate to LTM.
                try:
                    response = await self._target.remember(
                        RememberRequest(
                            content=item.content,
                            agent_id=item.agent_id,
                            user_id=item.user_id,
                            type=item.type,
                            metadata=item.metadata,
                            confidence=score,
                        )
                    )
                except Exception as exc:
                    # Per-item isolation: a failing remember() should never
                    # take down the consolidation pass. Keep the item in STM
                    # so the next tick can retry.
                    kept_ids.add(item.id)
                    result.errors.append((item.id, repr(exc)))
                    logger.warning(
                        "remember() raised during consolidation of %s: %s",
                        item.id,
                        exc,
                    )
                    continue

                result.consolidated += 1
                if self._on_consolidate is not None:
                    await self._fire_consolidate(item, response)
                # Item drops out of STM (not added to kept_ids).
                continue

            # Below threshold: either evict (aged out) or skip (still young).
            age_seconds = now_seconds - (item.pushed_at / 1000.0)
            if age_seconds > aged_out_seconds:
                result.evicted += 1
                if self._on_evict is not None:
                    await self._fire_evict(item)
                # Item drops out (not added to kept_ids).
                continue

            # Skip: keep in STM for later reconsideration.
            kept_ids.add(item.id)
            result.skipped += 1

        # Rewrite the buffer with the survivors. Items pushed *during* the
        # consolidation pass aren't in our snapshot â€” preserve them so we
        # don't lose concurrent writers' data.
        snapshot_ids: set[str] = {it.id for it in snapshot}
        async with self._lock:
            self._stm = deque(
                it for it in self._stm if (it.id in kept_ids) or (it.id not in snapshot_ids)
            )

        return result

    # ------------------------------------------------------------------
    # Lifecycle: start / stop / async-context-manager
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn the background consolidation task.

        Idempotent: calling :meth:`start` a second time without an
        intervening :meth:`stop` is a no-op.
        """
        if self._started:
            return
        self._started = True
        self._task = asyncio.create_task(self._run_loop(), name="amp-stm-ltm-loop")

    async def stop(self) -> None:
        """Cancel the background task and run one final drain tick.

        Calling ``stop`` on a never-started transformer is a no-op except
        for the final drain tick (so flushing on a manually-driven
        transformer still works).
        """
        task = self._task
        self._task = None
        self._started = False

        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Expected â€” we cancelled it.
                pass
            except Exception as exc:
                logger.warning("background task raised during stop: %s", exc)

        # Final drain pass so anything still in STM gets a last shot.
        try:
            await self.tick()
        except Exception as exc:
            logger.warning("drain tick during stop raised: %s", exc)

    async def __aenter__(self) -> STMToLTMTransformer:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Internal: background loop, scorer, callback fences
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Body of the background task: sleep cadence then tick, forever."""
        try:
            while True:
                await asyncio.sleep(self._cadence_seconds)
                try:
                    await self.tick()
                except Exception as exc:
                    # We never want a single bad tick to kill the loop; the
                    # next cadence will try again.
                    logger.warning("background tick raised: %s", exc)
        except asyncio.CancelledError:
            # Re-raised so the awaiter in stop() can swallow it; this is the
            # documented Python pattern for cooperative cancellation.
            raise

    def _safe_score(self, item: STMItem) -> float:
        """Run the configured scorer and clamp into ``[0, 1]``.

        A scorer that raises is treated as score 0 (item is not
        consolidated, will eventually be evicted as it ages); the error is
        logged.
        """
        try:
            raw = float(self._scorer(item))
        except Exception as exc:
            logger.warning("scorer raised for item %s: %s", item.id, exc)
            return 0.0
        if raw < 0.0:
            return 0.0
        if raw > 1.0:
            return 1.0
        return raw

    def _default_scorer(self, item: STMItem) -> float:
        """Built-in heuristic from the task brief / ARCHITECTURE Â§7.

        ``score = 0.5*importance + 0.2*min(1, recall_count/5)
                 + 0.2*max(0, 1 - age_seconds/3600)
                 + 0.1*(1 if metadata.user_flagged else 0)``

        Result is clamped to ``[0, 1]`` by :meth:`_safe_score`.
        """
        importance_term = 0.5 * float(item.importance)
        recall_term = 0.2 * min(1.0, item.recall_count / 5.0)

        age_seconds = self._clock() - (item.pushed_at / 1000.0)
        recency_term = 0.2 * max(0.0, 1.0 - age_seconds / 3600.0)

        flagged = bool(item.metadata and item.metadata.get("user_flagged"))
        flagged_term = 0.1 * (1.0 if flagged else 0.0)

        return importance_term + recall_term + recency_term + flagged_term

    async def _fire_consolidate(self, item: STMItem, response: RememberResponse) -> None:
        """Invoke the on_consolidate callback, swallowing + logging failures."""
        cb = self._on_consolidate
        if cb is None:  # pragma: no cover -- defensive; caller checks first
            return
        try:
            await cb(item, response)
        except Exception as exc:
            logger.warning("on_consolidate callback raised for %s: %s", item.id, exc)

    async def _fire_evict(self, item: STMItem) -> None:
        """Invoke the on_evict callback, swallowing + logging failures."""
        cb = self._on_evict
        if cb is None:  # pragma: no cover -- defensive; caller checks first
            return
        try:
            await cb(item)
        except Exception as exc:
            logger.warning("on_evict callback raised for %s: %s", item.id, exc)


__all__ = ["STMItem", "STMToLTMTransformer", "TickResult"]
