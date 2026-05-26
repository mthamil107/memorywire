"""Smoke tests for the Starlette factory + top-level routing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from amp_ui.app import create_app
from amp_ui.middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


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
async def test_boot_against_empty_db(tmp_path: Path) -> None:
    """Bug-1 regression: every page must work against a fresh, empty SQLite file.

    Before the fix, ``ensure_schema`` only created ``approval_patterns``;
    the OSS schema (``memories``, ``audit_log``, ...) was missing on a
    DB that the OSS adapter had not yet written to, so every page 500'd
    against the default ``./amp-cli.db`` on first boot.
    """
    db_path = tmp_path / "empty.db"
    app = create_app(db_path=str(db_path), agent_id="empty")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ["/", "/audit", "/health-dashboard", "/co-memorize", "/patterns"]:
            response = await client.get(path)
            assert response.status_code == 200, (
                path,
                response.status_code,
                response.text[:300],
            )


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


# ---------------------------------------------------------------------------
# Bug-3 regressions: bearer-token auth + CSRF middleware
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth_required_when_token_set(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    """When ``token`` is set, requests without the bearer header are 401."""
    app = app_for_path(seeded_db.db_path, token="s3cret", agent_id="x")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauth = await client.get("/")
        assert unauth.status_code == 401
        assert unauth.headers.get("WWW-Authenticate", "").lower().startswith("bearer")

        authed = await client.get("/", headers={"Authorization": "Bearer s3cret"})
        assert authed.status_code == 200


@pytest.mark.anyio
async def test_csrf_required_on_post(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    """Mutating routes must reject a POST without a matching CSRF token."""
    seeded_db.remember("dummy", approval_required=True)
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # No CSRF cookie + no header → 403.
        no_csrf = await client.post("/approvals/x/approve", data={"reviewer": "a"})
        assert no_csrf.status_code == 403, no_csrf.text[:200]

        # Prime cookie via a GET, then echo it back in the header.
        await client.get("/")
        token = client.cookies.get(CSRF_COOKIE_NAME, "")
        assert token, "GET should have minted the CSRF cookie"
        with_csrf = await client.post(
            "/approvals/some-bad-id/approve",
            data={"reviewer": "a"},
            headers={CSRF_HEADER_NAME: token},
        )
        # 403 means CSRF failed — that's what we *don't* want here. 404 is
        # fine (the memory id is bogus, but CSRF accepted the request).
        assert with_csrf.status_code != 403, with_csrf.text[:200]


@pytest.mark.anyio
async def test_no_auth_when_token_unset(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    """Auth is opt-in: with no token configured, GET / works without a header."""
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200


@pytest.mark.anyio
async def test_bearer_request_bypasses_csrf(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    """Server-to-server clients authed via Bearer must not also need CSRF."""
    app = app_for_path(seeded_db.db_path, token="s3cret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/approvals/nope/approve",
            data={"reviewer": "alice"},
            headers={"Authorization": "Bearer s3cret"},
        )
        # 404 because the row doesn't exist; the important thing is *not* 403.
        assert response.status_code != 403


@pytest.mark.anyio
async def test_csrf_token_exposed_to_template(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    """The base template must inject the CSRF token onto the body tag so
    HTMX picks it up via hx-headers."""
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "X-CSRF-Token" in response.text
        # The body tag should carry the hx-headers attribute.
        assert "hx-headers" in response.text
