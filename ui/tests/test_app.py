"""Smoke tests for the Starlette factory + top-level routing."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import pytest
from memwire_ui.__main__ import _assert_safe_public_config, _load_csrf_secret_from_env
from memwire_ui.app import create_app
from memwire_ui.middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


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
    against the default ``./memwire-cli.db`` on first boot.
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
        # No CSRF cookie + no header Ã¢â€ â€™ 403.
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
        # 403 means CSRF failed Ã¢â‚¬â€ that's what we *don't* want here. 404 is
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


# ---------------------------------------------------------------------------
# MEMWIRE_UI_CSRF_SECRET env-var handling
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_csrf_secret_from_env_var(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    """Two apps built with the same pinned CSRF secret must accept each
    other's tokens Ã¢â‚¬â€ proving the env-var path bypasses the per-process
    random default and keeps sessions stable across restarts."""
    raw_secret = b"x" * 32
    encoded = base64.b64encode(raw_secret).decode("ascii")

    # The helper that __main__ uses to parse the env var must decode the
    # same bytes back when given the base64 payload.
    decoded = _load_csrf_secret_from_env(encoded)
    assert decoded == raw_secret

    app_a = app_for_path(seeded_db.db_path, csrf_secret=raw_secret)
    app_b = app_for_path(seeded_db.db_path, csrf_secret=raw_secret)

    # Mint a CSRF token against app_a, then send it back to app_b along
    # with the matching cookie. If both apps share the same secret app_b
    # must accept it (i.e. *not* return 403).
    transport_a = httpx.ASGITransport(app=app_a)
    async with httpx.AsyncClient(transport=transport_a, base_url="http://test") as client_a:
        await client_a.get("/")
        token = client_a.cookies.get(CSRF_COOKIE_NAME, "")
    assert token, "GET against app_a should have minted a CSRF token"

    transport_b = httpx.ASGITransport(app=app_b)
    async with httpx.AsyncClient(transport=transport_b, base_url="http://test") as client_b:
        client_b.cookies.set(CSRF_COOKIE_NAME, token)
        response = await client_b.post(
            "/approvals/some-bogus-id/approve",
            data={"reviewer": "alice"},
            headers={CSRF_HEADER_NAME: token},
        )
        # 403 would mean app_b rejected the CSRF token minted by app_a;
        # any other status means it accepted the token (the memory id is
        # bogus on purpose Ã¢â‚¬â€ we don't care whether the handler 404s).
        assert response.status_code != 403, response.text[:200]

    # And the negative control: a *different* secret must reject the
    # foreign token.
    app_c = app_for_path(seeded_db.db_path, csrf_secret=b"y" * 32)
    transport_c = httpx.ASGITransport(app=app_c)
    async with httpx.AsyncClient(transport=transport_c, base_url="http://test") as client_c:
        client_c.cookies.set(CSRF_COOKIE_NAME, token)
        rejected = await client_c.post(
            "/approvals/some-bogus-id/approve",
            data={"reviewer": "alice"},
            headers={CSRF_HEADER_NAME: token},
        )
        assert rejected.status_code == 403, rejected.text[:200]


def test_csrf_secret_too_short_rejected() -> None:
    """A base64 value that decodes to <16 bytes must raise, not silently pass."""
    too_short = base64.b64encode(b"abcd").decode("ascii")
    with pytest.raises(ValueError, match="at least 16"):
        _load_csrf_secret_from_env(too_short)


def test_csrf_secret_invalid_base64_rejected() -> None:
    """Garbage that isn't valid base64 must raise, not silently pass."""
    with pytest.raises(ValueError, match="not valid base64"):
        _load_csrf_secret_from_env("this is !!! not base64 @@@")


def test_csrf_secret_env_unset_returns_none() -> None:
    """Empty / unset env var falls back to per-process randomness."""
    assert _load_csrf_secret_from_env(None) is None
    assert _load_csrf_secret_from_env("") is None


# ---------------------------------------------------------------------------
# Bug-4 regressions: fail-closed public-bind safety check
# ---------------------------------------------------------------------------


def test_assert_safe_public_config_loopback_no_token_passes() -> None:
    """Loopback bind (127.0.0.1) without a token is fine Ã¢â‚¬â€ nothing off-box reaches it."""
    # No exception expected.
    _assert_safe_public_config("127.0.0.1", None, False)
    _assert_safe_public_config("localhost", None, False)
    _assert_safe_public_config("::1", None, False)


def test_assert_safe_public_config_public_no_token_exits() -> None:
    """Public bind (0.0.0.0) without a token must terminate the process."""
    with pytest.raises(SystemExit) as exc_info:
        _assert_safe_public_config("0.0.0.0", None, False)
    assert exc_info.value.code == 1
    # Empty-string token (Fly secrets sometimes injects "") must also fail.
    with pytest.raises(SystemExit):
        _assert_safe_public_config("0.0.0.0", "", False)


def test_assert_safe_public_config_public_with_token_passes() -> None:
    """Public bind with a non-empty token is the production path Ã¢â‚¬â€ must succeed."""
    _assert_safe_public_config("0.0.0.0", "tok", False)
    _assert_safe_public_config("203.0.113.10", "another-token", False)


def test_assert_safe_public_config_explicit_opt_out_passes() -> None:
    """``MEMWIRE_UI_ALLOW_UNAUTHENTICATED_PUBLIC=1`` must bypass the check."""
    # No exception even with a public host and no token, because the
    # operator explicitly accepted the risk.
    _assert_safe_public_config("0.0.0.0", None, True)
    _assert_safe_public_config("0.0.0.0", "", True)
