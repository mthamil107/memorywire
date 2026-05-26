"""Shared pytest fixtures for the AMP Governance UI tests.

Tests write into a *real* :class:`amp.store.sqlite_vec.SqliteVecStore` so the
schema matches production. A deterministic fake embedder is injected to keep
``sentence-transformers`` out of the unit-test loop.

Three fixture flavours:

* :func:`seeded_db` — empty store + an ``insert_*`` helper. Tests choose their
  own data. Returns ``(db_path, helper)`` so each test stays explicit.
* :func:`app_for_path` — convenience factory wrapping
  :func:`amp_ui.app.create_app` for the configured db.
* :func:`csrf_client` — convenience factory returning an ``httpx.AsyncClient``
  pre-loaded with the CSRF cookie + ``X-CSRF-Token`` default header so
  existing POST tests don't have to hand-negotiate the double-submit token.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from amp_ui.app import create_app
from amp_ui.middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME

from amp.models import MemoryType, RememberRequest
from amp.store.sqlite_vec import DEFAULT_EMBEDDING_DIM, SqliteVecStore


def _fake_embedder(text: str) -> list[float]:
    """Deterministic 384-dim vector derived from sha256(text)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (digest * 12)[:DEFAULT_EMBEDDING_DIM]
    return [byte / 255.0 for byte in raw]


def _now_ms() -> int:
    return int(time.time() * 1000)


class SeedHelper:
    """Small helper bound to one SqliteVecStore + raw connection.

    The store handles the canonical ``remember`` write path; the raw
    connection is exposed for tests that need to inject rows the protocol
    would not normally produce (custom timestamps, audit-log seeding, etc.).
    """

    def __init__(self, store: SqliteVecStore, conn: sqlite3.Connection, db_path: str) -> None:
        self.store = store
        self.conn = conn
        self.db_path = db_path

    def remember(
        self,
        content: str,
        *,
        agent_id: str = "default",
        type: MemoryType = MemoryType.SEMANTIC,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        confidence: float = 1.0,
        source: str | None = None,
        approval_required: bool = False,
    ) -> str:
        req = RememberRequest(
            agent_id=agent_id,
            user_id=user_id,
            type=type,
            content=content,
            metadata=metadata,
            confidence=confidence,
            source=source,
            approval_required=approval_required,
        )
        # Call the sync write path directly so tests can seed from inside an
        # already-running asyncio event loop (the async API would deadlock).
        resp = self.store._remember_sync(req)
        return resp.id

    def set_last_recalled_at(self, memory_id: str, value: int | None) -> None:
        self.conn.execute(
            "UPDATE memories SET last_recalled_at = ? WHERE id = ?",
            (value, memory_id),
        )

    def set_created_at(self, memory_id: str, value: int) -> None:
        self.conn.execute(
            "UPDATE memories SET created_at = ?, updated_at = ? WHERE id = ?",
            (value, value, memory_id),
        )

    def seed_audit(
        self,
        *,
        operation: str,
        agent_id: str,
        memory_id: str | None,
        approved_by: str | None,
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        ts: int | None = None,
    ) -> int:
        import json

        cursor = self.conn.execute(
            "INSERT INTO audit_log(ts, operation, agent_id, user_id, memory_id, "
            "payload, result, approved_by, approval_at) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)",
            (
                ts if ts is not None else _now_ms(),
                operation,
                agent_id,
                memory_id,
                json.dumps(payload or {}),
                json.dumps(result) if result is not None else None,
                approved_by,
                _now_ms() if approved_by else None,
            ),
        )
        return int(cursor.lastrowid or 0)


@pytest.fixture
def seeded_db(tmp_path: Path) -> Iterator[SeedHelper]:
    """Yield a :class:`SeedHelper` bound to a temp-file SQLite database.

    The temp-file path matters: ``:memory:`` cannot be shared across two
    independent SQLite connections, so the UI (which opens its own conn)
    must point at a real file.
    """
    db_path = tmp_path / "amp.db"
    store = SqliteVecStore(db_path, embedder=_fake_embedder)
    # The UI-owned ``approval_patterns`` table is created by the app factory,
    # but tests that exercise services directly may not have built an app yet.
    from amp_ui import services as _services

    _services.ensure_schema(str(db_path))
    raw = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    try:
        yield SeedHelper(store, raw, str(db_path))
    finally:
        raw.close()
        store.close()


@pytest.fixture
def app_for_path() -> Any:
    """Factory: ``app_for_path(db_path, agent_id='default', **kwargs)`` → Starlette app."""

    def _build(db_path: str, agent_id: str = "default", **kwargs: Any) -> Any:
        return create_app(db_path=db_path, agent_id=agent_id, **kwargs)

    return _build


@pytest.fixture
def csrf_client() -> Any:
    """Factory: ``csrf_client(app)`` → context manager yielding an ``httpx.AsyncClient``.

    The returned client has its cookie jar primed by a single ``GET /``
    against the app (so the ``amp_ui_csrf`` cookie is set) and adds the
    matching ``X-CSRF-Token`` header to every subsequent request. Use
    this in any test that POSTs through the UI after the CSRF
    middleware landed in :mod:`amp_ui.middleware`.
    """

    @asynccontextmanager
    async def _build(app: Any, **client_kwargs: Any) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", **client_kwargs
        ) as client:
            # Prime the cookie jar. The middleware mints the token on any
            # GET that lacks the cookie; '/' is the cheapest such path.
            await client.get("/")
            token = client.cookies.get(CSRF_COOKIE_NAME, "")
            if token:
                client.headers[CSRF_HEADER_NAME] = token
            yield client

    return _build


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
