"""Unit tests for :class:`amp.store.sqlite_vec.SqliteVecStore`.

These tests use a deterministic fake embedder so they do not pull
``sentence-transformers`` at unit-test time. The integration test in
``tests/integration/store/test_sqlite_vec.py`` exercises the real model.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from amp.models import (
    ExpirePolicy,
    ExpireRequest,
    ForgetRequest,
    MemoryType,
    MergeRequest,
    MergeStrategy,
    RecallRequest,
    RememberRequest,
)
from amp.store import Capability, MemoryStore
from amp.store.sqlite_vec import DEFAULT_EMBEDDING_DIM, SqliteVecStore

# ---------------------------------------------------------------------------
# Fake embedder — deterministic, sha256-derived, 384-dim.
# ---------------------------------------------------------------------------


def fake_embedder(text: str) -> list[float]:
    """Deterministic 384-d embedding derived from sha256 of the input.

    Same text always returns the same vector; semantically similar inputs
    do not get similar vectors (that is the integration test's job). For
    unit tests we only need stability, not semantics.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (digest * 12)[:DEFAULT_EMBEDDING_DIM]
    return [byte / 255.0 for byte in raw]


def keyword_embedder_factory(corpus: list[str]) -> Any:
    """Build an embedder where each input maps to a distinct one-hot vector.

    Used in tests where we want the FTS half of the fused score to dominate
    so we can assert specific ordering deterministically.
    """

    def _embed(text: str) -> list[float]:
        vec = [0.0] * DEFAULT_EMBEDDING_DIM
        # Mix in a deterministic hash so unknown queries still get a vector,
        # but indexed corpus items get a sparse one-hot like signature.
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        for i, byte in enumerate(digest):
            vec[i] = byte / 255.0
        if text in corpus:
            slot = corpus.index(text) * 7 % DEFAULT_EMBEDDING_DIM
            vec[slot] += 1.0
        return vec

    return _embed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> Iterator[SqliteVecStore]:
    s = SqliteVecStore(":memory:", embedder=fake_embedder)
    try:
        yield s
    finally:
        s.close()


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_is_a_memory_store(store: SqliteVecStore) -> None:
    """The adapter must structurally satisfy the Protocol."""
    assert isinstance(store, MemoryStore)


def test_capabilities_set(store: SqliteVecStore) -> None:
    assert store.capabilities == {
        Capability.SEMANTIC,
        Capability.EPISODIC,
        Capability.PROCEDURAL,
        Capability.EMOTIONAL,
        Capability.FTS,
        Capability.VECTOR,
        Capability.RECALL_TRACKING,
    }


async def test_remember_then_recall_round_trip(store: SqliteVecStore) -> None:
    """Round-trip a semantic fact and verify the content + type come back."""
    write = await store.remember(
        RememberRequest(
            agent_id="agent-1",
            type=MemoryType.SEMANTIC,
            content="Alice is allergic to peanuts.",
            user_id="alice@example.com",
            confidence=0.9,
        )
    )
    assert write.pending_approval is False
    assert write.stores == ["sqlite-vec"]
    assert write.id

    read = await store.recall(RecallRequest(agent_id="agent-1", query="peanuts", k=5))
    assert len(read.results) == 1
    hit = read.results[0]
    assert hit.id == write.id
    assert hit.type is MemoryType.SEMANTIC
    assert "peanut" in str(hit.content).lower()
    assert hit.source_store == "sqlite-vec"
    assert hit.score > 0


async def test_recall_top_k_returns_requested_count(store: SqliteVecStore) -> None:
    """With 5 items and k=3 we get exactly 3 hits, all with non-zero score."""
    facts = [
        "Alice loves peanuts and walnuts.",
        "Bob is allergic to peanuts.",
        "Carol enjoys peanut butter sandwiches.",
        "Dave avoids peanuts at all costs.",
        "Eve sells peanut snacks.",
    ]
    for content in facts:
        await store.remember(
            RememberRequest(agent_id="agent-1", type=MemoryType.SEMANTIC, content=content)
        )
    read = await store.recall(RecallRequest(agent_id="agent-1", query="peanut", k=3))
    assert len(read.results) == 3
    assert all(hit.score > 0 for hit in read.results)


async def test_recall_type_filter_excludes_others(store: SqliteVecStore) -> None:
    await store.remember(
        RememberRequest(
            agent_id="agent-1", type=MemoryType.SEMANTIC, content="Alice likes peanuts."
        )
    )
    await store.remember(
        RememberRequest(
            agent_id="agent-1",
            type=MemoryType.EPISODIC,
            content="On Monday Alice ate peanuts.",
        )
    )
    read = await store.recall(
        RecallRequest(
            agent_id="agent-1",
            query="peanut",
            k=5,
            types=[MemoryType.SEMANTIC],
        )
    )
    assert len(read.results) == 1
    assert read.results[0].type is MemoryType.SEMANTIC


async def test_recall_fresher_than_days_filters_old(store: SqliteVecStore) -> None:
    """Items older than the freshness window must be excluded."""
    await store.remember(
        RememberRequest(agent_id="agent-1", type=MemoryType.SEMANTIC, content="recent peanut fact")
    )
    # Backdate one row by 30 days.
    cutoff = _now_ms() - 30 * 86_400_000
    store._conn.execute(
        "INSERT INTO memories(id, agent_id, type, content, metadata, confidence, "
        "source, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, NULL, 1.0, NULL, ?, ?)",
        ("ancient-1", "agent-1", "semantic", "ancient peanut fact", cutoff, cutoff),
    )
    # Companion vec/fts rows so the row is discoverable.
    rowid = int(
        store._conn.execute("SELECT rowid FROM memories WHERE id = 'ancient-1'").fetchone()["rowid"]
    )
    import sqlite_vec

    store._conn.execute(
        "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
        (rowid, sqlite_vec.serialize_float32(fake_embedder("ancient peanut fact"))),
    )
    store._conn.execute(
        "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
        (rowid, "ancient peanut fact"),
    )

    read = await store.recall(
        RecallRequest(agent_id="agent-1", query="peanut", k=5, fresher_than_days=7)
    )
    contents = {str(hit.content) for hit in read.results}
    assert "recent peanut fact" in contents
    assert "ancient peanut fact" not in contents


async def test_forget_by_ids_removes_record(store: SqliteVecStore) -> None:
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
    assert result.stores[0].store == "sqlite-vec"
    assert result.stores[0].count == 1

    follow = await store.recall(RecallRequest(agent_id="agent-2", query="deploy"))
    assert follow.results == []


async def test_forget_by_filter_removes_matching(store: SqliteVecStore) -> None:
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
    # The Bob row must still recall.
    follow = await store.recall(RecallRequest(agent_id="agent-3", query="flight", k=5))
    assert any("Bob" in str(hit.content) for hit in follow.results)


async def test_forget_requires_ids_or_filter(store: SqliteVecStore) -> None:
    """No-scope mass delete must raise per spec §3.3 Editor's note."""
    with pytest.raises(ValueError, match="ids` or `filter"):
        await store.forget(ForgetRequest(agent_id="agent-x"))


async def test_forget_hard_delete_removes_row(store: SqliteVecStore) -> None:
    write = await store.remember(
        RememberRequest(agent_id="agent-2", type=MemoryType.SEMANTIC, content="ephemeral")
    )
    await store.forget(ForgetRequest(agent_id="agent-2", ids=[write.id], hard_delete=True))
    row = store._conn.execute(
        "SELECT COUNT(*) AS n FROM memories WHERE id = ?", (write.id,)
    ).fetchone()
    assert row["n"] == 0


async def test_merge_keep_canonical_collapses_duplicates(store: SqliteVecStore) -> None:
    canonical = await store.remember(
        RememberRequest(agent_id="agent-4", type=MemoryType.SEMANTIC, content="Alice (canon)")
    )
    dup_a = await store.remember(
        RememberRequest(agent_id="agent-4", type=MemoryType.SEMANTIC, content="alice (dup A)")
    )
    dup_b = await store.remember(
        RememberRequest(agent_id="agent-4", type=MemoryType.SEMANTIC, content="alice (dup B)")
    )
    result = await store.merge(
        MergeRequest(
            agent_id="agent-4",
            canonical=canonical.id,
            duplicates=[dup_a.id, dup_b.id],
            strategy=MergeStrategy.KEEP_CANONICAL,
        )
    )
    assert result.merged_count == 2
    assert result.strategy_used is MergeStrategy.KEEP_CANONICAL
    # Canonical row must still be visible.
    surviving = store._conn.execute(
        "SELECT id FROM memories WHERE deleted_at IS NULL AND agent_id = 'agent-4'"
    ).fetchall()
    surviving_ids = {row["id"] for row in surviving}
    assert canonical.id in surviving_ids
    assert dup_a.id not in surviving_ids
    assert dup_b.id not in surviving_ids


async def test_merge_content_concatenates(store: SqliteVecStore) -> None:
    """``merge_content`` joins content with ``" | "`` and unions metadata."""
    a = await store.remember(
        RememberRequest(
            agent_id="agent-5",
            type=MemoryType.SEMANTIC,
            content="left",
            metadata={"a": 1},
            confidence=0.6,
        )
    )
    b = await store.remember(
        RememberRequest(
            agent_id="agent-5",
            type=MemoryType.SEMANTIC,
            content="right",
            metadata={"b": 2},
            confidence=0.9,
        )
    )
    result = await store.merge(
        MergeRequest(
            agent_id="agent-5",
            canonical=a.id,
            duplicates=[b.id],
            strategy=MergeStrategy.MERGE_CONTENT,
        )
    )
    assert result.merged_count == 1

    survivor = store._conn.execute(
        "SELECT content, metadata, confidence FROM memories WHERE id = ?", (a.id,)
    ).fetchone()
    assert "left" in survivor["content"] and "right" in survivor["content"]
    assert " | " in survivor["content"]
    merged_metadata = json.loads(survivor["metadata"])
    assert merged_metadata == {"a": 1, "b": 2}
    assert survivor["confidence"] == pytest.approx(0.9)


async def test_expire_older_than_days_soft_deletes(store: SqliteVecStore) -> None:
    """Backdate a row and verify expire(older_than_days=...) soft-deletes it."""
    await store.remember(
        RememberRequest(agent_id="agent-6", type=MemoryType.EPISODIC, content="fresh")
    )
    # Insert a backdated row directly.
    cutoff = _now_ms() - 100 * 86_400_000
    store._conn.execute(
        "INSERT INTO memories(id, agent_id, type, content, metadata, confidence, "
        "source, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, NULL, 1.0, NULL, ?, ?)",
        ("old-1", "agent-6", "episodic", "old content", cutoff, cutoff),
    )

    result = await store.expire(
        ExpireRequest(
            agent_id="agent-6",
            policy=ExpirePolicy(older_than_days=90, type=MemoryType.EPISODIC),
        )
    )
    assert result.matched_count == 1
    row = store._conn.execute("SELECT deleted_at FROM memories WHERE id = 'old-1'").fetchone()
    assert row["deleted_at"] is not None


async def test_expire_no_recall_in_days(store: SqliteVecStore) -> None:
    """An un-recalled, backdated row is matched by ``no_recall_in_days``."""
    write = await store.remember(
        RememberRequest(
            agent_id="agent-7",
            type=MemoryType.SEMANTIC,
            content="rarely recalled fact",
        )
    )
    # Recall once to set last_recalled_at, then backdate it well past the window.
    await store.recall(RecallRequest(agent_id="agent-7", query="rarely", k=5))
    backdated = _now_ms() - 200 * 86_400_000
    store._conn.execute(
        "UPDATE memories SET last_recalled_at = ?, created_at = ? WHERE id = ?",
        (backdated, backdated, write.id),
    )

    result = await store.expire(
        ExpireRequest(agent_id="agent-7", policy=ExpirePolicy(no_recall_in_days=180))
    )
    assert result.matched_count == 1


async def test_expire_demote_scales_confidence(store: SqliteVecStore) -> None:
    write = await store.remember(
        RememberRequest(
            agent_id="agent-8",
            type=MemoryType.SEMANTIC,
            content="low signal",
            confidence=0.4,
        )
    )
    from amp.models import ExpireAction

    await store.expire(
        ExpireRequest(
            agent_id="agent-8",
            policy=ExpirePolicy(confidence_below=0.5),
            action=ExpireAction.DEMOTE,
        )
    )
    row = store._conn.execute(
        "SELECT confidence, deleted_at FROM memories WHERE id = ?", (write.id,)
    ).fetchone()
    assert row["confidence"] == pytest.approx(0.4 * 0.25)
    assert row["deleted_at"] is None


async def test_expire_archive_sets_metadata_and_soft_deletes(store: SqliteVecStore) -> None:
    from amp.models import ExpireAction

    write = await store.remember(
        RememberRequest(
            agent_id="agent-9",
            type=MemoryType.SEMANTIC,
            content="archive me",
            metadata={"k": "v"},
        )
    )
    # Backdate so the policy matches.
    cutoff = _now_ms() - 365 * 86_400_000
    store._conn.execute("UPDATE memories SET created_at = ? WHERE id = ?", (cutoff, write.id))
    await store.expire(
        ExpireRequest(
            agent_id="agent-9",
            policy=ExpirePolicy(older_than_days=180),
            action=ExpireAction.ARCHIVE,
        )
    )
    row = store._conn.execute(
        "SELECT metadata, deleted_at FROM memories WHERE id = ?", (write.id,)
    ).fetchone()
    metadata = json.loads(row["metadata"])
    assert metadata.get("archived") is True
    assert metadata.get("k") == "v"
    assert row["deleted_at"] is not None


async def test_expire_rejects_missing_policy(store: SqliteVecStore) -> None:
    """``expire(policy=None)`` would mass-delete the agent's rows — must raise.

    Regression: before this guard, the WHERE clause collapsed to
    ``agent_id = ? AND deleted_at IS NULL`` and (with the default
    ``action=FORGET``) soft-deleted every live row for the agent.
    """
    await store.remember(
        RememberRequest(agent_id="agent-x", type=MemoryType.SEMANTIC, content="keep me")
    )
    with pytest.raises(ValueError, match="expire requires a non-empty policy"):
        await store.expire(ExpireRequest(agent_id="agent-x"))
    # No row was soft-deleted.
    row = store._conn.execute(
        "SELECT deleted_at FROM memories WHERE agent_id = ?", ("agent-x",)
    ).fetchone()
    assert row["deleted_at"] is None


async def test_expire_rejects_empty_policy_object(store: SqliteVecStore) -> None:
    """``expire`` with an :class:`ExpirePolicy` of all-None fields must raise."""
    await store.remember(
        RememberRequest(agent_id="agent-y", type=MemoryType.SEMANTIC, content="keep me too")
    )
    with pytest.raises(ValueError, match="expire requires a non-empty policy"):
        await store.expire(ExpireRequest(agent_id="agent-y", policy=ExpirePolicy()))
    row = store._conn.execute(
        "SELECT deleted_at FROM memories WHERE agent_id = ?", ("agent-y",)
    ).fetchone()
    assert row["deleted_at"] is None


async def test_health_returns_expected_shape(store: SqliteVecStore) -> None:
    await store.remember(
        RememberRequest(agent_id="agent-h", type=MemoryType.SEMANTIC, content="hi")
    )
    h = await store.health()
    assert h["status"] == "ok"
    assert h["backend"] == "sqlite-vec"
    assert h["db_path"] == ":memory:"
    assert h["memory_count"] == 1
    assert h["schema_version"] == 1


def test_from_url_parses_memory_form() -> None:
    s = SqliteVecStore.from_url("sqlite-vec://:memory:", embedder=fake_embedder)
    try:
        assert s.db_path == ":memory:"
    finally:
        s.close()


def test_from_url_parses_relative_file(tmp_path: Path) -> None:
    # urllib parses "sqlite-vec://./mem.db" as netloc='.' path='/mem.db'.
    target = tmp_path / "mem.db"
    s = SqliteVecStore.from_url(
        f"sqlite-vec://{target.as_posix()}",
        embedder=fake_embedder,
    )
    try:
        assert Path(s.db_path).name == "mem.db"
    finally:
        s.close()


async def test_approval_required_pends_and_hides_from_recall(store: SqliteVecStore) -> None:
    write = await store.remember(
        RememberRequest(
            agent_id="agent-p",
            type=MemoryType.SEMANTIC,
            content="secret fact pending approval",
            approval_required=True,
        )
    )
    assert write.pending_approval is True
    assert write.stores == []
    # The pending row exists on disk...
    row = store._conn.execute(
        "SELECT id, deleted_at FROM memories WHERE id = ?", (write.id,)
    ).fetchone()
    assert row is not None
    assert row["deleted_at"] is not None  # sentinel marker

    # ... but is not visible to recall.
    read = await store.recall(RecallRequest(agent_id="agent-p", query="secret", k=5))
    assert read.results == []


async def test_procedural_memory_round_trips(store: SqliteVecStore) -> None:
    """Procedural memory: FSM JSON in ``content``, side-row in ``procedures``."""
    fsm = {
        "name": "book-flight",
        "initial": "searching",
        "states": ["searching", "comparing", "selecting", "paying", "confirmed"],
        "transitions": [
            {"trigger": "found_options", "source": "searching", "dest": "comparing"},
        ],
        "current": "searching",
    }
    write = await store.remember(
        RememberRequest(
            agent_id="travel-agent",
            type=MemoryType.PROCEDURAL,
            content=json.dumps(fsm),
            metadata={"procedure_name": "book-flight"},
        )
    )
    # Procedures side table populated with the same id.
    proc_row = store._conn.execute(
        "SELECT id, name, current FROM procedures WHERE id = ?", (write.id,)
    ).fetchone()
    assert proc_row is not None
    assert proc_row["name"] == "book-flight"
    assert proc_row["current"] == "searching"

    # Recall surfaces it tagged as procedural.
    read = await store.recall(RecallRequest(agent_id="travel-agent", query="book flight", k=5))
    assert any(hit.id == write.id and hit.type is MemoryType.PROCEDURAL for hit in read.results)


async def test_async_context_manager_closes() -> None:
    async with SqliteVecStore(":memory:", embedder=fake_embedder) as s:
        await s.remember(RememberRequest(agent_id="ctx", type=MemoryType.SEMANTIC, content="hi"))
    # close() is idempotent; calling again should not raise.
    s.close()
