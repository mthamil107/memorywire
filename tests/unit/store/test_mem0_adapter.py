"""Unit tests for :class:`memorywire.store.mem0_adapter.Mem0Store`.

These tests use :class:`unittest.mock.MagicMock` to stand in for the real
``mem0.Memory`` client â€” the mem0 SDK is never touched. The goal is to
prove the adapter translates memorywire requests into the right mem0 calls and
maps the mocked responses back into the memorywire response models correctly.

Integration tests that exercise the real SDK live under
``tests/integration/store/test_mem0_adapter.py`` and are gated by
``OPENAI_API_KEY``.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from memorywire.models import (
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
from memorywire.store import Capability, MemoryStore
from memorywire.store.mem0_adapter import Mem0Store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(**overrides: object) -> MagicMock:
    """Return a fresh ``MagicMock`` configured with sensible defaults.

    Individual tests override the methods they care about via ``overrides``.
    The defaults here return shapes that mirror mem0 v1.1+ wire format
    (``{"results": [...]}``) so the adapter's normalisation paths get
    exercised in every test.
    """
    client = MagicMock()
    client.add.return_value = {
        "results": [{"id": "mem-default-id", "memory": "stored fact", "event": "ADD"}]
    }
    client.search.return_value = {"results": []}
    client.get_all.return_value = {"results": []}
    client.get.return_value = None
    client.delete.return_value = None
    client.update.return_value = {"message": "Memory updated successfully!"}
    for key, value in overrides.items():
        getattr(client, key).return_value = value
    return client


# ---------------------------------------------------------------------------
# Construction / Protocol conformance
# ---------------------------------------------------------------------------


def test_mem0store_is_a_memory_store() -> None:
    """``isinstance`` against the runtime-checkable Protocol must succeed."""
    store = Mem0Store(client=_make_client())
    assert isinstance(store, MemoryStore)


def test_from_url_returns_instance() -> None:
    """``Mem0Store.from_url('mem0://default')`` builds a usable adapter."""
    store = Mem0Store.from_url("mem0://default", client=_make_client())
    assert isinstance(store, Mem0Store)


def test_from_url_rejects_wrong_scheme() -> None:
    """A non-``mem0://`` scheme must raise."""
    with pytest.raises(ValueError, match="mem0://"):
        Mem0Store.from_url("sqlite-vec://./mem.db")


def test_capabilities_set_matches_spec() -> None:
    """Capability set is exactly ``{semantic, episodic, vector}``."""
    store = Mem0Store(client=_make_client())
    assert store.capabilities == {
        Capability.SEMANTIC,
        Capability.EPISODIC,
        Capability.VECTOR,
    }


# ---------------------------------------------------------------------------
# remember()
# ---------------------------------------------------------------------------


async def test_remember_calls_client_add_with_expected_kwargs() -> None:
    """``remember`` flattens memorywire fields into mem0 metadata and forwards them."""
    client = _make_client()
    client.add.return_value = {"results": [{"id": "mem-1", "memory": "hi", "event": "ADD"}]}
    store = Mem0Store(client=client)

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

    # One call into mem0, with the content positional and the memorywire-overlay
    # keys flattened into metadata.
    client.add.assert_called_once()
    args, kwargs = client.add.call_args
    assert args == ("Alice prefers email over phone",)
    assert kwargs["user_id"] == "alice@example.com"
    metadata = kwargs["metadata"]
    assert metadata["amp_type"] == "semantic"
    assert metadata["amp_confidence"] == 0.9
    assert metadata["amp_source"] == "onboarding-form"
    # Caller-supplied metadata is preserved alongside the overlay.
    assert metadata["channel"] == "support"

    assert response.id == "mem-1"
    assert response.stores == ["mem0"]
    assert response.pending_approval is False


async def test_remember_falls_back_to_agent_id_when_no_user_id() -> None:
    """When ``user_id`` is absent, the adapter uses ``agent_id`` for mem0 scoping."""
    client = _make_client()
    store = Mem0Store(client=client)

    await store.remember(
        RememberRequest(
            agent_id="agent-only",
            type=MemoryType.EPISODIC,
            content="Standalone episode",
        )
    )

    _, kwargs = client.add.call_args
    assert "user_id" not in kwargs
    assert kwargs["agent_id"] == "agent-only"


async def test_remember_with_approval_required_skips_client() -> None:
    """``approval_required=True`` short-circuits â€” no mem0 call, ``pending_approval``."""
    client = _make_client()
    store = Mem0Store(client=client)

    response = await store.remember(
        RememberRequest(
            agent_id="agent-a",
            user_id="alice",
            type=MemoryType.SEMANTIC,
            content="High-risk fact",
            approval_required=True,
        )
    )

    client.add.assert_not_called()
    assert response.pending_approval is True
    assert response.stores == []


async def test_remember_handles_legacy_list_response() -> None:
    """Older mem0 builds returned a bare list. The adapter normalises it."""
    client = _make_client()
    client.add.return_value = [{"id": "legacy-id", "memory": "x", "event": "ADD"}]
    store = Mem0Store(client=client)

    response = await store.remember(
        RememberRequest(
            agent_id="agent-a",
            user_id="u",
            type=MemoryType.SEMANTIC,
            content="legacy",
        )
    )
    assert response.id == "legacy-id"


# ---------------------------------------------------------------------------
# recall()
# ---------------------------------------------------------------------------


async def test_recall_calls_client_search_and_maps_results() -> None:
    """``recall`` maps mem0's ``results`` rows into :class:`RecallHit`."""
    client = _make_client()
    client.search.return_value = {
        "results": [
            {
                "id": "m1",
                "memory": "test",
                "score": 0.9,
                "metadata": {"amp_type": "semantic"},
            }
        ]
    }
    store = Mem0Store(client=client)

    response = await store.recall(
        RecallRequest(
            agent_id="agent-a",
            user_id="alice",
            query="anything",
            k=3,
        )
    )

    client.search.assert_called_once()
    _, kwargs = client.search.call_args
    assert kwargs["top_k"] == 3
    assert kwargs["filters"]["user_id"] == "alice"

    assert len(response.results) == 1
    hit = response.results[0]
    assert hit.id == "m1"
    assert hit.type is MemoryType.SEMANTIC
    assert hit.content == "test"
    assert hit.score == pytest.approx(0.9)
    assert hit.source_store == "mem0"
    assert response.stores_queried == ["mem0"]


async def test_recall_filters_by_type() -> None:
    """``types=[SEMANTIC]`` filters out non-semantic mem0 rows."""
    client = _make_client()
    client.search.return_value = {
        "results": [
            {"id": "m1", "memory": "fact", "score": 0.9, "metadata": {"amp_type": "semantic"}},
            {"id": "m2", "memory": "event", "score": 0.8, "metadata": {"amp_type": "episodic"}},
            {"id": "m3", "memory": "feeling", "score": 0.7, "metadata": {"amp_type": "emotional"}},
        ]
    }
    store = Mem0Store(client=client)

    response = await store.recall(
        RecallRequest(
            agent_id="agent-a",
            user_id="alice",
            query="anything",
            types=[MemoryType.SEMANTIC],
        )
    )
    ids = [hit.id for hit in response.results]
    assert ids == ["m1"]


async def test_recall_filters_by_fresher_than_days() -> None:
    """Rows older than the freshness window are dropped client-side."""
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - (60 * 86_400_000)  # 60 days old
    new_ms = now_ms - (1 * 86_400_000)  # 1 day old

    client = _make_client()
    client.search.return_value = {
        "results": [
            {
                "id": "old",
                "memory": "ancient",
                "score": 0.5,
                "metadata": {"amp_type": "semantic"},
                "created_at": old_ms,
            },
            {
                "id": "new",
                "memory": "fresh",
                "score": 0.5,
                "metadata": {"amp_type": "semantic"},
                "created_at": new_ms,
            },
        ]
    }
    store = Mem0Store(client=client)

    response = await store.recall(
        RecallRequest(
            agent_id="agent-a",
            user_id="alice",
            query="anything",
            fresher_than_days=30,
        )
    )
    assert [hit.id for hit in response.results] == ["new"]


async def test_recall_defaults_missing_amp_type_to_semantic() -> None:
    """Rows without an ``amp_type`` metadata tag default to ``semantic``."""
    client = _make_client()
    client.search.return_value = {
        "results": [{"id": "m9", "memory": "untagged", "score": 0.1, "metadata": {}}]
    }
    store = Mem0Store(client=client)

    response = await store.recall(RecallRequest(agent_id="agent-a", user_id="alice", query="q"))
    assert response.results[0].type is MemoryType.SEMANTIC


# ---------------------------------------------------------------------------
# forget()
# ---------------------------------------------------------------------------


async def test_forget_by_ids_calls_delete_for_each() -> None:
    """``forget(ids=[...])`` issues one ``client.delete`` per id."""
    client = _make_client()
    store = Mem0Store(client=client)

    response = await store.forget(
        ForgetRequest(
            agent_id="agent-a",
            ids=["m1", "m2"],
        )
    )
    assert client.delete.call_count == 2
    called_ids = {call.args[0] for call in client.delete.call_args_list}
    assert called_ids == {"m1", "m2"}
    assert response.forgotten_ids == ["m1", "m2"]
    assert response.stores[0].store == "mem0"
    assert response.stores[0].count == 2


async def test_forget_without_ids_or_filter_raises() -> None:
    """No-scope mass-delete protection (spec Â§3.3): must raise ``ValueError``."""
    store = Mem0Store(client=_make_client())
    with pytest.raises(ValueError, match=r"ids.*filter"):
        await store.forget(ForgetRequest(agent_id="agent-a"))


async def test_forget_by_filter_calls_get_all_then_delete() -> None:
    """A filter-only forget resolves ids via ``get_all`` then deletes them."""
    client = _make_client()
    client.get_all.return_value = {
        "results": [
            {
                "id": "alice-1",
                "memory": "fact",
                "user_id": "alice",
                "metadata": {"amp_type": "episodic"},
            },
            {
                "id": "alice-2",
                "memory": "other",
                "user_id": "alice",
                "metadata": {"amp_type": "semantic"},
            },
        ]
    }
    store = Mem0Store(client=client)

    response = await store.forget(
        ForgetRequest(
            agent_id="agent-a",
            user_id="alice",
            filter={"user_id": "alice", "type": "episodic"},
        )
    )
    client.get_all.assert_called_once()
    # Only the episodic one should be deleted.
    delete_ids = {call.args[0] for call in client.delete.call_args_list}
    assert delete_ids == {"alice-1"}
    assert response.forgotten_ids == ["alice-1"]


async def test_forget_continues_on_per_id_delete_error() -> None:
    """A delete that raises mid-batch is swallowed; the rest proceed."""
    client = _make_client()
    client.delete.side_effect = [ValueError("not found"), None]
    store = Mem0Store(client=client)

    response = await store.forget(ForgetRequest(agent_id="agent-a", ids=["missing", "real"]))
    # Only the second id is recorded as forgotten.
    assert response.forgotten_ids == ["real"]


# ---------------------------------------------------------------------------
# merge()
# ---------------------------------------------------------------------------


async def test_merge_keep_canonical_deletes_only_duplicates() -> None:
    """``keep_canonical`` preserves the canonical row verbatim and drops dupes.

    Semantic choice: spec Â§3.4 says canonical is "preserved verbatim;
    duplicates are dropped after pointer migration". This adapter only owns
    the dropping half â€” pointer migration is router-layer (Phase 4). So we
    assert: no ``client.add`` is called (canonical stays in place) and
    each duplicate id is passed to ``client.delete``.
    """
    client = _make_client()
    # Both duplicate ids resolve to mem0 records.
    client.get.side_effect = [
        {"id": "canon", "memory": "Alice Smith"},
        {"id": "d1", "memory": "alice (dup1)"},
        {"id": "d2", "memory": "alice (dup2)"},
    ]
    store = Mem0Store(client=client)

    response = await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon",
            duplicates=["d1", "d2"],
            strategy=MergeStrategy.KEEP_CANONICAL,
        )
    )
    # No new canonical written.
    client.add.assert_not_called()
    # Both duplicates deleted.
    delete_ids = {call.args[0] for call in client.delete.call_args_list}
    assert delete_ids == {"d1", "d2"}
    assert response.canonical == "canon"
    assert response.merged_count == 2
    assert response.strategy_used is MergeStrategy.KEEP_CANONICAL


async def test_merge_content_writes_new_canonical_with_joined_content() -> None:
    """``merge_content`` issues a new ``client.add`` with concatenated content."""
    client = _make_client()
    client.get.side_effect = [
        {"id": "canon", "memory": "Alice Smith", "metadata": {"amp_confidence": 0.7}},
        {"id": "d1", "memory": "Alice S.", "metadata": {"amp_confidence": 0.4}},
    ]
    client.add.return_value = {"results": [{"id": "new-canon", "memory": "merged", "event": "ADD"}]}
    store = Mem0Store(client=client)

    response = await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon",
            duplicates=["d1"],
            strategy=MergeStrategy.MERGE_CONTENT,
        )
    )
    client.add.assert_called_once()
    args, kwargs = client.add.call_args
    # spec-gap: " | " separator instead of "\n"; documented in adapter.
    assert "Alice Smith" in args[0]
    assert "Alice S." in args[0]
    assert " | " in args[0]
    # max(confidence) wins per spec.
    assert kwargs["metadata"]["amp_confidence"] == 0.7
    assert response.canonical == "new-canon"
    assert response.merged_count == 1


async def test_merge_keep_highest_confidence_picks_top_row() -> None:
    """``keep_highest_confidence`` reuses the high-confidence row's content."""
    client = _make_client()
    client.get.side_effect = [
        {"id": "canon", "memory": "Alice Smith", "metadata": {"amp_confidence": 0.4}},
        {"id": "d1", "memory": "Alice the Great", "metadata": {"amp_confidence": 0.95}},
    ]
    client.add.return_value = {
        "results": [{"id": "new-canon", "memory": "Alice the Great", "event": "ADD"}]
    }
    store = Mem0Store(client=client)

    await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon",
            duplicates=["d1"],
            strategy=MergeStrategy.KEEP_HIGHEST_CONFIDENCE,
        )
    )
    args, _kwargs = client.add.call_args
    assert args[0] == "Alice the Great"


# ---------------------------------------------------------------------------
# expire()
# ---------------------------------------------------------------------------


async def test_expire_older_than_days_forget_deletes_matches() -> None:
    """``older_than_days=30`` + ``action=forget`` removes only old rows."""
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - (60 * 86_400_000)
    new_ms = now_ms - (1 * 86_400_000)

    client = _make_client()
    client.get_all.return_value = {
        "results": [
            {
                "id": "old",
                "memory": "stale",
                "metadata": {"amp_type": "semantic"},
                "created_at": old_ms,
            },
            {
                "id": "new",
                "memory": "fresh",
                "metadata": {"amp_type": "semantic"},
                "created_at": new_ms,
            },
        ]
    }
    store = Mem0Store(client=client)

    response = await store.expire(
        ExpireRequest(
            agent_id="agent-a",
            policy=ExpirePolicy(older_than_days=30),
            action=ExpireAction.FORGET,
        )
    )
    delete_ids = {call.args[0] for call in client.delete.call_args_list}
    assert delete_ids == {"old"}
    assert response.matched_count == 1
    assert response.action_taken is ExpireAction.FORGET


async def test_expire_no_recall_in_days_unsupported() -> None:
    """``no_recall_in_days`` MUST raise â€” mem0 lacks last-recalled-at tracking."""
    store = Mem0Store(client=_make_client())
    with pytest.raises(ValueError, match="no_recall_in_days"):
        await store.expire(
            ExpireRequest(
                agent_id="agent-a",
                policy=ExpirePolicy(no_recall_in_days=30),
            )
        )


async def test_expire_demote_updates_confidence() -> None:
    """``action=demote`` multiplies ``amp_confidence`` by 0.25 via ``update``."""
    now_ms = int(time.time() * 1000)
    client = _make_client()
    client.get_all.return_value = {
        "results": [
            {
                "id": "row-a",
                "memory": "low-conf fact",
                "metadata": {"amp_type": "semantic", "amp_confidence": 0.5},
                "created_at": now_ms - (200 * 86_400_000),
            }
        ]
    }
    store = Mem0Store(client=client)

    await store.expire(
        ExpireRequest(
            agent_id="agent-a",
            policy=ExpirePolicy(older_than_days=180),
            action=ExpireAction.DEMOTE,
        )
    )
    client.update.assert_called_once()
    _args, kwargs = client.update.call_args
    assert kwargs["metadata"]["amp_confidence"] == pytest.approx(0.5 * 0.25)


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------


async def test_health_ok_when_client_responds() -> None:
    """A successful probe returns the canonical ok shape."""
    store = Mem0Store(client=_make_client())
    health = await store.health()
    assert health["status"] == "ok"
    assert health["backend"] == "mem0"


async def test_health_error_when_client_raises() -> None:
    """A raising probe returns ``{"status": "error", ...}`` without leaking."""
    client = _make_client()
    client.get_all.side_effect = RuntimeError("backend down")
    store = Mem0Store(client=client)
    health = await store.health()
    assert health["status"] == "error"
    assert health["backend"] == "mem0"
    assert "backend down" in health["error"]
