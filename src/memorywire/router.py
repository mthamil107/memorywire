"""The :class:`MemoryRouter` â€” a :class:`memorywire.store.MemoryStore` composed of N child stores.

The router is the centrepiece of memorywire's "any-backend" promise (spec Â§5). It
fans operations out to a set of child stores in parallel, fuses results
with one of three algorithms (RRF / max / weighted), and optionally
boosts items connected via 1-2 graph hops. Because :class:`MemoryRouter`
itself satisfies the :class:`memorywire.store.MemoryStore` Protocol, routers can
be nested (e.g. a region-router of memory-type-routers).

Design notes
------------
* Every fan-out uses :func:`asyncio.gather` with ``return_exceptions=True``
  so a single failing store can't abort an operation. Per-store failures
  are logged at WARNING but never re-raised (except for ``remember``,
  where an all-stores-failed condition re-raises the first exception so
  callers don't see a silently-empty write).
* Per-request ``fusion`` (on :class:`RecallRequest`) overrides the
  router-level ``default_fusion``.
* Each store gets ``req.k * 4`` as its per-store k (matches
  :file:`docs/kickoff/ARCHITECTURE.md` Â§5 pseudocode: over-fetch then
  re-rank).
* Graph-hop boost dispatches to stores implementing the
  :class:`Neighborable` Protocol. Adapters in Phase 3 (sqlite-vec, mem0)
  don't implement it yet â€” Phase v0.2 will add Cognee/Letta with real
  graph traversal. Until then the router silently skips the boost when
  no store declares :attr:`memorywire.store.Capability.GRAPH`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from memorywire.models import (
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    ForgetStoreResult,
    FusionAlgorithm,
    MemoryType,
    MergeRequest,
    MergeResponse,
    MergeStrategy,
    RecallHit,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)
from memorywire.store.base import Capability, MemoryStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    """Return the current Unix time in milliseconds (memorywire timestamp format)."""
    return int(time.time() * 1000)


# Memory-type â†’ capability-string mapping. Kept in one place so the routing
# rules ("skip stores that don't support this type") stay consistent across
# remember/recall.
_TYPE_TO_CAPABILITY: dict[MemoryType, str] = {
    MemoryType.SEMANTIC: Capability.SEMANTIC,
    MemoryType.EPISODIC: Capability.EPISODIC,
    MemoryType.PROCEDURAL: Capability.PROCEDURAL,
    MemoryType.EMOTIONAL: Capability.EMOTIONAL,
}


# ---------------------------------------------------------------------------
# Neighborable Protocol (graph-hop dispatch)
# ---------------------------------------------------------------------------


@runtime_checkable
class Neighborable(Protocol):
    """Optional extension Protocol for stores that can expose graph neighbors.

    The router calls :meth:`neighbors` on every child store that both
    implements this Protocol and declares :attr:`Capability.GRAPH`. The
    return type matches :class:`RecallHit` so the router can fuse the
    neighbor scores back into the existing result set. ``hop_distance``
    MAY be communicated by stores via :attr:`RecallHit.metadata` under the
    key ``"hop_distance"`` (defaults to 1 when missing).

    No adapter implements this Protocol at v0 â€” Cognee and Letta (Phase
    v0.2) will be the first. The router uses ``isinstance(store,
    Neighborable)`` to detect support at runtime.
    """

    async def neighbors(self, id: str, hops: int) -> list[RecallHit]:
        """Return up to ``hops``-distance neighbors of ``id``."""
        ...


# ---------------------------------------------------------------------------
# MemoryRouter
# ---------------------------------------------------------------------------


class MemoryRouter:
    """Fan-out + fusion router that itself implements :class:`MemoryStore`.

    Parameters
    ----------
    stores:
        Non-empty sequence of child stores. ``stores[0]`` is the "primary"
        used when ``write_policy == "primary_only"``.
    default_fusion:
        Fusion algorithm applied when :attr:`RecallRequest.fusion` is None.
        Defaults to :class:`FusionAlgorithm.RRF`.
    rrf_k:
        The constant used in the RRF formula ``1 / (rrf_k + rank)``. Spec
        Â§5 fixes this at 60; exposed as a parameter for benchmarking.
    graph_boost_factor:
        Multiplier in the graph-hop boost formula
        ``new_score = old_score * (1 + graph_boost_factor / (1 + hop_distance))``.
        Spec Â§5 fixes this at 0.1; exposed as a parameter for tuning.
    weights:
        Per-store weights for ``fusion="weighted"``. Keys are store
        identifiers â€” preferred is the ``backend`` value from
        :meth:`MemoryStore.health`, falling back to ``repr(store)``.
        Missing keys default to 1.0.
    write_policy:
        ``"all"`` (default) fans :meth:`remember` out to every capable
        child. ``"primary_only"`` writes only to ``stores[0]``.
    """

    def __init__(
        self,
        stores: Sequence[MemoryStore],
        *,
        default_fusion: FusionAlgorithm = FusionAlgorithm.RRF,
        rrf_k: int = 60,
        graph_boost_factor: float = 0.1,
        weights: dict[str, float] | None = None,
        write_policy: Literal["all", "primary_only"] = "all",
    ) -> None:
        if not stores:
            raise ValueError("MemoryRouter requires at least one store")
        # Keep an immutable tuple â€” the router is inert without children
        # and shouldn't be mutable post-construction.
        self._stores: tuple[MemoryStore, ...] = tuple(stores)
        self._default_fusion: FusionAlgorithm = default_fusion
        self._rrf_k: int = int(rrf_k)
        self._graph_boost_factor: float = float(graph_boost_factor)
        self._weights: dict[str, float] = dict(weights) if weights else {}
        self._write_policy: Literal["all", "primary_only"] = write_policy

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stores(self) -> tuple[MemoryStore, ...]:
        """The configured child stores, in priority order."""
        return self._stores

    @property
    def capabilities(self) -> set[str]:
        """Union of capabilities across all child stores.

        The router supports a capability if *any* child does. Per-operation
        dispatch uses each child's own capability set to decide whether
        that child participates.
        """
        union: set[str] = set()
        for store in self._stores:
            union |= store.capabilities
        return union

    # ------------------------------------------------------------------
    # Store-id helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _store_id(store: MemoryStore) -> str:
        """Return a stable identifier for a child store.

        Prefer the ``backend`` key from :meth:`health`; fall back to
        ``repr(store)`` so the router can still aggregate when health is
        unimplemented or raises.
        """
        try:
            health = await store.health()
        except Exception:
            return repr(store)
        backend = health.get("backend") if isinstance(health, dict) else None
        if isinstance(backend, str) and backend:
            return backend
        return repr(store)

    @staticmethod
    def _store_id_sync(store: MemoryStore) -> str:
        """Synchronous best-effort store id (used inside fusion loops).

        We use ``BACKEND_NAME`` class attribute if available â€” both
        :class:`SqliteVecStore` and :class:`Mem0Store` expose it. Otherwise
        we fall back to ``repr(store)``. The async :meth:`_store_id` is
        preferred for response aggregation; this sync flavour exists so
        fusion math doesn't have to await per item.
        """
        backend_name = getattr(store, "BACKEND_NAME", None)
        if isinstance(backend_name, str) and backend_name:
            return backend_name
        return repr(store)

    # ------------------------------------------------------------------
    # remember
    # ------------------------------------------------------------------

    async def remember(self, req: RememberRequest) -> RememberResponse:
        """Fan a remember out per :attr:`write_policy`.

        * ``primary_only`` â€” call ``stores[0]`` only.
        * ``all`` â€” fan out to every store whose capabilities include the
          requested memory type. Stores without the capability are
          silently skipped (not failed).

        Aggregation:
        * ``id`` â€” first successful store's id.
        * ``stores`` â€” union of ``stores`` lists across successful
          responses.
        * ``pending_approval`` â€” True if any store returned True.
        * ``approval_url`` â€” first non-None across successful responses.

        Partial-failure semantics: if any store raises, the exception is
        logged and skipped. If *all* eligible stores raise (or no stores
        are eligible), the first exception is re-raised. If no stores are
        eligible *and* none raised, ``ValueError`` is raised so callers
        notice the no-op.
        """
        required_capability = _TYPE_TO_CAPABILITY[req.type]

        if self._write_policy == "primary_only":
            target_stores: tuple[MemoryStore, ...] = (self._stores[0],)
        else:
            target_stores = self._stores

        eligible: list[MemoryStore] = [
            s for s in target_stores if required_capability in s.capabilities
        ]

        if not eligible:
            raise ValueError(
                f"no child store supports memory type {req.type.value!r}; "
                f"router capabilities are {sorted(self.capabilities)!r}"
            )

        # Run all eligible stores in parallel; tolerate per-store failures.
        outcomes = await asyncio.gather(
            *(s.remember(req) for s in eligible),
            return_exceptions=True,
        )

        canonical_id: str | None = None
        merged_stores: list[str] = []
        any_pending = False
        approval_url: str | None = None
        first_exception: BaseException | None = None
        success_count = 0

        for store, outcome in zip(eligible, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                if first_exception is None:
                    first_exception = outcome
                logger.warning(
                    "remember failed on store %s: %s",
                    self._store_id_sync(store),
                    outcome,
                )
                continue
            success_count += 1
            if canonical_id is None:
                canonical_id = outcome.id
            # Merge the per-store ``stores`` field. The adapter typically
            # returns ``[<its own backend name>]``; collect them all so the
            # response accurately documents who wrote.
            for s in outcome.stores:
                if s and s not in merged_stores:
                    merged_stores.append(s)
            if outcome.pending_approval:
                any_pending = True
            if approval_url is None and outcome.approval_url is not None:
                approval_url = outcome.approval_url

        if success_count == 0:
            # Every eligible store raised â€” re-raise the first exception so
            # callers see something rather than an empty response.
            assert first_exception is not None  # for type-narrowing
            raise first_exception

        assert canonical_id is not None  # at least one success â†’ an id
        return RememberResponse(
            id=canonical_id,
            stored_at=_now_ms(),
            stores=merged_stores,
            pending_approval=any_pending,
            approval_url=approval_url,
        )

    # ------------------------------------------------------------------
    # recall
    # ------------------------------------------------------------------

    async def recall(self, req: RecallRequest) -> RecallResponse:
        """Fan a recall out, fuse, optionally boost, return top-k.

        Implements :file:`docs/kickoff/ARCHITECTURE.md` Â§5 pseudocode.
        """
        started_ms = _now_ms()

        fusion = req.fusion if req.fusion is not None else self._default_fusion
        # Validate up front â€” pydantic accepts the enum, but if a caller
        # somehow injects an unknown algorithm we want a clear ValueError
        # rather than a KeyError deep in the fusion math.
        if fusion not in (FusionAlgorithm.RRF, FusionAlgorithm.MAX, FusionAlgorithm.WEIGHTED):
            raise ValueError(f"unknown fusion algorithm: {fusion!r}")

        # Which stores can satisfy any of the requested types? Stores
        # without an intersecting type capability are skipped entirely.
        if req.types:
            required_caps = {_TYPE_TO_CAPABILITY[t] for t in req.types}
            eligible_stores = [s for s in self._stores if s.capabilities & required_caps]
        else:
            eligible_stores = list(self._stores)

        if not eligible_stores:
            # Nothing to query â€” return an empty response with the fusion
            # the caller requested so downstream code can still log it.
            return RecallResponse(
                results=[],
                fusion_used=fusion,
                stores_queried=[],
                latency_ms=max(_now_ms() - started_ms, 0),
            )

        # Per-store over-fetch: spec / ARCHITECTURE Â§5 says k*4.
        k = req.k if req.k is not None else 5
        per_store_k = max(k * 4, 1)
        per_store_req = req.model_copy(update={"k": per_store_k})

        outcomes = await asyncio.gather(
            *(s.recall(per_store_req) for s in eligible_stores),
            return_exceptions=True,
        )

        # Collect the per-store, ranked hit lists.
        per_store_hits: list[tuple[MemoryStore, list[RecallHit]]] = []
        for store, outcome in zip(eligible_stores, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                logger.warning(
                    "recall failed on store %s: %s",
                    self._store_id_sync(store),
                    outcome,
                )
                per_store_hits.append((store, []))
                continue
            per_store_hits.append((store, list(outcome.results)))

        # Per-store identifiers for the response. Use the BACKEND_NAME sync
        # form to avoid an extra round of health() calls inside the hot path.
        stores_queried: list[str] = []
        for store, _hits in per_store_hits:
            sid = self._store_id_sync(store)
            if sid not in stores_queried:
                stores_queried.append(sid)

        # Fuse.
        fused: dict[str, RecallHit] = {}
        fused_scores: dict[str, float] = {}
        for store, hits in per_store_hits:
            sid = self._store_id_sync(store)
            weight = self._weights.get(sid, 1.0)
            for rank, item in enumerate(hits):
                contribution = self._fusion_contribution(fusion, rank, item.score, weight)
                if item.id in fused_scores:
                    fused_scores[item.id] = self._fusion_combine(
                        fusion, fused_scores[item.id], contribution
                    )
                else:
                    fused_scores[item.id] = contribution
                    # Take the first occurrence as the canonical row;
                    # subsequent stores only contribute their score.
                    fused[item.id] = item.model_copy()

        # Apply the fused scores back onto the canonical row objects.
        for mid, hit in fused.items():
            hit.score = fused_scores[mid]

        # Graph-hop boost.
        if (req.hops or 0) > 0:
            await self._apply_graph_boost(fused, fused_scores, req.hops or 0)

        # Sort by final score, descending, then take top-k.
        ranked = sorted(fused.values(), key=lambda h: h.score, reverse=True)[:k]

        return RecallResponse(
            results=ranked,
            fusion_used=fusion,
            stores_queried=stores_queried,
            latency_ms=max(_now_ms() - started_ms, 0),
        )

    def _fusion_contribution(
        self,
        fusion: FusionAlgorithm,
        rank: int,
        item_score: float,
        weight: float,
    ) -> float:
        """Per-occurrence contribution to the fused score, by algorithm.

        * RRF â€” ``1 / (rrf_k + rank)`` (the item's own score is ignored).
        * MAX â€” passthrough of the item's score (combine via ``max``).
        * WEIGHTED â€” ``weight * item_score``.
        """
        if fusion is FusionAlgorithm.RRF:
            return 1.0 / (self._rrf_k + rank)
        if fusion is FusionAlgorithm.MAX:
            return float(item_score)
        # WEIGHTED
        return float(weight) * float(item_score)

    @staticmethod
    def _fusion_combine(fusion: FusionAlgorithm, existing: float, incoming: float) -> float:
        """Combine two per-occurrence contributions for the same item.

        * RRF / WEIGHTED â€” sum.
        * MAX â€” element-wise max.
        """
        if fusion is FusionAlgorithm.MAX:
            return max(existing, incoming)
        return existing + incoming

    # ------------------------------------------------------------------
    # Graph-hop boost
    # ------------------------------------------------------------------

    async def _apply_graph_boost(
        self,
        fused: dict[str, RecallHit],
        fused_scores: dict[str, float],
        hops: int,
    ) -> None:
        """Boost fused items whose neighbors are also in the fused set.

        Cap hops at 2; deeper traversal is deferred to v0.2 (see spec Â§5
        and ARCHITECTURE Â§5 pseudocode).
        """
        # Only stores that declare GRAPH *and* implement the Neighborable
        # Protocol participate.
        graph_stores: list[Neighborable] = [
            s
            for s in self._stores
            if Capability.GRAPH in s.capabilities and isinstance(s, Neighborable)
        ]
        if not graph_stores:
            # Silent skip â€” no GRAPH-capable store wired in. v0.2 lands the
            # first real graph adapter.
            return

        effective_hops = min(hops, 2)

        # Snapshot the items we'll boost from; we don't want to iterate over
        # ``fused`` while we mutate the scores within.
        anchor_ids = list(fused.keys())

        for anchor_id in anchor_ids:
            # For each graph-capable store, fetch up to ``hops`` neighbors of
            # the anchor. Failures are logged and tolerated.
            neighbor_results = await asyncio.gather(
                *(self._neighbors_safe(store, anchor_id, effective_hops) for store in graph_stores),
                return_exceptions=False,  # _neighbors_safe handles its own errors
            )
            for neighbors in neighbor_results:
                for n in neighbors:
                    if n.id not in fused:
                        # Per ARCHITECTURE Â§5 we only boost items already
                        # in the fused set.
                        continue
                    hop_distance = self._hop_distance(n)
                    old_score = fused_scores[n.id]
                    new_score = old_score * (1.0 + self._graph_boost_factor / (1.0 + hop_distance))
                    fused_scores[n.id] = new_score
                    fused[n.id].score = new_score
                    # Track which anchor contributed via the supporting list.
                    supporting = list(fused[n.id].supporting or [])
                    if anchor_id != n.id and anchor_id not in supporting:
                        supporting.append(anchor_id)
                        fused[n.id].supporting = supporting

    @staticmethod
    def _hop_distance(hit: RecallHit) -> int:
        """Extract the hop distance from a neighbor result.

        Convention: stores MAY pass ``hop_distance`` via
        :attr:`RecallHit.metadata`. Missing â†’ default 1. Values are clamped
        to >=1 so the boost formula stays well-defined.
        """
        metadata = hit.metadata or {}
        raw = metadata.get("hop_distance", 1)
        try:
            distance = int(raw)
        except (TypeError, ValueError):
            distance = 1
        return max(distance, 1)

    @staticmethod
    async def _neighbors_safe(store: Neighborable, anchor_id: str, hops: int) -> list[RecallHit]:
        """Call ``store.neighbors`` and swallow errors with a WARNING log."""
        try:
            return list(await store.neighbors(anchor_id, hops))
        except Exception as exc:
            logger.warning(
                "graph-hop neighbors call failed on store %r for anchor %s: %s",
                store,
                anchor_id,
                exc,
            )
            return []

    # ------------------------------------------------------------------
    # forget
    # ------------------------------------------------------------------

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        """Fan a forget out, aggregate per-store counts.

        Per spec Â§3.3 a request with neither ``ids`` nor ``filter`` is
        rejected here (before any child call) as a no-scope mass-delete.
        """
        if not req.ids and not req.filter:
            raise ValueError("forget requires `ids` or `filter`")

        outcomes = await asyncio.gather(
            *(s.forget(req) for s in self._stores),
            return_exceptions=True,
        )

        forgotten_union: list[str] = []
        per_store_rows: list[ForgetStoreResult] = []
        any_pending = False
        approval_url: str | None = None

        for store, outcome in zip(self._stores, outcomes, strict=True):
            sid = self._store_id_sync(store)
            if isinstance(outcome, BaseException):
                logger.warning("forget failed on store %s: %s", sid, outcome)
                per_store_rows.append(ForgetStoreResult(store=sid, count=0, error=str(outcome)))
                continue
            for fid in outcome.forgotten_ids:
                if fid not in forgotten_union:
                    forgotten_union.append(fid)
            # Sum per-store rows. Most adapters return a single row keyed
            # to their own backend name; preserve that shape.
            if outcome.stores:
                per_store_rows.extend(outcome.stores)
            else:
                per_store_rows.append(ForgetStoreResult(store=sid, count=0))
            if outcome.pending_approval:
                any_pending = True
            if approval_url is None and outcome.approval_url is not None:
                approval_url = outcome.approval_url

        return ForgetResponse(
            forgotten_ids=forgotten_union,
            hard_delete=bool(req.hard_delete),
            stores=per_store_rows,
            pending_approval=any_pending,
            approval_url=approval_url,
        )

    # ------------------------------------------------------------------
    # merge
    # ------------------------------------------------------------------

    async def merge(self, req: MergeRequest) -> MergeResponse:
        """Fan a merge out, sum per-store merged counts."""
        outcomes = await asyncio.gather(
            *(s.merge(req) for s in self._stores),
            return_exceptions=True,
        )

        strategy_used = req.strategy if req.strategy is not None else MergeStrategy.KEEP_CANONICAL
        total_merged = 0
        store_ids: list[str] = []

        for store, outcome in zip(self._stores, outcomes, strict=True):
            sid = self._store_id_sync(store)
            if isinstance(outcome, BaseException):
                logger.warning("merge failed on store %s: %s", sid, outcome)
                continue
            total_merged += outcome.merged_count
            # Prefer the per-store ``stores`` list (matches the adapter's
            # own self-identifier); fall back to the router-side sid.
            if outcome.stores:
                for s in outcome.stores:
                    if s and s not in store_ids:
                        store_ids.append(s)
            elif sid not in store_ids:
                store_ids.append(sid)

        return MergeResponse(
            canonical=req.canonical,
            merged_count=total_merged,
            strategy_used=strategy_used,
            stores=store_ids,
        )

    # ------------------------------------------------------------------
    # expire
    # ------------------------------------------------------------------

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        """Fan an expire out, sum per-store matched counts.

        Per spec Â§3.5: when the policy uses ``no_recall_in_days`` only
        stores with :attr:`Capability.RECALL_TRACKING` are eligible; the
        rest are skipped silently. (Their own adapter would raise; the
        router pre-empts that to keep the aggregate clean.)

        Empty-policy guard: mirrors the no-scope mass-delete guard on
        :meth:`forget`. A request with no policy fields would otherwise
        match every live row for the agent and (with the default
        ``action=FORGET``) soft-delete them all â€” see ARCHITECTURE Â§3.5.
        """
        # Reject empty/missing policies so a stray ``expire(policy={})``
        # cannot mass-delete every memory for the agent.
        if req.policy is None or (
            req.policy.older_than_days is None
            and req.policy.type is None
            and req.policy.confidence_below is None
            and req.policy.no_recall_in_days is None
        ):
            raise ValueError(
                "expire requires a non-empty policy: at least one of "
                "older_than_days, type, confidence_below, or no_recall_in_days "
                "must be set"
            )

        requires_recall_tracking = (
            req.policy is not None and req.policy.no_recall_in_days is not None
        )

        eligible_stores: list[MemoryStore] = []
        for store in self._stores:
            if requires_recall_tracking and Capability.RECALL_TRACKING not in store.capabilities:
                logger.debug(
                    "skipping store %s for expire(no_recall_in_days) â€” no recall_tracking",
                    self._store_id_sync(store),
                )
                continue
            eligible_stores.append(store)

        outcomes = await asyncio.gather(
            *(s.expire(req) for s in eligible_stores),
            return_exceptions=True,
        )

        action_taken = req.action  # spec contract: response echoes the request action
        # Resolve action_taken if the request omitted it: default per the
        # ExpireResponse model contract â€” first successful outcome wins.
        total_matched = 0
        store_ids: list[str] = []
        first_action = None

        for store, outcome in zip(eligible_stores, outcomes, strict=True):
            sid = self._store_id_sync(store)
            if isinstance(outcome, BaseException):
                logger.warning("expire failed on store %s: %s", sid, outcome)
                continue
            total_matched += outcome.matched_count
            if first_action is None:
                first_action = outcome.action_taken
            if outcome.stores:
                for s in outcome.stores:
                    if s and s not in store_ids:
                        store_ids.append(s)
            elif sid not in store_ids:
                store_ids.append(sid)

        # If we have a request action use it, else inherit from the first
        # successful store, else default to the model's required field by
        # falling through to FORGET (the spec default).
        if action_taken is None:
            from memorywire.models import ExpireAction

            action_taken = first_action if first_action is not None else ExpireAction.FORGET

        return ExpireResponse(
            matched_count=total_matched,
            action_taken=action_taken,
            stores=store_ids,
        )

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """Fan health checks out; report aggregated router status.

        * ``ok`` â€” every child returned ``status == "ok"``.
        * ``degraded`` â€” at least one child is ``ok`` and at least one
          isn't (or raised).
        * ``error`` â€” no child is ``ok``.
        """
        outcomes = await asyncio.gather(
            *(s.health() for s in self._stores),
            return_exceptions=True,
        )

        per_store: list[dict[str, Any]] = []
        ok_count = 0
        for store, outcome in zip(self._stores, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                per_store.append(
                    {
                        "status": "error",
                        "backend": self._store_id_sync(store),
                        "error": str(outcome),
                    }
                )
                continue
            health_dict = dict(outcome) if isinstance(outcome, dict) else {"raw": outcome}
            if health_dict.get("status") == "ok":
                ok_count += 1
            per_store.append(health_dict)

        if ok_count == len(self._stores):
            status = "ok"
        elif ok_count == 0:
            status = "error"
        else:
            status = "degraded"

        return {
            "status": status,
            "backend": "memory-router",
            "stores": per_store,
        }


__all__ = ["MemoryRouter", "Neighborable"]
