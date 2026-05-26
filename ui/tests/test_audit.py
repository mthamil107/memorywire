"""Tests for the Audit Log screen + the JSON/CSV export endpoint."""

from __future__ import annotations

from typing import Any

import httpx
import pytest


def _seed_audit(seeded_db: Any) -> None:
    # Three rows: two remembers, one recall.
    seeded_db.seed_audit(operation="remember", agent_id="default", memory_id="m1", approved_by=None)
    seeded_db.seed_audit(
        operation="remember", agent_id="default", memory_id="m2", approved_by="alice"
    )
    seeded_db.seed_audit(operation="recall", agent_id="default", memory_id=None, approved_by=None)


@pytest.mark.anyio
async def test_audit_page_returns_200(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    _seed_audit(seeded_db)
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit")
        assert response.status_code == 200
        assert "Audit log" in response.text


@pytest.mark.anyio
async def test_filter_by_operation(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    _seed_audit(seeded_db)
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit?operation=recall")
        assert response.status_code == 200
        # No "remember" rows on this page; the operation column should not contain a
        # plain "remember" badge body.
        assert "recall" in response.text
        assert ">remember<" not in response.text


@pytest.mark.anyio
async def test_pagination_respects_limit_offset(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    for i in range(7):
        seeded_db.seed_audit(
            operation="remember",
            agent_id="default",
            memory_id=f"m{i}",
            approved_by=None,
            ts=1_700_000_000_000 + i,
        )
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit?limit=2&offset=0")
        assert response.status_code == 200
        # Two rows of ts column should be rendered; check no third id surfaces.
        # Since rendering varies slightly we count via the partial endpoint.
        partial = await client.get("/audit?limit=2&offset=0", headers={"HX-Request": "true"})
        # Count "<tr" occurrences minus the header (none in partial -> all data).
        # The partial only emits one <tbody> + N <tr>.
        data_rows = partial.text.count("<tr ")
        assert data_rows == 2


@pytest.mark.anyio
async def test_csv_export_returns_csv(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    _seed_audit(seeded_db)
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit/export?format=csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        text = response.text
        assert text.startswith("id,ts,operation,")
        # At least one data line beyond the header.
        assert len(text.strip().splitlines()) >= 2


@pytest.mark.anyio
async def test_json_export_returns_json(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    _seed_audit(seeded_db)
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit/export?format=json")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert isinstance(body, list)
        assert len(body) >= 3


@pytest.mark.anyio
async def test_export_rejects_bad_format(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit/export?format=xml")
        assert response.status_code == 400
