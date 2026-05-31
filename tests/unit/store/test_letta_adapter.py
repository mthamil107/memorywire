"""Unit tests for :class:`memwire.store.letta_adapter.LettaStore`.

These tests use :class:`unittest.mock.MagicMock` to stand in for the real
``letta_client.Letta`` client â€” the Letta SDK is never touched. The goal
is to prove the adapter translates memwire requests into the right Letta
calls and maps the mocked responses back into the memwire response models.

Integration tests that exercise the real SDK live under
``tests/integration/store/test_letta_adapter.py`` and are gated by
``LETTA_BASE_URL`` (and optionally ``LETTA_API_KEY`` /
``LETTA_AGENT_ID``).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

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
from memwire.store.letta_adapter import LettaStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(**overrides: Any) -> MagicMock:
    """Return a fresh ``MagicMock`` configured with sensible defaults.

    The mock mimics the Letta SDK's nested-resource shape:
    ``client.agents.passages.{create, search, list, delete}`` and
    ``client.health``. Individual tests override the methods they care
    about via ``overrides`` (keyed on the leaf method name).
    """
    client = MagicMock()
    # Default return shapes mirror the real SDK at letta-client 1.12.0.
    client.agents.passages.create.return_value = [
        {"id": "letta-default-id", "text": "stored fact", "tags": []}
    ]
    client.agents.passages.search.return_value = []
    client.agents.passages.list.return_value = []
    client.agents.passages.delete.return_value = None
    client.health.return_value = {"status": "ok"}
    for key, value in overrides.items():
        attr = getattr(client.agents.passages, key, None)
        if attr is not None and hasattr(attr, "return_value"):
            attr.return_value = value
        else:
            getattr(client, key).return_value = value
    return client


# ---------------------------------------------------------------------------
# Construction / Protocol conformance
# ---------------------------------------------------------------------------


def test_lettastore_is_a_memory_store() -> None:
    """``isinstance`` against the runtime-checkable Protocol must succeed."""
    store = LettaStore(client=_make_client(), agent_id="ag-1")
    assert isinstance(store, MemoryStore)


def test_from_url_returns_instance() -> None:
    """``LettaStore.from_url('letta://default?agent_id=ag-1')`` builds a usable adapter."""
    store = LettaStore.from_url(
        "letta://default?agent_id=ag-1",
        client=_make_client(),
    )
    assert isinstance(store, LettaStore)
    assert store.agent_id == "ag-1"


def test_from_url_with_host_port_and_token() -> None:
    """A host:port plus token query parameter populates the lazy-init kwargs."""
    store = LettaStore.from_url(
        "letta://localhost:8283?token=secret&agent_id=ag-2",
        client=_make_client(),
    )
    # Token/base_url are internal; assert via the agent_id round-trip and a
    # no-raise construction. (Full lazy-init wiring is exercised separately.)
    assert store.agent_id == "ag-2"


def test_from_url_rejects_wrong_scheme() -> None:
    """A non-``letta://`` scheme must raise."""
    with pytest.raises(ValueError, match="letta://"):
        LettaStore.from_url("sqlite-vec://./mem.db")


def test_capabilities_set_matches_spec() -> None:
    """Capability set is exactly ``{semantic, episodic, vector}``."""
    store = LettaStore(client=_make_client(), agent_id="ag-1")
    assert store.capabilities == {
        Capability.SEMANTIC,
        Capability.EPISODIC,
        Capability.VECTOR,
    }


# ---------------------------------------------------------------------------
# remember()
# ---------------------------------------------------------------------------


async def test_remember_calls_passages_create_with_encoded_tags() -> None:
    """``remember`` encodes memwire overlay fields onto Letta's tag list."""
    client = _make_client()
    client.agents.passages.create.return_value = [
        {"id": "p-1", "text": "Alice prefers email", "tags": []}
    ]
    store = LettaStore(client=client, agent_id="ag-A")

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

    client.agents.passages.create.assert_called_once()
    _, kwargs = client.agents.passages.create.call_args
    assert kwargs["agent_id"] == "ag-A"
    assert kwargs["text"] == "Alice prefers email over phone"
    tags = kwargs["tags"]
    assert "amp_type:semantic" in tags
    assert "amp_conf:0.9" in tags
    assert "amp_src:onboarding-form" in tags
    # Caller metadata is encoded under amp_kv:
    assert any(t == "amp_kv:channel=support" for t in tags)

    assert response.id == "p-1"
    assert response.stores == ["letta"]
    assert response.pending_approval is False


async def test_remember_with_approval_required_skips_client() -> None:
    """``approval_required=True`` short-circuits â€” no Letta call, ``pending_approval``."""
    client = _make_client()
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.remember(
        RememberRequest(
            agent_id="agent-a",
            user_id="alice",
            type=MemoryType.SEMANTIC,
            content="High-risk fact",
            approval_required=True,
        )
    )

    client.agents.passages.create.assert_not_called()
    assert response.pending_approval is True
    assert response.stores == []


async def test_remember_without_agent_id_raises() -> None:
    """Letta requires an agent_id; the adapter raises a clear error if absent."""
    client = _make_client()
    store = LettaStore(client=client)  # no agent_id
    with pytest.raises(ValueError, match="agent_id"):
        await store.remember(
            RememberRequest(
                agent_id="agent-a",
                type=MemoryType.SEMANTIC,
                content="hi",
            )
        )


# ---------------------------------------------------------------------------
# recall()
# ---------------------------------------------------------------------------


async def test_recall_calls_passages_search_and_maps_results() -> None:
    """``recall`` maps Letta's search rows into :class:`RecallHit`."""
    client = _make_client()
    client.agents.passages.search.return_value = [
        {
            "passage": {
                "id": "p-1",
                "text": "Alice prefers email",
                "tags": ["amp_type:semantic", "amp_conf:0.9"],
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
            "score": 0.85,
            "metadata": {},
        }
    ]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.recall(
        RecallRequest(
            agent_id="agent-a",
            user_id="alice",
            query="anything",
            k=3,
        )
    )

    client.agents.passages.search.assert_called_once()
    _, kwargs = client.agents.passages.search.call_args
    assert kwargs["agent_id"] == "ag-A"
    assert kwargs["top_k"] == 3
    assert kwargs["query"] == "anything"

    assert len(response.results) == 1
    hit = response.results[0]
    assert hit.id == "p-1"
    assert hit.type is MemoryType.SEMANTIC
    assert hit.content == "Alice prefers email"
    assert hit.score == pytest.approx(0.85)
    assert hit.source_store == "letta"
    assert response.stores_queried == ["letta"]


async def test_recall_filters_by_type() -> None:
    """``types=[SEMANTIC]`` filters out non-semantic Letta rows."""
    client = _make_client()
    client.agents.passages.search.return_value = [
        {
            "passage": {
                "id": "p-1",
                "text": "fact",
                "tags": ["amp_type:semantic"],
            },
            "score": 0.9,
        },
        {
            "passage": {
                "id": "p-2",
                "text": "event",
                "tags": ["amp_type:episodic"],
            },
            "score": 0.8,
        },
    ]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.recall(
        RecallRequest(
            agent_id="agent-a",
            query="anything",
            types=[MemoryType.SEMANTIC],
        )
    )
    ids = [hit.id for hit in response.results]
    assert ids == ["p-1"]


async def test_recall_defaults_missing_amp_type_to_semantic() -> None:
    """Rows without an ``amp_type`` tag default to ``semantic``."""
    client = _make_client()
    client.agents.passages.search.return_value = [
        {
            "passage": {"id": "p-x", "text": "untagged", "tags": []},
            "score": 0.1,
        }
    ]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.recall(RecallRequest(agent_id="agent-a", query="q"))
    assert response.results[0].type is MemoryType.SEMANTIC


async def test_recall_uses_uniform_score_when_missing() -> None:
    """When the search result omits ``score``, the adapter falls back to 0.5."""
    client = _make_client()
    client.agents.passages.search.return_value = [
        {
            "passage": {"id": "p-1", "text": "no score", "tags": ["amp_type:semantic"]},
        }
    ]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.recall(RecallRequest(agent_id="agent-a", query="q"))
    assert response.results[0].score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# forget()
# ---------------------------------------------------------------------------


async def test_forget_by_ids_calls_delete_for_each() -> None:
    """``forget(ids=[...])`` issues one ``delete`` per id."""
    client = _make_client()
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.forget(
        ForgetRequest(
            agent_id="agent-a",
            ids=["p-1", "p-2"],
        )
    )
    assert client.agents.passages.delete.call_count == 2
    called_ids = {call.kwargs["memory_id"] for call in client.agents.passages.delete.call_args_list}
    assert called_ids == {"p-1", "p-2"}
    # And each call was scoped to the right agent.
    for call in client.agents.passages.delete.call_args_list:
        assert call.kwargs["agent_id"] == "ag-A"
    assert response.forgotten_ids == ["p-1", "p-2"]
    assert response.stores[0].store == "letta"
    assert response.stores[0].count == 2


async def test_forget_without_ids_or_filter_raises() -> None:
    """No-scope mass-delete protection (spec Â§3.3): must raise ``ValueError``."""
    store = LettaStore(client=_make_client(), agent_id="ag-A")
    with pytest.raises(ValueError, match=r"ids.*filter"):
        await store.forget(ForgetRequest(agent_id="agent-a"))


async def test_forget_by_filter_lists_then_deletes_matches() -> None:
    """A filter-only forget resolves ids via ``list`` then deletes matches."""
    client = _make_client()
    client.agents.passages.list.return_value = [
        {"id": "p-1", "text": "fact", "tags": ["amp_type:episodic"]},
        {"id": "p-2", "text": "other", "tags": ["amp_type:semantic"]},
    ]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.forget(
        ForgetRequest(
            agent_id="agent-a",
            filter={"type": "episodic"},
        )
    )
    client.agents.passages.list.assert_called_once()
    delete_ids = {call.kwargs["memory_id"] for call in client.agents.passages.delete.call_args_list}
    assert delete_ids == {"p-1"}
    assert response.forgotten_ids == ["p-1"]


async def test_forget_continues_on_per_id_delete_error() -> None:
    """A delete that raises mid-batch is swallowed; the rest proceed."""
    client = _make_client()
    client.agents.passages.delete.side_effect = [ValueError("not found"), None]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.forget(ForgetRequest(agent_id="agent-a", ids=["missing", "real"]))
    assert response.forgotten_ids == ["real"]


# ---------------------------------------------------------------------------
# merge()
# ---------------------------------------------------------------------------


async def test_merge_keep_canonical_deletes_only_duplicates() -> None:
    """``keep_canonical`` preserves the canonical row and drops duplicates."""
    client = _make_client()
    # The merge path lists once to resolve canonical + duplicates.
    client.agents.passages.list.return_value = [
        {"id": "canon", "text": "Alice Smith", "tags": ["amp_type:semantic"]},
        {"id": "d1", "text": "alice (dup1)", "tags": ["amp_type:semantic"]},
        {"id": "d2", "text": "alice (dup2)", "tags": ["amp_type:semantic"]},
    ]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon",
            duplicates=["d1", "d2"],
            strategy=MergeStrategy.KEEP_CANONICAL,
        )
    )
    # No new canonical written under keep_canonical.
    client.agents.passages.create.assert_not_called()
    delete_ids = {call.kwargs["memory_id"] for call in client.agents.passages.delete.call_args_list}
    assert delete_ids == {"d1", "d2"}
    assert response.canonical == "canon"
    assert response.merged_count == 2
    assert response.strategy_used is MergeStrategy.KEEP_CANONICAL


async def test_merge_content_writes_new_canonical_with_joined_content() -> None:
    """``merge_content`` issues a new ``create`` with concatenated content."""
    client = _make_client()
    client.agents.passages.list.return_value = [
        {
            "id": "canon",
            "text": "Alice Smith",
            "tags": ["amp_type:semantic", "amp_conf:0.7"],
        },
        {
            "id": "d1",
            "text": "Alice S.",
            "tags": ["amp_type:semantic", "amp_conf:0.4"],
        },
    ]
    client.agents.passages.create.return_value = [{"id": "new-canon", "text": "merged", "tags": []}]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon",
            duplicates=["d1"],
            strategy=MergeStrategy.MERGE_CONTENT,
        )
    )
    client.agents.passages.create.assert_called_once()
    _, kwargs = client.agents.passages.create.call_args
    assert "Alice Smith" in kwargs["text"]
    assert "Alice S." in kwargs["text"]
    assert " | " in kwargs["text"]
    # max(confidence) wins per spec.
    assert "amp_conf:0.7" in kwargs["tags"]
    assert response.canonical == "new-canon"
    assert response.merged_count == 1


# ---------------------------------------------------------------------------
# expire()
# ---------------------------------------------------------------------------


async def test_expire_older_than_days_forget_deletes_matches() -> None:
    """``older_than_days=30`` + ``action=forget`` removes only old rows."""
    now = datetime.now(UTC)
    old_dt = datetime.fromtimestamp(time.time() - (60 * 86_400), tz=UTC)
    new_dt = datetime.fromtimestamp(time.time() - (1 * 86_400), tz=UTC)
    # Sanity-check the test fixture so a wall-clock skew doesn't break us.
    assert old_dt < now and new_dt < now

    client = _make_client()
    client.agents.passages.list.return_value = [
        {
            "id": "old",
            "text": "stale",
            "tags": ["amp_type:semantic"],
            "created_at": old_dt,
        },
        {
            "id": "new",
            "text": "fresh",
            "tags": ["amp_type:semantic"],
            "created_at": new_dt,
        },
    ]
    store = LettaStore(client=client, agent_id="ag-A")

    response = await store.expire(
        ExpireRequest(
            agent_id="agent-a",
            policy=ExpirePolicy(older_than_days=30),
            action=ExpireAction.FORGET,
        )
    )
    delete_ids = {call.kwargs["memory_id"] for call in client.agents.passages.delete.call_args_list}
    assert delete_ids == {"old"}
    assert response.matched_count == 1
    assert response.action_taken is ExpireAction.FORGET


async def test_expire_no_recall_in_days_unsupported() -> None:
    """``no_recall_in_days`` MUST raise â€” Letta lacks last-recalled-at tracking."""
    store = LettaStore(client=_make_client(), agent_id="ag-A")
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


async def test_health_ok_when_client_responds() -> None:
    """A successful probe returns the canonical ok shape."""
    store = LettaStore(client=_make_client(), agent_id="ag-A")
    health = await store.health()
    assert health["status"] == "ok"
    assert health["backend"] == "letta"


async def test_health_error_when_client_raises() -> None:
    """A raising probe returns ``{"status": "error", ...}`` without leaking."""
    client = _make_client()
    client.health.side_effect = RuntimeError("backend down")
    store = LettaStore(client=client, agent_id="ag-A")
    health = await store.health()
    assert health["status"] == "error"
    assert health["backend"] == "letta"
    assert "backend down" in health["error"]
