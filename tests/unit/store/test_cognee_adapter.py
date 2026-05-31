"""Unit tests for :class:`memwire.store.cognee_adapter.CogneeStore`.

These tests use :class:`unittest.mock.AsyncMock` / :class:`MagicMock` to
stand in for the real ``cognee`` module â€” the Cognee SDK is never
touched. The goal is to prove the adapter translates memwire requests into
the right Cognee calls and maps the mocked responses back into the memwire
response models.

Integration tests that exercise the real SDK live under
``tests/integration/store/test_cognee_adapter.py`` and are gated by the
``COGNEE_LLM_API_KEY`` environment variable (Cognee needs an LLM to
build its knowledge graph).
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from memwire.models import (
    ExpireAction,
    ExpirePolicy,
    ExpireRequest,
    ForgetRequest,
    MemoryType,
    MergeRequest,
    MergeStrategy,
    RecallRequest,
    RememberRequest,
)
from memwire.store import Capability, MemoryStore
from memwire.store.cognee_adapter import (
    CogneeStore,
    _unwrap_content,
    _wrap_content,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_module(**overrides: Any) -> MagicMock:
    """Return a fresh ``MagicMock`` modelling the cognee module surface.

    Default async methods (``add``, ``remember``, ``search``, ``recall``,
    ``forget``) return empty-ish values; individual tests override the
    methods they care about via ``overrides``.
    """
    module = MagicMock()
    # Async methods.
    module.add = AsyncMock(return_value=None)
    module.remember = AsyncMock(return_value=None)
    module.search = AsyncMock(return_value=[])
    module.recall = AsyncMock(return_value=[])
    module.forget = AsyncMock(return_value={"status": "ok"})
    # SearchType enum surface â€” adapter passes the GRAPH_COMPLETION value.
    module.SearchType = MagicMock()
    module.SearchType.GRAPH_COMPLETION = "GRAPH_COMPLETION"
    # datasets namespace for health probes.
    module.datasets = MagicMock()
    module.datasets.list_datasets = MagicMock(return_value=[])
    # Apply per-test overrides on the top-level module attribute.
    for key, value in overrides.items():
        setattr(module, key, value)
    return module


def _wrapped_payload(
    *,
    amp_id: str = "cog:test-id",
    agent_id: str = "agent-a",
    type: str = "semantic",
    content: str = "fact",
    confidence: float | None = None,
    created_at_ms: int | None = None,
) -> str:
    """Build a wrapped Cognee text blob the way :meth:`remember` would."""
    payload: dict[str, Any] = {
        "id": amp_id,
        "agent_id": agent_id,
        "type": type,
        "created_at": created_at_ms if created_at_ms is not None else int(time.time() * 1000),
    }
    if confidence is not None:
        payload["confidence"] = confidence
    return _wrap_content(payload, content)


# ---------------------------------------------------------------------------
# Construction / Protocol conformance
# ---------------------------------------------------------------------------


def test_cogneestore_is_a_memory_store() -> None:
    """``isinstance`` against the runtime-checkable Protocol must succeed."""
    store = CogneeStore(client=_make_module())
    assert isinstance(store, MemoryStore)


def test_from_url_default_resolves_to_memwire_dataset() -> None:
    """``cognee://default`` resolves to dataset='memwire'."""
    store = CogneeStore.from_url("cognee://default", client=_make_module())
    assert isinstance(store, CogneeStore)
    assert store.dataset == "memwire"


def test_from_url_custom_dataset() -> None:
    """A non-default host slot is used verbatim as the dataset name."""
    store = CogneeStore.from_url("cognee://team-knowledge", client=_make_module())
    assert store.dataset == "team-knowledge"


def test_from_url_rejects_wrong_scheme() -> None:
    """A non-``cognee://`` scheme must raise."""
    with pytest.raises(ValueError, match="cognee://"):
        CogneeStore.from_url("sqlite-vec://./mem.db")


def test_capabilities_set_includes_graph() -> None:
    """Cognee declares graph capability as its differentiator."""
    store = CogneeStore(client=_make_module())
    assert store.capabilities == {
        Capability.SEMANTIC,
        Capability.EPISODIC,
        Capability.VECTOR,
        Capability.GRAPH,
    }


def test_backend_name_constant() -> None:
    """The class exposes the canonical backend name."""
    assert CogneeStore.BACKEND_NAME == "cognee"


# ---------------------------------------------------------------------------
# Header encode/decode round-trip
# ---------------------------------------------------------------------------


def test_wrap_and_unwrap_round_trip() -> None:
    """An memwire-wrapped blob decodes back into its original overlay + content."""
    payload = {
        "id": "cog:abc",
        "agent_id": "agent-a",
        "type": "semantic",
        "created_at": 1716800000000,
        "confidence": 0.9,
    }
    wrapped = _wrap_content(payload, "the fact body")
    overlay, content = _unwrap_content(wrapped)
    assert overlay == payload
    assert content == "the fact body"


def test_unwrap_passes_through_unmarked_blob() -> None:
    """Text ingested outside the adapter has no header â€” returned verbatim."""
    overlay, content = _unwrap_content("just a fact without a header")
    assert overlay == {}
    assert content == "just a fact without a header"


# ---------------------------------------------------------------------------
# remember()
# ---------------------------------------------------------------------------


async def test_remember_calls_module_remember_with_wrapped_content() -> None:
    """``remember`` prepends the memwire header and dispatches to module.remember."""
    module = _make_module()
    store = CogneeStore(client=module, dataset="amp")

    response = await store.remember(
        RememberRequest(
            agent_id="agent-a",
            user_id="alice@example.com",
            type=MemoryType.SEMANTIC,
            content="Alice prefers email over phone",
            confidence=0.9,
            source="onboarding-form",
            metadata={"channel": "support"},
        )
    )

    module.remember.assert_awaited_once()
    args, kwargs = module.remember.await_args
    # First positional arg is the wrapped content.
    wrapped_content = args[0]
    assert wrapped_content.startswith("<AMP_META>")
    assert kwargs.get("dataset_name") == "amp"
    # The header parses back into the right overlay.
    overlay, rest = _unwrap_content(wrapped_content)
    assert overlay["agent_id"] == "agent-a"
    assert overlay["type"] == "semantic"
    assert overlay["confidence"] == 0.9
    assert overlay["source"] == "onboarding-form"
    assert overlay["metadata"] == {"channel": "support"}
    assert rest == "Alice prefers email over phone"

    # Adapter-synthesised id is stable and memwire-prefixed.
    assert response.id.startswith("cog:")
    assert response.stores == ["cognee"]
    assert response.pending_approval is False


async def test_remember_with_approval_required_skips_module() -> None:
    """``approval_required=True`` short-circuits â€” no Cognee call."""
    module = _make_module()
    store = CogneeStore(client=module)

    response = await store.remember(
        RememberRequest(
            agent_id="agent-a",
            type=MemoryType.SEMANTIC,
            content="High-risk fact",
            approval_required=True,
        )
    )

    module.remember.assert_not_awaited()
    module.add.assert_not_awaited()
    assert response.pending_approval is True
    assert response.stores == []


async def test_remember_falls_back_to_add_when_remember_missing() -> None:
    """An older Cognee mock without ``remember`` is dispatched via ``add``."""
    module = _make_module()
    # Simulate an SDK that doesn't expose the v1 ``remember`` surface.
    del module.remember
    store = CogneeStore(client=module)

    response = await store.remember(
        RememberRequest(
            agent_id="agent-a",
            type=MemoryType.SEMANTIC,
            content="fact",
        )
    )
    module.add.assert_awaited_once()
    assert response.id.startswith("cog:")


# ---------------------------------------------------------------------------
# recall()
# ---------------------------------------------------------------------------


async def test_recall_calls_module_recall_and_maps_results() -> None:
    """``recall`` maps Cognee's response entries into :class:`RecallHit`."""
    module = _make_module()
    wrapped = _wrapped_payload(
        amp_id="cog:row-1",
        agent_id="agent-a",
        type="semantic",
        content="Alice prefers email",
        confidence=0.9,
        created_at_ms=1716800000000,
    )
    module.recall.return_value = [
        {"text": wrapped, "score": 0.85, "metadata": {}, "source": "graph"},
    ]
    store = CogneeStore(client=module, dataset="amp")

    response = await store.recall(
        RecallRequest(
            agent_id="agent-a",
            query="anything",
            k=3,
        )
    )
    module.recall.assert_awaited_once()
    args, kwargs = module.recall.await_args
    assert args[0] == "anything"
    assert kwargs.get("top_k") == 3
    assert kwargs.get("datasets") == ["amp"]
    # Adapter pins GRAPH_COMPLETION as the default query_type.
    assert kwargs.get("query_type") == "GRAPH_COMPLETION"

    assert len(response.results) == 1
    hit = response.results[0]
    assert hit.id == "cog:row-1"
    assert hit.type is MemoryType.SEMANTIC
    assert hit.content == "Alice prefers email"
    assert hit.score == pytest.approx(0.85)
    assert hit.source_store == "cognee"
    assert response.stores_queried == ["cognee"]


async def test_recall_filters_by_type() -> None:
    """``types=[SEMANTIC]`` filters out non-semantic Cognee rows."""
    module = _make_module()
    module.recall.return_value = [
        {"text": _wrapped_payload(amp_id="r-1", agent_id="agent-a", type="semantic", content="s")},
        {"text": _wrapped_payload(amp_id="r-2", agent_id="agent-a", type="episodic", content="e")},
    ]
    store = CogneeStore(client=module)

    response = await store.recall(
        RecallRequest(
            agent_id="agent-a",
            query="anything",
            types=[MemoryType.SEMANTIC],
        )
    )
    ids = [hit.id for hit in response.results]
    assert ids == ["r-1"]


async def test_recall_filters_by_agent_id() -> None:
    """Rows wearing a different ``agent_id`` overlay are filtered out."""
    module = _make_module()
    module.recall.return_value = [
        {"text": _wrapped_payload(amp_id="mine", agent_id="agent-a", content="ours")},
        {"text": _wrapped_payload(amp_id="theirs", agent_id="agent-b", content="theirs")},
    ]
    store = CogneeStore(client=module)
    response = await store.recall(RecallRequest(agent_id="agent-a", query="q"))
    assert [h.id for h in response.results] == ["mine"]


async def test_recall_falls_back_to_search_when_recall_missing() -> None:
    """If module has no ``recall`` surface, ``search`` is used."""
    module = _make_module()
    del module.recall
    wrapped = _wrapped_payload(amp_id="cog:r1", agent_id="agent-a", content="text")
    module.search.return_value = [{"text": wrapped, "score": 0.7}]

    store = CogneeStore(client=module)
    response = await store.recall(RecallRequest(agent_id="agent-a", query="q"))
    module.search.assert_awaited_once()
    assert len(response.results) == 1


async def test_recall_defaults_score_when_missing() -> None:
    """Rows without a numeric ``score`` default to 0.5."""
    module = _make_module()
    wrapped = _wrapped_payload(amp_id="cog:r1", agent_id="agent-a", content="text")
    module.recall.return_value = [{"text": wrapped}]
    store = CogneeStore(client=module)
    response = await store.recall(RecallRequest(agent_id="agent-a", query="q"))
    assert response.results[0].score == pytest.approx(0.5)


async def test_recall_honours_fresher_than_days() -> None:
    """``fresher_than_days=7`` drops rows older than the cutoff."""
    module = _make_module()
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - (30 * 86_400_000)
    new_ms = now_ms - (1 * 86_400_000)
    module.recall.return_value = [
        {
            "text": _wrapped_payload(
                amp_id="old", agent_id="agent-a", content="o", created_at_ms=old_ms
            ),
            "score": 0.5,
        },
        {
            "text": _wrapped_payload(
                amp_id="new", agent_id="agent-a", content="n", created_at_ms=new_ms
            ),
            "score": 0.5,
        },
    ]
    store = CogneeStore(client=module)
    response = await store.recall(RecallRequest(agent_id="agent-a", query="q", fresher_than_days=7))
    assert [h.id for h in response.results] == ["new"]


async def test_recall_handles_pydantic_model_dump_style_entry() -> None:
    """A response entry exposing ``model_dump`` is handled like a dict."""
    module = _make_module()
    fake_entry = MagicMock()
    wrapped = _wrapped_payload(amp_id="cog:p1", agent_id="agent-a", content="hello")
    fake_entry.model_dump.return_value = {"text": wrapped, "score": 0.9, "source": "graph"}
    module.recall.return_value = [fake_entry]
    store = CogneeStore(client=module)
    response = await store.recall(RecallRequest(agent_id="agent-a", query="q"))
    assert response.results[0].id == "cog:p1"
    assert response.results[0].score == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# forget()
# ---------------------------------------------------------------------------


async def test_forget_without_ids_or_filter_raises() -> None:
    """No-scope mass-delete protection (spec Â§3.3): must raise ``ValueError``."""
    store = CogneeStore(client=_make_module())
    with pytest.raises(ValueError, match=r"ids.*filter"):
        await store.forget(ForgetRequest(agent_id="agent-a"))


async def test_forget_with_uuid_ids_calls_module_forget() -> None:
    """Plain ids (Cognee UUIDs) are dispatched per-id to module.forget."""
    module = _make_module()
    store = CogneeStore(client=module, dataset="amp")

    response = await store.forget(
        ForgetRequest(
            agent_id="agent-a",
            ids=["data-uuid-1", "data-uuid-2"],
        )
    )
    assert module.forget.await_count == 2
    forgotten_ids = {call.kwargs["data_id"] for call in module.forget.await_args_list}
    assert forgotten_ids == {"data-uuid-1", "data-uuid-2"}
    for call in module.forget.await_args_list:
        assert call.kwargs["dataset"] == "amp"
    assert response.forgotten_ids == ["data-uuid-1", "data-uuid-2"]
    assert response.stores[0].store == "cognee"
    assert response.stores[0].count == 2


async def test_forget_skips_synthetic_cog_ids_silently() -> None:
    """Adapter-synthetic ``cog:`` ids are no-ops at the Cognee layer."""
    module = _make_module()
    store = CogneeStore(client=module)
    response = await store.forget(ForgetRequest(agent_id="agent-a", ids=["cog:fakeid"]))
    module.forget.assert_not_awaited()
    assert response.forgotten_ids == []


async def test_forget_filter_with_data_id_dispatches() -> None:
    """``filter={'data_id': uuid}`` resolves to a single per-id delete."""
    module = _make_module()
    store = CogneeStore(client=module)
    response = await store.forget(
        ForgetRequest(agent_id="agent-a", filter={"data_id": "real-uuid"})
    )
    module.forget.assert_awaited_once()
    assert response.forgotten_ids == ["real-uuid"]


async def test_forget_filter_other_shape_raises() -> None:
    """Any non-``data_id`` filter shape is rejected as unsupported."""
    store = CogneeStore(client=_make_module())
    with pytest.raises(ValueError, match="data_id"):
        await store.forget(ForgetRequest(agent_id="agent-a", filter={"type": "semantic"}))


async def test_forget_swallows_per_id_errors() -> None:
    """A delete that raises mid-batch is swallowed; the rest proceed."""
    module = _make_module()
    module.forget = AsyncMock(side_effect=[RuntimeError("boom"), {"status": "ok"}])
    store = CogneeStore(client=module)
    response = await store.forget(
        ForgetRequest(agent_id="agent-a", ids=["missing-uuid", "real-uuid"])
    )
    assert response.forgotten_ids == ["real-uuid"]


# ---------------------------------------------------------------------------
# merge()
# ---------------------------------------------------------------------------


async def test_merge_keep_canonical_does_not_write_new_row() -> None:
    """``keep_canonical`` preserves the canonical row; only duplicates drop."""
    module = _make_module()
    # ``search`` is used by merge to resolve rows by id; return Cognee
    # UUID-style ids so the per-id delete actually fires.
    module.search.return_value = [
        {"text": _wrapped_payload(amp_id="canon-uuid", agent_id="agent-a", content="A")},
        {"text": _wrapped_payload(amp_id="dup-1-uuid", agent_id="agent-a", content="A1")},
    ]
    store = CogneeStore(client=module)

    response = await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon-uuid",
            duplicates=["dup-1-uuid"],
            strategy=MergeStrategy.KEEP_CANONICAL,
        )
    )
    # No new memory written on keep_canonical.
    module.remember.assert_not_awaited()
    assert response.canonical == "canon-uuid"
    assert response.strategy_used is MergeStrategy.KEEP_CANONICAL
    # One duplicate was attempted (Cognee-UUID style ids are dispatched).
    assert response.merged_count == 1


async def test_merge_content_writes_new_canonical_with_joined_content() -> None:
    """``merge_content`` writes a new canonical via remember + drops originals."""
    module = _make_module()
    module.search.return_value = [
        {
            "text": _wrapped_payload(
                amp_id="canon-uuid",
                agent_id="agent-a",
                content="Alice Smith",
                confidence=0.7,
            ),
        },
        {
            "text": _wrapped_payload(
                amp_id="dup-uuid",
                agent_id="agent-a",
                content="Alice S.",
                confidence=0.4,
            ),
        },
    ]
    store = CogneeStore(client=module)

    response = await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon-uuid",
            duplicates=["dup-uuid"],
            strategy=MergeStrategy.MERGE_CONTENT,
        )
    )
    # The merged canonical is written via the public remember surface,
    # which delegates to module.remember.
    module.remember.assert_awaited()
    written_blob = module.remember.await_args_list[0].args[0]
    assert "Alice Smith" in written_blob
    assert "Alice S." in written_blob
    assert " | " in written_blob
    assert response.merged_count == 1
    assert response.strategy_used is MergeStrategy.MERGE_CONTENT


# ---------------------------------------------------------------------------
# expire()
# ---------------------------------------------------------------------------


async def test_expire_older_than_days_forget_deletes_only_old_rows() -> None:
    """``older_than_days=30`` + ``forget`` removes only old adapter-owned rows."""
    module = _make_module()
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - (60 * 86_400_000)
    new_ms = now_ms - (1 * 86_400_000)
    module.search.return_value = [
        {
            "text": _wrapped_payload(
                amp_id="old-uuid",
                agent_id="agent-a",
                content="o",
                created_at_ms=old_ms,
            )
        },
        {
            "text": _wrapped_payload(
                amp_id="new-uuid",
                agent_id="agent-a",
                content="n",
                created_at_ms=new_ms,
            )
        },
    ]
    store = CogneeStore(client=module)

    response = await store.expire(
        ExpireRequest(
            agent_id="agent-a",
            policy=ExpirePolicy(older_than_days=30),
            action=ExpireAction.FORGET,
        )
    )
    # Only the old row's id was sent to module.forget.
    delete_ids = {call.kwargs["data_id"] for call in module.forget.await_args_list}
    assert delete_ids == {"old-uuid"}
    assert response.matched_count == 1
    assert response.action_taken is ExpireAction.FORGET


async def test_expire_no_recall_in_days_unsupported() -> None:
    """``no_recall_in_days`` MUST raise â€” Cognee lacks last-recalled-at tracking."""
    store = CogneeStore(client=_make_module())
    with pytest.raises(ValueError, match="no_recall_in_days"):
        await store.expire(
            ExpireRequest(
                agent_id="agent-a",
                policy=ExpirePolicy(no_recall_in_days=30),
            )
        )


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------


async def test_health_ok_when_module_responds() -> None:
    """A successful probe returns the canonical ok shape with dataset."""
    module = _make_module()
    store = CogneeStore(client=module, dataset="my-set")
    health = await store.health()
    assert health["status"] == "ok"
    assert health["backend"] == "cognee"
    assert health["dataset"] == "my-set"


async def test_health_error_when_probe_raises() -> None:
    """A raising probe surfaces an error shape without leaking the stack."""
    module = _make_module()
    module.datasets.list_datasets = MagicMock(side_effect=RuntimeError("backend down"))
    store = CogneeStore(client=module)
    health = await store.health()
    assert health["status"] == "error"
    assert health["backend"] == "cognee"
    assert "backend down" in health["error"]
