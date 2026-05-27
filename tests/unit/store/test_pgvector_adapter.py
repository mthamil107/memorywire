"""Unit tests for :class:`amp.store.pgvector_adapter.PgVectorStore`.

These tests use :class:`unittest.mock.AsyncMock` to stand in for the
``asyncpg.Pool`` / connection that the adapter would otherwise reach. The
real Postgres + ``pgvector`` server is never touched. The integration test
under ``tests/integration/store/test_pgvector_adapter.py`` exercises the
SDK end-to-end, gated by the ``DATABASE_URL`` env var.

Mock model
----------
We build a ``MagicMock`` pool whose ``acquire()`` returns an async context
manager that yields a connection ``MagicMock``. The connection mock has
``execute``, ``fetch``, and ``fetchrow`` configured as :class:`AsyncMock`
methods. Tests assert against the SQL/parameter tuples passed in.
"""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amp.models import (
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
from amp.store import Capability, MemoryStore
from amp.store.pgvector_adapter import (
    BACKEND_NAME,
    DEFAULT_EMBEDDING_DIM,
    PENDING_APPROVAL_DELETED_AT,
    PgVectorStore,
)

# ---------------------------------------------------------------------------
# Helpers
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


class _AcquireCtx:
    """Async context manager mimicking ``pool.acquire()`` from asyncpg.

    Tests build the connection mock once, then have the pool's ``acquire``
    return one of these so ``async with pool.acquire() as conn:`` works.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *_: Any) -> None:
        return None


def _make_pool(conn: Any | None = None) -> tuple[MagicMock, MagicMock]:
    """Return ``(pool_mock, connection_mock)`` wired together.

    The connection's ``execute`` / ``fetch`` / ``fetchrow`` are AsyncMocks
    with sensible defaults; tests override the ``return_value`` they care
    about.
    """
    if conn is None:
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    pool.close = AsyncMock(return_value=None)
    return pool, conn


def _make_store(**overrides: Any) -> tuple[PgVectorStore, MagicMock]:
    """Build a :class:`PgVectorStore` with the fake embedder + mocked pool."""
    pool, conn = _make_pool()
    store = PgVectorStore(
        pool=pool,
        embedder=fake_embedder,
        **overrides,
    )
    return store, conn


# ---------------------------------------------------------------------------
# Construction / Protocol conformance
# ---------------------------------------------------------------------------


def test_pgvectorstore_is_a_memory_store() -> None:
    """``isinstance`` against the runtime-checkable Protocol must succeed."""
    pool, _ = _make_pool()
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    assert isinstance(store, MemoryStore)


def test_constructor_requires_dsn_or_pool() -> None:
    """Neither ``dsn`` nor ``pool`` → :class:`ValueError`."""
    with pytest.raises(ValueError, match="dsn"):
        PgVectorStore()


def test_constructor_rejects_unsafe_schema_identifier() -> None:
    """A schema name with SQL metacharacters is refused outright."""
    pool, _ = _make_pool()
    with pytest.raises(ValueError, match="schema"):
        PgVectorStore(pool=pool, schema="amp; DROP TABLE memories--")


def test_capabilities_set_matches_spec() -> None:
    """Postgres declares rich capabilities; FTS is deliberately absent at v0."""
    store, _ = _make_store()
    assert store.capabilities == {
        Capability.SEMANTIC,
        Capability.EPISODIC,
        Capability.PROCEDURAL,
        Capability.EMOTIONAL,
        Capability.VECTOR,
        Capability.RECALL_TRACKING,
        Capability.GOVERNANCE,
    }
    # No FTS at v0.
    assert Capability.FTS not in store.capabilities


# ---------------------------------------------------------------------------
# from_url
# ---------------------------------------------------------------------------


def test_from_url_pgvector_scheme_parses_dsn() -> None:
    """``pgvector://user:pw@host:5432/db`` parses into a postgres DSN."""
    pool, _ = _make_pool()
    store = PgVectorStore.from_url(
        "pgvector://amp:pw@localhost:5432/amp",
        pool=pool,
        embedder=fake_embedder,
    )
    assert store._dsn == "postgres://amp:pw@localhost:5432/amp"


def test_from_url_pgvector_postgres_composite_scheme() -> None:
    """``pgvector+postgres://...`` is accepted and the composite is stripped."""
    pool, _ = _make_pool()
    store = PgVectorStore.from_url(
        "pgvector+postgres://amp:pw@host:5432/db",
        pool=pool,
        embedder=fake_embedder,
    )
    assert store._dsn == "postgres://amp:pw@host:5432/db"


def test_from_url_default_reads_database_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``pgvector://default`` pulls the DSN from ``DATABASE_URL``."""
    monkeypatch.setenv("DATABASE_URL", "postgres://envuser@envhost/envdb")
    pool, _ = _make_pool()
    store = PgVectorStore.from_url("pgvector://default", pool=pool, embedder=fake_embedder)
    assert store._dsn == "postgres://envuser@envhost/envdb"


def test_from_url_default_without_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``pgvector://default`` with no ``DATABASE_URL`` → :class:`ValueError`."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        PgVectorStore.from_url("pgvector://default")


def test_from_url_rejects_wrong_scheme() -> None:
    """A non-``pgvector://`` scheme must raise."""
    with pytest.raises(ValueError, match="pgvector"):
        PgVectorStore.from_url("sqlite-vec://./mem.db")


# ---------------------------------------------------------------------------
# _ensure_schema
# ---------------------------------------------------------------------------


async def test_ensure_schema_runs_create_statements_once() -> None:
    """The bootstrap fires on the first call, then becomes a no-op."""
    store, conn = _make_store()
    await store._ensure_schema()
    # Each DDL statement is one ``conn.execute`` call.
    first_calls = conn.execute.call_count
    assert first_calls >= 5
    # Capture the SQL that was issued — must include extension/schema/table.
    sqls = "\n".join(str(call.args[0]) for call in conn.execute.call_args_list)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sqls
    assert "CREATE SCHEMA IF NOT EXISTS amp" in sqls
    assert "CREATE TABLE IF NOT EXISTS amp.memories" in sqls
    assert "vector(384)" in sqls
    assert "ivfflat" in sqls

    # Idempotency: second call is a no-op.
    await store._ensure_schema()
    assert conn.execute.call_count == first_calls


async def test_ensure_schema_disabled_skips_ddl() -> None:
    """``ensure_schema=False`` suppresses the bootstrap entirely."""
    pool, conn = _make_pool()
    store = PgVectorStore(pool=pool, embedder=fake_embedder, ensure_schema=False)
    await store._ensure_schema()
    assert conn.execute.call_count == 0


# ---------------------------------------------------------------------------
# remember
# ---------------------------------------------------------------------------


async def test_remember_issues_parameterised_insert() -> None:
    """``remember`` runs the schema bootstrap then INSERTs a parameterised row."""
    store, conn = _make_store()
    response = await store.remember(
        RememberRequest(
            agent_id="agent-a",
            user_id="alice@example.com",
            type=MemoryType.SEMANTIC,
            content="Alice prefers email.",
            confidence=0.9,
            source="onboarding",
            metadata={"channel": "support"},
        )
    )

    # First N execute calls are DDL; find the INSERT into memories.
    insert_call = next(
        c for c in conn.execute.call_args_list if "INSERT INTO amp.memories" in str(c.args[0])
    )
    sql = insert_call.args[0]
    params = insert_call.args[1:]
    # 13 positional params (id, agent_id, user_id, type, content, metadata,
    # confidence, source, embedding_literal, created_at, updated_at,
    # expires_at, deleted_at).
    assert len(params) == 13
    assert "$1" in sql and "$13" in sql
    # type / agent_id / user_id come through verbatim.
    assert params[1] == "agent-a"
    assert params[2] == "alice@example.com"
    assert params[3] == "semantic"
    assert params[4] == "Alice prefers email."
    # metadata is JSON-encoded.
    assert '"channel"' in params[5] and '"support"' in params[5]
    # confidence preserved.
    assert params[6] == pytest.approx(0.9)
    # source preserved.
    assert params[7] == "onboarding"
    # embedding is a vector literal: starts with "[" and contains 383 commas.
    assert params[8].startswith("[") and params[8].endswith("]")
    assert params[8].count(",") == DEFAULT_EMBEDDING_DIM - 1
    # deleted_at is None on a normal write.
    assert params[12] is None

    # Response shape.
    assert response.stores == [BACKEND_NAME]
    assert response.pending_approval is False
    assert response.id


async def test_remember_with_approval_required_writes_pending_sentinel() -> None:
    """``approval_required=True`` writes the PENDING sentinel and surfaces it."""
    store, conn = _make_store()
    response = await store.remember(
        RememberRequest(
            agent_id="agent-a",
            type=MemoryType.SEMANTIC,
            content="High-risk fact",
            approval_required=True,
        )
    )
    insert_call = next(
        c for c in conn.execute.call_args_list if "INSERT INTO amp.memories" in str(c.args[0])
    )
    params = insert_call.args[1:]
    assert params[12] == PENDING_APPROVAL_DELETED_AT  # deleted_at slot
    assert response.pending_approval is True
    assert response.stores == []


async def test_remember_procedural_writes_procedures_row() -> None:
    """A procedural memory also gets a row in ``procedures``."""
    store, conn = _make_store()
    fsm_json = (
        '{"name":"checkout","initial":"start","states":["start","done"],'
        '"transitions":[],"current":"start"}'
    )
    await store.remember(
        RememberRequest(
            agent_id="agent-a",
            type=MemoryType.PROCEDURAL,
            content=fsm_json,
        )
    )
    proc_call = next(
        c for c in conn.execute.call_args_list if "INSERT INTO amp.procedures" in str(c.args[0])
    )
    params = proc_call.args[1:]
    # name pulled from FSM, current too.
    assert params[2] == "checkout"
    assert params[4] == "start"


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


async def test_recall_returns_hits_from_mocked_rowset() -> None:
    """A mocked ``fetch`` rowset is mapped into :class:`RecallHit`."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": "m1",
                "agent_id": "agent-a",
                "user_id": "alice",
                "type": "semantic",
                "content": "Alice likes peanuts.",
                "metadata": '{"channel":"support"}',
                "confidence": 0.9,
                "source": "onboarding",
                "created_at": 1_700_000_000_000,
                "updated_at": 1_700_000_000_000,
                "expires_at": None,
                "distance": 0.1,
            }
        ]
    )
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    response = await store.recall(RecallRequest(agent_id="agent-a", query="peanut", k=5))

    assert len(response.results) == 1
    hit = response.results[0]
    assert hit.id == "m1"
    assert hit.type is MemoryType.SEMANTIC
    assert hit.content == "Alice likes peanuts."
    assert hit.source_store == BACKEND_NAME
    # score is the inverse of distance, in (0, 1].
    assert 0.0 < hit.score <= 1.0
    # metadata round-tripped from the JSON string asyncpg may return.
    assert hit.metadata == {"channel": "support"}
    assert response.stores_queried == [BACKEND_NAME]
    assert response.latency_ms >= 0


async def test_recall_types_filter_passed_as_text_array() -> None:
    """``types=[SEMANTIC]`` adds a ``type = ANY($n::text[])`` clause."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(return_value=[])
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    await store.recall(
        RecallRequest(
            agent_id="agent-a",
            query="anything",
            types=[MemoryType.SEMANTIC, MemoryType.EPISODIC],
        )
    )
    select_call = next(
        c for c in conn.fetch.call_args_list if "FROM amp.memories" in str(c.args[0])
    )
    sql = select_call.args[0]
    params = select_call.args[1:]
    assert "type = ANY(" in sql
    # The list-of-strings array should be one of the parameters.
    assert any(p == ["semantic", "episodic"] for p in params)


async def test_recall_updates_last_recalled_at_for_hits() -> None:
    """When a hit comes back, the adapter UPDATEs its ``last_recalled_at``."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": "m1",
                "agent_id": "agent-a",
                "user_id": None,
                "type": "semantic",
                "content": "x",
                "metadata": None,
                "confidence": 1.0,
                "source": None,
                "created_at": 1,
                "updated_at": 1,
                "expires_at": None,
                "distance": 0.5,
            }
        ]
    )
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    await store.recall(RecallRequest(agent_id="agent-a", query="q"))

    update_call = next(
        c for c in conn.execute.call_args_list if "SET last_recalled_at" in str(c.args[0])
    )
    assert "last_recalled_at = $1" in update_call.args[0]
    assert update_call.args[2] == ["m1"]


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------


async def test_forget_by_ids_soft_deletes() -> None:
    """``forget(ids=[...])`` resolves them and runs the soft-delete UPDATE."""
    pool, conn = _make_pool()
    # First fetch (id lookup) returns the requested ids; subsequent fetches
    # default to [] from the helper.
    conn.fetch = AsyncMock(side_effect=[[{"id": "m1"}, {"id": "m2"}]])
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    response = await store.forget(ForgetRequest(agent_id="agent-a", ids=["m1", "m2"]))

    # The soft-delete UPDATE must run with both ids.
    update_call = next(
        c
        for c in conn.execute.call_args_list
        if "SET deleted_at" in str(c.args[0]) and "amp.memories" in str(c.args[0])
    )
    assert "deleted_at = $1" in update_call.args[0]
    assert update_call.args[2] == ["m1", "m2"]
    assert response.forgotten_ids == ["m1", "m2"]
    assert response.hard_delete is False
    assert response.stores[0].store == BACKEND_NAME
    assert response.stores[0].count == 2


async def test_forget_hard_delete_issues_delete() -> None:
    """``hard_delete=True`` runs DELETE rather than UPDATE."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(side_effect=[[{"id": "m1"}]])
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    await store.forget(ForgetRequest(agent_id="agent-a", ids=["m1"], hard_delete=True))
    delete_call = next(
        c for c in conn.execute.call_args_list if "DELETE FROM amp.memories" in str(c.args[0])
    )
    assert "DELETE" in delete_call.args[0]
    assert delete_call.args[1] == ["m1"]


async def test_forget_by_filter_runs_select_then_update() -> None:
    """A filter-only forget resolves ids via SELECT then soft-deletes them."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(side_effect=[[{"id": "m1"}]])
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    response = await store.forget(
        ForgetRequest(
            agent_id="agent-a",
            filter={"user_id": "alice@example.com"},
        )
    )
    # The SELECT had a user_id filter.
    select_call = conn.fetch.call_args_list[0]
    assert "user_id = $" in select_call.args[0]
    assert "alice@example.com" in select_call.args
    assert response.forgotten_ids == ["m1"]


async def test_forget_without_ids_or_filter_raises() -> None:
    """No-scope mass delete must raise per spec §3.3 Editor's note."""
    store, _ = _make_store()
    with pytest.raises(ValueError, match="ids` or `filter"):
        await store.forget(ForgetRequest(agent_id="agent-a"))


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


async def test_merge_keep_canonical_soft_deletes_duplicates() -> None:
    """``keep_canonical`` preserves the canonical and soft-deletes duplicates."""
    pool, conn = _make_pool()
    # _resolve_entity calls fetch twice per entity (id then entity_name); the
    # second call returns [] when the first one matched. canonical resolves
    # by id, both duplicates resolve by id too.
    conn.fetch = AsyncMock(
        side_effect=[
            [
                {
                    "id": "canon",
                    "content": "Alice",
                    "metadata": None,
                    "confidence": 1.0,
                    "created_at": 1,
                }
            ],
            [
                {
                    "id": "d1",
                    "content": "alice",
                    "metadata": None,
                    "confidence": 0.5,
                    "created_at": 2,
                }
            ],
            [
                {
                    "id": "d2",
                    "content": "alice2",
                    "metadata": None,
                    "confidence": 0.5,
                    "created_at": 3,
                }
            ],
        ]
    )
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    response = await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon",
            duplicates=["d1", "d2"],
            strategy=MergeStrategy.KEEP_CANONICAL,
        )
    )
    assert response.merged_count == 2
    assert response.strategy_used is MergeStrategy.KEEP_CANONICAL
    soft_delete_call = next(
        c
        for c in conn.execute.call_args_list
        if "SET deleted_at" in str(c.args[0]) and "id = ANY" in str(c.args[0])
    )
    assert set(soft_delete_call.args[2]) == {"d1", "d2"}


async def test_merge_keep_highest_confidence_picks_winner() -> None:
    """``keep_highest_confidence`` keeps the row with the highest confidence."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(
        side_effect=[
            [{"id": "canon", "content": "x", "metadata": None, "confidence": 0.3, "created_at": 1}],
            [{"id": "d1", "content": "y", "metadata": None, "confidence": 0.9, "created_at": 2}],
        ]
    )
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    response = await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon",
            duplicates=["d1"],
            strategy=MergeStrategy.KEEP_HIGHEST_CONFIDENCE,
        )
    )
    # Only the loser (canon) is soft-deleted.
    soft_delete_call = next(
        c
        for c in conn.execute.call_args_list
        if "SET deleted_at" in str(c.args[0]) and "id = ANY" in str(c.args[0])
    )
    assert soft_delete_call.args[2] == ["canon"]
    assert response.merged_count == 1


async def test_merge_content_writes_concatenated_survivor() -> None:
    """``merge_content`` UPDATEs the survivor row with ``" | "``-joined content."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(
        side_effect=[
            [
                {
                    "id": "canon",
                    "content": "Alice Smith",
                    "metadata": None,
                    "confidence": 0.7,
                    "created_at": 1,
                }
            ],
            [
                {
                    "id": "d1",
                    "content": "Alice S.",
                    "metadata": None,
                    "confidence": 0.4,
                    "created_at": 2,
                }
            ],
        ]
    )
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    await store.merge(
        MergeRequest(
            agent_id="agent-a",
            canonical="canon",
            duplicates=["d1"],
            strategy=MergeStrategy.MERGE_CONTENT,
        )
    )
    update_call = next(c for c in conn.execute.call_args_list if "SET content" in str(c.args[0]))
    # Concatenated content present in the bind args.
    assert any(
        " | " in str(a) and "Alice Smith" in str(a) and "Alice S." in str(a)
        for a in update_call.args[1:]
    )


# ---------------------------------------------------------------------------
# expire
# ---------------------------------------------------------------------------


async def test_expire_empty_policy_raises() -> None:
    """Spec §3.5: empty policy must raise so it can't mass-delete."""
    store, _ = _make_store()
    with pytest.raises(ValueError, match="non-empty policy"):
        await store.expire(ExpireRequest(agent_id="agent-a", policy=ExpirePolicy()))
    with pytest.raises(ValueError, match="non-empty policy"):
        await store.expire(ExpireRequest(agent_id="agent-a"))


async def test_expire_older_than_days_runs_update() -> None:
    """A valid policy fetches candidate rows and runs the action SQL."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(side_effect=[[{"id": "old1", "metadata": None}]])
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    response = await store.expire(
        ExpireRequest(
            agent_id="agent-a",
            policy=ExpirePolicy(older_than_days=30),
            action=ExpireAction.FORGET,
        )
    )
    # First fetch is the SELECT of matching rows.
    select_call = conn.fetch.call_args_list[0]
    assert "created_at <= $" in select_call.args[0]
    # UPDATE soft-deletes the matched ids.
    update_call = next(
        c
        for c in conn.execute.call_args_list
        if "SET deleted_at" in str(c.args[0]) and "id = ANY" in str(c.args[0])
    )
    assert update_call.args[2] == ["old1"]
    assert response.matched_count == 1
    assert response.action_taken is ExpireAction.FORGET


async def test_expire_demote_multiplies_confidence() -> None:
    """``action=demote`` multiplies confidence by 0.25 on matched rows."""
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(side_effect=[[{"id": "x", "metadata": None}]])
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    await store.expire(
        ExpireRequest(
            agent_id="agent-a",
            policy=ExpirePolicy(confidence_below=0.5),
            action=ExpireAction.DEMOTE,
        )
    )
    demote_call = next(
        c for c in conn.execute.call_args_list if "confidence = COALESCE" in str(c.args[0])
    )
    assert "* 0.25" in demote_call.args[0]


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


async def test_health_returns_expected_shape() -> None:
    """``health`` reports backend, pg_version, schema, and memory_count."""
    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"v": "PostgreSQL 16.0"},
            {"n": 42},
        ]
    )
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    h = await store.health()
    assert h["status"] == "ok"
    assert h["backend"] == BACKEND_NAME
    assert h["schema"] == "amp"
    assert h["pg_version"] == "PostgreSQL 16.0"
    assert h["memory_count"] == 42
    assert "schema_version" in h


async def test_health_reports_error_on_failure() -> None:
    """Probe failure surfaces as ``status=error`` rather than raising."""
    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(side_effect=RuntimeError("connection refused"))
    store = PgVectorStore(pool=pool, embedder=fake_embedder)
    h = await store.health()
    assert h["status"] == "error"
    assert "connection refused" in h["error"]
