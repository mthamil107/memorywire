"""Integration test for :class:`amp.store.pgvector_adapter.PgVectorStore`.

This test exercises the **real** Postgres + ``pgvector`` stack end-to-end:

1. Connect to the DSN supplied via the ``DATABASE_URL`` env var.
2. Run schema bootstrap (``CREATE EXTENSION``, ``CREATE SCHEMA``, tables).
3. ``remember`` a semantic fact.
4. ``recall`` and assert the fact comes back.
5. ``forget`` it and assert the soft-delete removes it from recall.

It is doubly gated:

* ``@pytest.mark.integration`` so default ``pytest -m "not integration"``
  runs skip it.
* ``@pytest.mark.skipif(not os.environ.get("DATABASE_URL"))`` so even an
  explicit ``pytest -m integration`` skips when no DSN is configured.

Run with: ``pytest -m integration tests/integration/store/test_pgvector_adapter.py``.

A scratch schema name is used (``amp_itest_<pid>``) so the test does not
collide with any application schema in the same database. The teardown
phase drops the scratch schema at the end of the run.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from amp.models import (
    ForgetRequest,
    MemoryType,
    RecallRequest,
    RememberRequest,
)
from amp.store.pgvector_adapter import DEFAULT_EMBEDDING_DIM, PgVectorStore


def _fake_embedder(text: str) -> list[float]:
    """Deterministic 384-d embedding so the test does not depend on
    sentence-transformers being installed in the integration environment."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (digest * 12)[:DEFAULT_EMBEDDING_DIM]
    return [byte / 255.0 for byte in raw]


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is required for the real Postgres backend",
)
async def test_remember_recall_forget_against_real_postgres() -> None:
    """Round-trip a fact through a real ``PgVectorStore``."""
    scratch_schema = f"amp_itest_{os.getpid()}"
    dsn = os.environ["DATABASE_URL"]

    store = PgVectorStore(
        dsn=dsn,
        schema=scratch_schema,
        embedder=_fake_embedder,
    )
    try:
        # remember.
        write = await store.remember(
            RememberRequest(
                agent_id="amp-itest-agent",
                type=MemoryType.SEMANTIC,
                content="The agent's favourite colour is blue.",
            )
        )
        assert write.stores == ["pgvector"]
        assert write.pending_approval is False
        assert write.id

        # recall (vector distance against the same fake embedder → exact hit).
        read = await store.recall(
            RecallRequest(
                agent_id="amp-itest-agent",
                query="The agent's favourite colour is blue.",
                k=5,
            )
        )
        assert read.stores_queried == ["pgvector"]
        ids = [hit.id for hit in read.results]
        assert write.id in ids

        # forget — soft-delete by id.
        result = await store.forget(ForgetRequest(agent_id="amp-itest-agent", ids=[write.id]))
        assert result.forgotten_ids == [write.id]

        # The deleted row must no longer surface in recall.
        post = await store.recall(
            RecallRequest(
                agent_id="amp-itest-agent",
                query="The agent's favourite colour is blue.",
                k=5,
            )
        )
        assert write.id not in [hit.id for hit in post.results]
    finally:
        # Best-effort teardown of the scratch schema.
        try:
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(f"DROP SCHEMA IF EXISTS {scratch_schema} CASCADE")
        except Exception:
            pass
        await store.close()
