"""Smoke tests for the Starlette factory + top-level routing."""

from __future__ import annotations

from typing import Any

import httpx
import pytest


@pytest.mark.anyio
async def test_smoke_routes_return_200(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ["/", "/audit", "/health-dashboard", "/co-memorize", "/patterns"]:
            response = await client.get(path)
            assert response.status_code == 200, (path, response.text[:200])


@pytest.mark.anyio
async def test_missing_route_returns_404(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/no-such-page")
        assert response.status_code == 404


@pytest.mark.anyio
async def test_static_css_served(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/static/app.css")
        assert response.status_code == 200
        assert b".nav-link" in response.content


@pytest.mark.anyio
async def test_create_app_ensures_schema(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    """The factory must idempotently create the approval_patterns table."""
    app_for_path(seeded_db.db_path)
    # Calling create_app again on the same db must not raise.
    app_for_path(seeded_db.db_path)
    rows = seeded_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='approval_patterns'"
    ).fetchall()
    assert len(rows) == 1
