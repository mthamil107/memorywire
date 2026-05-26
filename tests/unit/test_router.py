"""Tests for :class:`amp.router.MemoryRouter` (Phase 4).

The router is the centrepiece of AMP's "any-backend" promise (spec §5).
These tests use a small in-test ``FakeStore`` helper to inject prepared
:class:`RecallResponse` rows and capability sets so we can assert fusion
math and per-operation routing without spinning up a real adapter.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import pytest

from amp.models import (
    ExpireAction,
    ExpirePolicy,
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
from amp.router import MemoryRouter, Neighborable
from amp.store import Capability, MemoryStore

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeStore:
    """Minimal :class:`MemoryStore` for router tests.

    Each instance can be primed with:

    * a fixed list of :class:`RecallHit`'s to return on ``recall``;
    * a capability set;
    * a backend name (used by the router for fusion weights + reporting);
    * a recorded list of ``remember`` / ``forget`` / ``merge`` / ``expire``
      calls for assertions.

    Optionally any operation can be forced to raise via ``raise_on``.
    """

    def __init__(
        self,
        *,
        backend_name: str,
        capabilities: set[str] | None = None,
        recall_hits: list[RecallHit] | None = None,
        forget_count: int = 1,
        merge_count: int = 1,
        expire_count: int = 1,
        pending_approval: bool = False,
        health_status: str = "ok",
        health_extra: dict[str, Any] | None = None,
        raise_on: set[str] | None = None,
    ) -> None:
        self.BACKEND_NAME = backend_name
        self._capabilities: set[str] = capabilities or {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.PROCEDURAL,
            Capability.EMOTIONAL,
        }
        self._recall_hits = recall_hits or []
        self._forget_count = forget_count
        self._merge_count = merge_count
        self._expire_count = expire_count
        self._pending_approval = pending_approval
        self._health_status = health_status
        self._health_extra = health_extra or {}
        self._raise_on = raise_on or set()
        # Recording attributes
        self.remember_calls: list[RememberRequest] = []
        self.recall_calls: list[RecallRequest] = []
        self.forget_calls: list[ForgetRequest] = []
        self.merge_calls: list[MergeRequest] = []
        self.expire_calls: list[ExpireRequest] = []
        self.health_calls: int = 0

    @property
    def capabilities(self) -> set[str]:
        return self._capabilities

    async def remember(self, req: RememberRequest) -> RememberResponse:
        if "remember" in self._raise_on:
            raise RuntimeError(f"{self.BACKEND_NAME} remember failure")
        self.remember_calls.append(req)
        return RememberResponse(
            id=f"{self.BACKEND_NAME}-id-{len(self.remember_calls)}",
            stored_at=1_700_000_000_000,
            stores=[self.BACKEND_NAME],
            pending_approval=self._pending_approval,
            approval_url="https://gov/" if self._pending_approval else None,
        )

    async def recall(self, req: RecallRequest) -> RecallResponse:
        if "recall" in self._raise_on:
            raise RuntimeError(f"{self.BACKEND_NAME} recall failure")
        self.recall_calls.append(req)
        return RecallResponse(
            results=list(self._recall_hits),
            fusion_used=req.fusion if req.fusion is not None else FusionAlgorithm.RRF,
            stores_queried=[self.BACKEND_NAME],
            latency_ms=1,
        )

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        if "forget" in self._raise_on:
            raise RuntimeError(f"{self.BACKEND_NAME} forget failure")
        self.forget_calls.append(req)
        forgotten = list(req.ids or [])[: self._forget_count]
        return ForgetResponse(
            forgotten_ids=forgotten,
            hard_delete=bool(req.hard_delete),
            stores=[ForgetStoreResult(store=self.BACKEND_NAME, count=len(forgotten))],
            pending_approval=False,
            approval_url=None,
        )

    async def merge(self, req: MergeRequest) -> MergeResponse:
        if "merge" in self._raise_on:
            raise RuntimeError(f"{self.BACKEND_NAME} merge failure")
        self.merge_calls.append(req)
        return MergeResponse(
            canonical=req.canonical,
            merged_count=self._merge_count,
            strategy_used=req.strategy
            if req.strategy is not None
            else MergeStrategy.KEEP_CANONICAL,
            stores=[self.BACKEND_NAME],
        )

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        if "expire" in self._raise_on:
            raise RuntimeError(f"{self.BACKEND_NAME} expire failure")
        self.expire_calls.append(req)
        return ExpireResponse(
            matched_count=self._expire_count,
            action_taken=req.action if req.action is not None else ExpireAction.FORGET,
            stores=[self.BACKEND_NAME],
        )

    async def health(self) -> dict[str, Any]:
        if "health" in self._raise_on:
            raise RuntimeError(f"{self.BACKEND_NAME} health failure")
        self.health_calls += 1
        payload: dict[str, Any] = {"status": self._health_status, "backend": self.BACKEND_NAME}
        payload.update(self._health_extra)
        return payload


class FakeGraphStore(FakeStore):
    """A :class:`FakeStore` that also implements :class:`Neighborable`.

    Used to verify the graph-hop boost path. Returns whichever neighbors
    the test primes for a given anchor id.
    """

    def __init__(
        self,
        *,
        backend_name: str = "fake-graph",
        capabilities: set[str] | None = None,
        recall_hits: list[RecallHit] | None = None,
        neighbors_map: dict[str, list[RecallHit]] | None = None,
    ) -> None:
        caps = capabilities or {Capability.SEMANTIC, Capability.GRAPH}
        super().__init__(backend_name=backend_name, capabilities=caps, recall_hits=recall_hits)
        self._neighbors_map = neighbors_map or {}
        self.neighbors_calls: list[tuple[str, int]] = []

    async def neighbors(self, id: str, hops: int) -> list[RecallHit]:
        self.neighbors_calls.append((id, hops))
        return list(self._neighbors_map.get(id, []))


def _hit(memory_id: str, *, score: float = 0.5, source: str | None = None) -> RecallHit:
    """Build a small :class:`RecallHit` with the test-friendly defaults."""
    return RecallHit(
        id=memory_id,
        type=MemoryType.SEMANTIC,
        content=f"content-{memory_id}",
        score=score,
        metadata=None,
        created_at=1_700_000_000_000,
        supporting=[],
        source_store=source,
    )


# ---------------------------------------------------------------------------
# 1. Constructor + Protocol-shape tests
# ---------------------------------------------------------------------------


def test_constructor_requires_stores() -> None:
    """Empty stores list raises ``ValueError``."""
    with pytest.raises(ValueError, match="at least one store"):
        MemoryRouter([])


def test_router_is_a_memory_store() -> None:
    """The router itself satisfies the :class:`MemoryStore` Protocol."""
    router = MemoryRouter([FakeStore(backend_name="s1")])
    assert isinstance(router, MemoryStore)


def test_capabilities_union_across_children() -> None:
    """Router capabilities are the union of child capabilities."""
    s1 = FakeStore(backend_name="s1", capabilities={Capability.SEMANTIC, Capability.VECTOR})
    s2 = FakeStore(backend_name="s2", capabilities={Capability.EPISODIC, Capability.GRAPH})
    router = MemoryRouter([s1, s2])
    assert router.capabilities == {
        Capability.SEMANTIC,
        Capability.VECTOR,
        Capability.EPISODIC,
        Capability.GRAPH,
    }


async def test_recall_rejects_unknown_fusion_algorithm() -> None:
    """A non-enum fusion value raises ``ValueError`` in ``recall``."""

    class BogusFusion:
        def __repr__(self) -> str:
            return "<bogus>"

    s1 = FakeStore(backend_name="s1")
    router = MemoryRouter([s1])

    # Construct a request and forcibly override the fusion attribute past
    # pydantic validation. We use object.__setattr__ to bypass pydantic
    # field assignment because pydantic v2 with strict types would raise.
    req = RecallRequest(agent_id="a", query="q")
    object.__setattr__(req, "fusion", BogusFusion())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="unknown fusion"):
        await router.recall(req)


# ---------------------------------------------------------------------------
# 2. remember
# ---------------------------------------------------------------------------


async def test_remember_write_policy_all_fans_out() -> None:
    """``write_policy='all'`` calls every capable store."""
    s1 = FakeStore(backend_name="s1")
    s2 = FakeStore(backend_name="s2")
    router = MemoryRouter([s1, s2])

    resp = await router.remember(
        RememberRequest(agent_id="a", type=MemoryType.SEMANTIC, content="hello")
    )

    assert len(s1.remember_calls) == 1
    assert len(s2.remember_calls) == 1
    # First store contributes the canonical id.
    assert resp.id == "s1-id-1"
    assert set(resp.stores) == {"s1", "s2"}
    assert resp.pending_approval is False


async def test_remember_write_policy_primary_only() -> None:
    """``write_policy='primary_only'`` writes only to ``stores[0]``."""
    s1 = FakeStore(backend_name="s1")
    s2 = FakeStore(backend_name="s2")
    router = MemoryRouter([s1, s2], write_policy="primary_only")

    resp = await router.remember(
        RememberRequest(agent_id="a", type=MemoryType.SEMANTIC, content="hello")
    )

    assert len(s1.remember_calls) == 1
    assert s2.remember_calls == []
    assert resp.stores == ["s1"]


async def test_remember_skips_stores_without_capability() -> None:
    """Stores whose capability set doesn't cover the request type are skipped."""
    s_no_proc = FakeStore(
        backend_name="vec",
        capabilities={Capability.SEMANTIC, Capability.EPISODIC, Capability.VECTOR},
    )
    s_proc = FakeStore(
        backend_name="fsm",
        capabilities={Capability.PROCEDURAL},
    )
    router = MemoryRouter([s_no_proc, s_proc])

    resp = await router.remember(
        RememberRequest(agent_id="a", type=MemoryType.PROCEDURAL, content="{}")
    )
    assert s_no_proc.remember_calls == []
    assert len(s_proc.remember_calls) == 1
    assert resp.stores == ["fsm"]


async def test_remember_partial_failure_returns_successful_id() -> None:
    """A single failing store doesn't abort the operation."""
    s_bad = FakeStore(backend_name="bad", raise_on={"remember"})
    s_good = FakeStore(backend_name="good")
    router = MemoryRouter([s_bad, s_good])

    resp = await router.remember(
        RememberRequest(agent_id="a", type=MemoryType.SEMANTIC, content="hi")
    )
    # The good store's id surfaces as canonical.
    assert resp.id == "good-id-1"
    assert resp.stores == ["good"]


async def test_remember_total_failure_reraises() -> None:
    """If every store raises, the first exception propagates."""
    s_bad1 = FakeStore(backend_name="b1", raise_on={"remember"})
    s_bad2 = FakeStore(backend_name="b2", raise_on={"remember"})
    router = MemoryRouter([s_bad1, s_bad2])

    with pytest.raises(RuntimeError, match="b1 remember failure"):
        await router.remember(RememberRequest(agent_id="a", type=MemoryType.SEMANTIC, content="hi"))


async def test_remember_pending_approval_propagates() -> None:
    """``pending_approval=True`` from any store surfaces in the response."""
    s1 = FakeStore(backend_name="s1", pending_approval=True)
    s2 = FakeStore(backend_name="s2", pending_approval=False)
    router = MemoryRouter([s1, s2])
    resp = await router.remember(
        RememberRequest(
            agent_id="a", type=MemoryType.SEMANTIC, content="hi", approval_required=True
        )
    )
    assert resp.pending_approval is True
    assert resp.approval_url == "https://gov/"


async def test_remember_no_eligible_stores_raises() -> None:
    """If no store supports the requested type, ``ValueError``."""
    s_no_proc = FakeStore(
        backend_name="vec", capabilities={Capability.SEMANTIC, Capability.EPISODIC}
    )
    router = MemoryRouter([s_no_proc])
    with pytest.raises(ValueError, match="no child store supports memory type 'procedural'"):
        await router.remember(
            RememberRequest(agent_id="a", type=MemoryType.PROCEDURAL, content="{}")
        )


# ---------------------------------------------------------------------------
# 3. recall — RRF + max + weighted
# ---------------------------------------------------------------------------


async def test_recall_rrf_disjoint_six_items() -> None:
    """Two stores returning disjoint sets of 3 hits each produce 6 fused items."""
    s1_hits = [_hit("a1"), _hit("a2"), _hit("a3")]
    s2_hits = [_hit("b1"), _hit("b2"), _hit("b3")]
    s1 = FakeStore(backend_name="s1", recall_hits=s1_hits)
    s2 = FakeStore(backend_name="s2", recall_hits=s2_hits)
    router = MemoryRouter([s1, s2])

    resp = await router.recall(RecallRequest(agent_id="a", query="q", k=10))

    ids = {hit.id for hit in resp.results}
    assert ids == {"a1", "a2", "a3", "b1", "b2", "b3"}
    # Top-ranked from each store: 1 / (60 + 0) ≈ 0.016667.
    top = next(h for h in resp.results if h.id == "a1")
    assert math.isclose(top.score, 1.0 / 60, rel_tol=1e-9)


async def test_recall_rrf_overlap_boosts_shared_item() -> None:
    """An item present in both stores fuses to ``1/(60+rA) + 1/(60+rB)``."""
    # ``shared`` appears at rank 0 in s1 and rank 2 in s2.
    s1_hits = [_hit("shared"), _hit("a2"), _hit("a3")]
    s2_hits = [_hit("b1"), _hit("b2"), _hit("shared")]
    s1 = FakeStore(backend_name="s1", recall_hits=s1_hits)
    s2 = FakeStore(backend_name="s2", recall_hits=s2_hits)
    router = MemoryRouter([s1, s2])

    resp = await router.recall(RecallRequest(agent_id="a", query="q", k=10))

    shared = next(h for h in resp.results if h.id == "shared")
    expected = 1.0 / 60 + 1.0 / 62
    assert math.isclose(shared.score, expected, rel_tol=1e-9)

    # And it should outrank items that only appeared in one store.
    a2 = next(h for h in resp.results if h.id == "a2")
    assert shared.score > a2.score


async def test_recall_fusion_max() -> None:
    """``fusion=max`` takes the max item-score across stores."""
    s1_hits = [_hit("only-s1", score=0.4), _hit("shared", score=0.6)]
    s2_hits = [_hit("only-s2", score=0.9), _hit("shared", score=0.3)]
    s1 = FakeStore(backend_name="s1", recall_hits=s1_hits)
    s2 = FakeStore(backend_name="s2", recall_hits=s2_hits)
    router = MemoryRouter([s1, s2])

    resp = await router.recall(
        RecallRequest(agent_id="a", query="q", k=10, fusion=FusionAlgorithm.MAX)
    )

    by_id = {h.id: h.score for h in resp.results}
    # Shared item: max(0.6, 0.3) = 0.6
    assert math.isclose(by_id["shared"], 0.6, rel_tol=1e-9)
    assert math.isclose(by_id["only-s1"], 0.4, rel_tol=1e-9)
    assert math.isclose(by_id["only-s2"], 0.9, rel_tol=1e-9)


async def test_recall_fusion_weighted() -> None:
    """``fusion=weighted`` applies per-store weights."""
    s1_hits = [_hit("a", score=1.0)]
    s2_hits = [_hit("a", score=1.0)]
    s1 = FakeStore(backend_name="s1", recall_hits=s1_hits)
    s2 = FakeStore(backend_name="s2", recall_hits=s2_hits)
    router = MemoryRouter([s1, s2], weights={"s1": 0.7, "s2": 0.3})

    resp = await router.recall(
        RecallRequest(agent_id="a", query="q", k=5, fusion=FusionAlgorithm.WEIGHTED)
    )
    only = resp.results[0]
    assert math.isclose(only.score, 1.0, rel_tol=1e-9)  # 0.7 * 1.0 + 0.3 * 1.0


# ---------------------------------------------------------------------------
# 4. recall — k limiting, types filter, empty + error paths
# ---------------------------------------------------------------------------


async def test_recall_overfetches_per_store_then_limits_k() -> None:
    """Per-store k is ``req.k * 4``; final response is truncated to k."""
    s1_hits = [_hit(f"h{i}", score=1.0 - i * 0.01) for i in range(10)]
    s1 = FakeStore(backend_name="s1", recall_hits=s1_hits)
    router = MemoryRouter([s1])

    resp = await router.recall(RecallRequest(agent_id="a", query="q", k=3))

    # Final response is truncated to k=3.
    assert len(resp.results) == 3
    # And the underlying store was asked for k*4 = 12.
    assert s1.recall_calls[0].k == 12


async def test_recall_types_filter_skips_incapable_stores() -> None:
    """A type request skips stores without an intersecting capability."""
    s_semantic = FakeStore(
        backend_name="sem",
        capabilities={Capability.SEMANTIC},
        recall_hits=[_hit("sem-1")],
    )
    s_procedural = FakeStore(
        backend_name="fsm",
        capabilities={Capability.PROCEDURAL},
        recall_hits=[_hit("fsm-1")],
    )
    router = MemoryRouter([s_semantic, s_procedural])

    resp = await router.recall(
        RecallRequest(agent_id="a", query="q", k=10, types=[MemoryType.SEMANTIC])
    )
    assert s_procedural.recall_calls == []
    assert {h.id for h in resp.results} == {"sem-1"}
    assert resp.stores_queried == ["sem"]


async def test_recall_empty_results_still_works() -> None:
    """One empty store + one populated store returns the populated results."""
    s_empty = FakeStore(backend_name="empty", recall_hits=[])
    s_full = FakeStore(backend_name="full", recall_hits=[_hit("x")])
    router = MemoryRouter([s_empty, s_full])
    resp = await router.recall(RecallRequest(agent_id="a", query="q", k=5))
    assert [h.id for h in resp.results] == ["x"]


async def test_recall_store_error_degrades_gracefully() -> None:
    """A raising store contributes zero hits but doesn't fail the recall."""
    s_bad = FakeStore(backend_name="bad", raise_on={"recall"})
    s_good = FakeStore(backend_name="good", recall_hits=[_hit("ok")])
    router = MemoryRouter([s_bad, s_good])
    resp = await router.recall(RecallRequest(agent_id="a", query="q", k=5))
    assert [h.id for h in resp.results] == ["ok"]
    # Both stores still appear in stores_queried — they were queried.
    assert set(resp.stores_queried) == {"bad", "good"}


async def test_recall_no_eligible_stores_returns_empty() -> None:
    """When no store has the requested capability, return empty cleanly."""
    s = FakeStore(backend_name="s", capabilities={Capability.SEMANTIC})
    router = MemoryRouter([s])
    resp = await router.recall(
        RecallRequest(agent_id="a", query="q", k=5, types=[MemoryType.PROCEDURAL])
    )
    assert resp.results == []
    assert resp.stores_queried == []


# ---------------------------------------------------------------------------
# 5. recall — graph-hop boost
# ---------------------------------------------------------------------------


async def test_recall_graph_boost_skipped_when_no_graph_store() -> None:
    """Without a GRAPH-capable store, ``hops > 0`` is silently a no-op."""
    s = FakeStore(backend_name="s", recall_hits=[_hit("a"), _hit("b")])
    router = MemoryRouter([s])
    # Pre-compute RRF-only scores so we can verify nothing got boosted.
    resp = await router.recall(RecallRequest(agent_id="a", query="q", k=10, hops=1))
    # rrf(rank=0) ≈ 0.016667 ; rrf(rank=1) ≈ 0.016393
    assert math.isclose(resp.results[0].score, 1.0 / 60, rel_tol=1e-9)
    assert math.isclose(resp.results[1].score, 1.0 / 61, rel_tol=1e-9)


async def test_recall_graph_boost_applies_to_neighbor_in_set() -> None:
    """A graph-capable store boosts items whose neighbors are in the set.

    Setup: store returns [anchor, other]. Anchor's neighbors include ``other``.
    Without the boost, anchor ranks higher (rank=0 > rank=1). With the boost,
    ``other`` should retain its position but its score should be multiplied.
    """
    hits = [_hit("anchor"), _hit("other")]
    graph_store = FakeGraphStore(
        backend_name="graph",
        capabilities={Capability.SEMANTIC, Capability.GRAPH},
        recall_hits=hits,
        neighbors_map={"anchor": [_hit("other")]},
    )
    router = MemoryRouter([graph_store], graph_boost_factor=0.1)

    # First: hops=0 baseline.
    base = await router.recall(RecallRequest(agent_id="a", query="q", k=10, hops=0))
    base_other = next(h for h in base.results if h.id == "other").score

    # Now: hops=1 boost.
    boosted = await router.recall(RecallRequest(agent_id="a", query="q", k=10, hops=1))
    boosted_other = next(h for h in boosted.results if h.id == "other").score

    # 1 + 0.1 / (1 + 1) = 1.05  (hop_distance default = 1).
    assert math.isclose(boosted_other, base_other * 1.05, rel_tol=1e-9)
    # ``supporting`` records the anchor.
    other_hit = next(h for h in boosted.results if h.id == "other")
    assert other_hit.supporting == ["anchor"]


async def test_recall_graph_boost_promotes_underdog() -> None:
    """A weak item that's a neighbor of a strong anchor moves up after boost.

    Two graph-capable stores, with one item appearing at rank 0 in the first
    (``anchor`` — very strong) and a different item at rank 1 (``promote``).
    The graph store reports ``promote`` as a neighbor of ``anchor`` with a
    small hop distance, so the boost should narrow the gap. We don't try to
    make ``promote`` overtake ``anchor`` (it would take an unrealistic factor)
    — we just verify the boost is observable in the score.
    """
    hits = [_hit("anchor"), _hit("promote")]
    graph_store = FakeGraphStore(
        backend_name="graph",
        capabilities={Capability.SEMANTIC, Capability.GRAPH},
        recall_hits=hits,
        neighbors_map={"anchor": [_hit("promote")]},
    )
    router = MemoryRouter([graph_store], graph_boost_factor=0.5)

    no_boost = await router.recall(RecallRequest(agent_id="a", query="q", k=10, hops=0))
    boosted = await router.recall(RecallRequest(agent_id="a", query="q", k=10, hops=1))

    promote_no_boost = next(h for h in no_boost.results if h.id == "promote").score
    promote_boosted = next(h for h in boosted.results if h.id == "promote").score
    # boost = 1 + 0.5 / (1+1) = 1.25
    assert boosted is not no_boost
    assert promote_boosted > promote_no_boost


# ---------------------------------------------------------------------------
# 6. forget
# ---------------------------------------------------------------------------


async def test_forget_fans_out_and_aggregates() -> None:
    """``forget`` calls every store and unions ``forgotten_ids``."""
    s1 = FakeStore(backend_name="s1", forget_count=2)
    s2 = FakeStore(backend_name="s2", forget_count=2)
    router = MemoryRouter([s1, s2])

    resp = await router.forget(ForgetRequest(agent_id="a", ids=["x", "y"]))
    assert len(s1.forget_calls) == 1
    assert len(s2.forget_calls) == 1
    assert set(resp.forgotten_ids) == {"x", "y"}
    # Two per-store rows aggregated.
    assert len(resp.stores) == 2


async def test_forget_neither_ids_nor_filter_raises() -> None:
    """``forget`` with neither ``ids`` nor ``filter`` raises ``ValueError``."""
    s1 = FakeStore(backend_name="s1")
    router = MemoryRouter([s1])
    with pytest.raises(ValueError, match="forget requires"):
        await router.forget(ForgetRequest(agent_id="a"))
    # The store must not have been called.
    assert s1.forget_calls == []


async def test_forget_partial_failure_reports_error() -> None:
    """A raising store surfaces as a per-store row with the error."""
    s_bad = FakeStore(backend_name="bad", raise_on={"forget"})
    s_good = FakeStore(backend_name="good", forget_count=1)
    router = MemoryRouter([s_bad, s_good])

    resp = await router.forget(ForgetRequest(agent_id="a", ids=["x"]))
    by_store = {row.store: row for row in resp.stores}
    assert by_store["good"].count == 1
    assert by_store["bad"].count == 0
    assert by_store["bad"].error is not None


# ---------------------------------------------------------------------------
# 7. merge
# ---------------------------------------------------------------------------


async def test_merge_fans_out_and_sums_counts() -> None:
    """``merge.merged_count`` is the sum across stores."""
    s1 = FakeStore(backend_name="s1", merge_count=2)
    s2 = FakeStore(backend_name="s2", merge_count=3)
    router = MemoryRouter([s1, s2])
    resp = await router.merge(
        MergeRequest(
            agent_id="a",
            canonical="canon",
            duplicates=["d1", "d2"],
            strategy=MergeStrategy.MERGE_CONTENT,
        )
    )
    assert resp.canonical == "canon"
    assert resp.merged_count == 5
    assert resp.strategy_used is MergeStrategy.MERGE_CONTENT
    assert set(resp.stores) == {"s1", "s2"}


# ---------------------------------------------------------------------------
# 8. expire
# ---------------------------------------------------------------------------


async def test_expire_fans_out_and_sums_counts() -> None:
    """``expire.matched_count`` is the sum across stores."""
    s1 = FakeStore(backend_name="s1", expire_count=10)
    s2 = FakeStore(backend_name="s2", expire_count=5)
    router = MemoryRouter([s1, s2])
    resp = await router.expire(
        ExpireRequest(
            agent_id="a",
            policy=ExpirePolicy(older_than_days=30),
            action=ExpireAction.ARCHIVE,
        )
    )
    assert resp.matched_count == 15
    assert resp.action_taken is ExpireAction.ARCHIVE
    assert set(resp.stores) == {"s1", "s2"}


async def test_expire_rejects_missing_policy() -> None:
    """``expire`` with ``policy=None`` is a no-scope mass-delete and must raise.

    Regression: before this guard, ``policy=None`` with the default
    ``action=FORGET`` soft-deleted every live row for the agent because the
    where-clause collapsed to ``agent_id = ? AND deleted_at IS NULL``.
    """
    s1 = FakeStore(backend_name="s1")
    router = MemoryRouter([s1])
    with pytest.raises(ValueError, match="expire requires a non-empty policy"):
        await router.expire(ExpireRequest(agent_id="a"))
    # The store must not have been called.
    assert s1.expire_calls == []


async def test_expire_rejects_empty_policy() -> None:
    """``expire`` with an :class:`ExpirePolicy` of all-None fields must raise."""
    s1 = FakeStore(backend_name="s1")
    router = MemoryRouter([s1])
    with pytest.raises(ValueError, match="expire requires a non-empty policy"):
        await router.expire(ExpireRequest(agent_id="a", policy=ExpirePolicy()))
    assert s1.expire_calls == []


async def test_expire_no_recall_in_days_skips_stores_without_capability() -> None:
    """``no_recall_in_days`` policy skips stores that don't track recall."""
    s_tracked = FakeStore(
        backend_name="tracked",
        capabilities={Capability.SEMANTIC, Capability.RECALL_TRACKING},
        expire_count=4,
    )
    s_untracked = FakeStore(
        backend_name="untracked",
        capabilities={Capability.SEMANTIC},  # no RECALL_TRACKING
        expire_count=99,
    )
    router = MemoryRouter([s_tracked, s_untracked])
    resp = await router.expire(
        ExpireRequest(
            agent_id="a",
            policy=ExpirePolicy(no_recall_in_days=30),
        )
    )
    # Only the tracked store contributed.
    assert resp.matched_count == 4
    assert resp.stores == ["tracked"]
    assert s_untracked.expire_calls == []


# ---------------------------------------------------------------------------
# 9. health
# ---------------------------------------------------------------------------


async def test_health_all_ok() -> None:
    """All children healthy → router reports ``ok``."""
    s1 = FakeStore(backend_name="s1", health_status="ok")
    s2 = FakeStore(backend_name="s2", health_status="ok")
    router = MemoryRouter([s1, s2])
    h = await router.health()
    assert h["status"] == "ok"
    assert h["backend"] == "memory-router"
    assert len(h["stores"]) == 2


async def test_health_one_error_is_degraded() -> None:
    """Mixed health → ``degraded``."""
    s1 = FakeStore(backend_name="s1", health_status="ok")
    s2 = FakeStore(backend_name="s2", health_status="error")
    router = MemoryRouter([s1, s2])
    h = await router.health()
    assert h["status"] == "degraded"


async def test_health_all_error_is_error() -> None:
    """All children unhealthy (including raises) → ``error``."""
    s1 = FakeStore(backend_name="s1", raise_on={"health"})
    s2 = FakeStore(backend_name="s2", health_status="error")
    router = MemoryRouter([s1, s2])
    h = await router.health()
    assert h["status"] == "error"
    statuses = [row["status"] for row in h["stores"]]
    assert statuses == ["error", "error"]


# ---------------------------------------------------------------------------
# 10. Composition (router-of-routers)
# ---------------------------------------------------------------------------


async def test_router_of_routers_recall() -> None:
    """A router containing another router works end-to-end for recall."""
    inner_s1 = FakeStore(backend_name="inner-s1", recall_hits=[_hit("i1")])
    inner_s2 = FakeStore(backend_name="inner-s2", recall_hits=[_hit("i2")])
    inner_router = MemoryRouter([inner_s1, inner_s2])

    outer_s = FakeStore(backend_name="outer-s", recall_hits=[_hit("o1")])
    outer_router = MemoryRouter([inner_router, outer_s])

    resp = await outer_router.recall(RecallRequest(agent_id="a", query="q", k=10))
    assert {h.id for h in resp.results} == {"i1", "i2", "o1"}


async def test_router_of_routers_capabilities_union() -> None:
    """Capabilities union propagates through nested routers."""
    inner = MemoryRouter(
        [
            FakeStore(backend_name="i1", capabilities={Capability.SEMANTIC}),
            FakeStore(backend_name="i2", capabilities={Capability.VECTOR}),
        ]
    )
    outer = MemoryRouter([inner, FakeStore(backend_name="o", capabilities={Capability.GRAPH})])
    assert outer.capabilities == {Capability.SEMANTIC, Capability.VECTOR, Capability.GRAPH}


# ---------------------------------------------------------------------------
# 11. Fan-out parallelism sanity check
# ---------------------------------------------------------------------------


async def test_recall_runs_stores_concurrently() -> None:
    """Fan-out uses ``asyncio.gather`` — slow stores don't serialize."""

    class SlowStore(FakeStore):
        async def recall(self, req: RecallRequest) -> RecallResponse:
            await asyncio.sleep(0.05)
            return await super().recall(req)

    s1 = SlowStore(backend_name="s1", recall_hits=[_hit("a")])
    s2 = SlowStore(backend_name="s2", recall_hits=[_hit("b")])
    router = MemoryRouter([s1, s2])

    loop = asyncio.get_running_loop()
    started = loop.time()
    resp = await router.recall(RecallRequest(agent_id="a", query="q", k=10))
    elapsed = loop.time() - started

    # Two stores each sleeping 50ms — concurrent execution should finish in
    # well under 100ms wallclock. Use a generous bound to keep CI happy.
    assert elapsed < 0.18
    assert {h.id for h in resp.results} == {"a", "b"}


# ---------------------------------------------------------------------------
# 12. Neighborable Protocol structural check
# ---------------------------------------------------------------------------


def test_fake_graph_store_is_neighborable() -> None:
    """The :class:`Neighborable` Protocol is ``@runtime_checkable``."""
    assert isinstance(FakeGraphStore(), Neighborable)
    # A plain :class:`FakeStore` is NOT a Neighborable.
    assert not isinstance(FakeStore(backend_name="x"), Neighborable)
