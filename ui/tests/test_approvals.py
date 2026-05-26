"""Tests for the Pending Approvals screen + approve/reject actions."""

from __future__ import annotations

from typing import Any

import httpx
import pytest


@pytest.mark.anyio
async def test_pending_row_visible_on_home(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    pending_id = seeded_db.remember(
        "Alice prefers black coffee",
        approval_required=True,
        metadata={"entity_name": "alice.coffee"},
    )
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "Alice prefers black coffee" in response.text
        assert pending_id in response.text


@pytest.mark.anyio
async def test_approve_flips_deleted_at_to_null(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    pending_id = seeded_db.remember("Bob likes cats", approval_required=True)
    # Sanity: row is currently pending.
    row = seeded_db.conn.execute(
        "SELECT deleted_at FROM memories WHERE id = ?", (pending_id,)
    ).fetchone()
    assert row["deleted_at"] == -1

    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/approvals/{pending_id}/approve",
            data={"reviewer": "alice", "reason": "looks good"},
        )
        assert response.status_code in {200, 303}

    row = seeded_db.conn.execute(
        "SELECT deleted_at FROM memories WHERE id = ?", (pending_id,)
    ).fetchone()
    assert row["deleted_at"] is None

    audit = seeded_db.conn.execute(
        "SELECT operation, approved_by FROM audit_log WHERE memory_id = ? ORDER BY id DESC LIMIT 1",
        (pending_id,),
    ).fetchone()
    assert audit["operation"] == "remember"
    assert audit["approved_by"] == "alice"


@pytest.mark.anyio
async def test_reject_soft_deletes_the_row(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    pending_id = seeded_db.remember("noise", approval_required=True)
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/approvals/{pending_id}/reject",
            data={"reviewer": "alice", "reason": "spam"},
        )
        assert response.status_code in {200, 303}

    row = seeded_db.conn.execute(
        "SELECT deleted_at FROM memories WHERE id = ?", (pending_id,)
    ).fetchone()
    # deleted_at must now be a real timestamp, not the -1 sentinel.
    assert row["deleted_at"] is not None
    assert int(row["deleted_at"]) > 0

    audit = seeded_db.conn.execute(
        "SELECT operation, approved_by FROM audit_log WHERE memory_id = ? ORDER BY id DESC LIMIT 1",
        (pending_id,),
    ).fetchone()
    assert audit["operation"] == "forget"
    assert audit["approved_by"] == "alice"


@pytest.mark.anyio
async def test_htmx_request_returns_only_partial(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    """An HTMX GET / should return the list partial, not the full page chrome."""
    seeded_db.remember("Pending row", approval_required=True)
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"HX-Request": "true"})
        assert response.status_code == 200
        # Partial omits the <html> chrome.
        assert "<html" not in response.text.lower()
        assert "approvals-list" in response.text


@pytest.mark.anyio
async def test_empty_state_shown_when_no_pending(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "No pending approvals" in response.text
