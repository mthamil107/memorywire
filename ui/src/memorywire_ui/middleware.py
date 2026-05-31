"""ASGI middleware for the memorywire Governance UI: bearer-token auth + CSRF.

Two middlewares ship from this module, both opt-in via :func:`amp_ui.app.create_app`:

* :class:`BearerAuthMiddleware` Ã¢â‚¬â€ gate every request behind a static
  bearer token, with a cookie escape-hatch for browser flows. No-op
  when ``token`` is ``None`` (local-dev default).
* :class:`CSRFMiddleware` Ã¢â‚¬â€ protects state-changing requests (POST /
  PUT / DELETE / PATCH) with the standard double-submit-cookie pattern.
  GETs mint a signed token cookie; mutating requests must echo it back
  via an ``X-CSRF-Token`` header (HTMX's hx-headers attribute sends it
  automatically once the body tag is wired up in ``base.html``).

Both middlewares are deliberately small Ã¢â‚¬â€ itsdangerous-style cookie
sessions are overkill for v0 here, where the threat model is a single
operator on localhost or behind a reverse proxy.

Security notes
--------------
* Bypass: when an ``Authorization: Bearer`` header is present, CSRF is
  skipped. This is because server-to-server clients (curl scripts, CI
  bots, the memorywire CLI itself) cannot keep a cookie jar across requests,
  and a stolen bearer is a separate compromise.
* Constant-time comparison via :func:`hmac.compare_digest` guards
  against timing oracles on both the bearer and the CSRF token.
* The CSRF secret is unstructured bytes Ã¢â‚¬â€ we sign ``token || timestamp``
  with HMAC-SHA256 so a token leaked via a referer header cannot be
  trivially replayed past its expiry. For v0 the expiry is 24h.
"""

from __future__ import annotations

import base64
import hmac
import os
import secrets
import sys
import time
from collections.abc import Iterable
from hashlib import sha256
from typing import Final

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSRF_COOKIE_NAME: Final[str] = "memorywire_ui_csrf"
SESSION_COOKIE_NAME: Final[str] = "memorywire_ui_session"
CSRF_HEADER_NAME: Final[str] = "X-CSRF-Token"
CSRF_TOKEN_TTL_S: Final[int] = 24 * 3600
# State-changing methods that require a CSRF token when no bearer header is set.
_MUTATING_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def warn_if_public_host() -> None:
    """Emit a stderr warning when the UI is bound to a non-loopback host but
    no ``MEMORYWIRE_UI_TOKEN`` was supplied. Called from ``create_app`` so the
    warning surfaces on every boot, including in tests if relevant.
    """
    host = os.environ.get("MEMORYWIRE_UI_HOST", "")
    if host and host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"[memorywire-ui] WARNING: MEMORYWIRE_UI_HOST={host!r} but MEMORYWIRE_UI_TOKEN is not set; "
            "the governance UI is unauthenticated on a public-ish bind address.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Bearer-token auth
# ---------------------------------------------------------------------------


class BearerAuthMiddleware:
    """Gate every request behind a static bearer token.

    Accepts either ``Authorization: Bearer <token>`` (for API clients) or
    the ``memorywire_ui_session=<token>`` cookie (for browser flows). On any
    mismatch returns ``401`` with a ``WWW-Authenticate: Bearer`` header.

    No-op when ``token`` is ``None`` Ã¢â‚¬â€ that preserves the current
    behaviour for unauthenticated local development.
    """

    def __init__(self, app: ASGIApp, *, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.token is None:
            await self.app(scope, receive, send)
            return

        if _request_is_authenticated(scope, self.token):
            await self.app(scope, receive, send)
            return

        response = PlainTextResponse(
            "unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="memorywire-ui"'},
        )
        await response(scope, receive, send)


def _request_is_authenticated(scope: Scope, expected_token: str) -> bool:
    """Return True if the request carries a valid bearer header or session cookie."""
    headers = _headers_dict(scope)
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer "):
        presented = auth[len("Bearer ") :].strip()
        if presented and hmac.compare_digest(presented, expected_token):
            return True
    cookies = _parse_cookies(headers.get("cookie", ""))
    session = cookies.get(SESSION_COOKIE_NAME, "")
    return bool(session) and hmac.compare_digest(session, expected_token)


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


class CSRFMiddleware:
    """Double-submit-cookie CSRF for browser-driven POSTs.

    * On every GET response: set the ``amp_ui_csrf`` cookie if not already
      present.
    * On every mutating request: require the ``X-CSRF-Token`` header to
      match the cookie *and* pass HMAC verification with the per-process
      secret.

    Bypassed entirely for requests carrying an ``Authorization: Bearer``
    header Ã¢â‚¬â€ server-to-server clients use the bearer for both authn and
    integrity, and asking them to maintain a cookie jar is gratuitous.
    """

    def __init__(self, app: ASGIApp, *, secret: bytes) -> None:
        self.app = app
        self.secret = secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        headers = _headers_dict(scope)
        cookies = _parse_cookies(headers.get("cookie", ""))

        if method in _MUTATING_METHODS and "authorization" not in headers:
            presented_header = headers.get(CSRF_HEADER_NAME.lower(), "")
            cookie_token = cookies.get(CSRF_COOKIE_NAME, "")
            if (
                not presented_header
                or not cookie_token
                or not hmac.compare_digest(presented_header, cookie_token)
                or not self._verify(cookie_token)
            ):
                response = PlainTextResponse("csrf token missing or invalid", status_code=403)
                await response(scope, receive, send)
                return

        # For safe methods (and successful mutating ones) ensure the
        # client has a fresh CSRF token cookie. We do this by wrapping
        # ``send`` and injecting a Set-Cookie header on the response head
        # whenever the inbound request did not already carry the cookie.
        needs_cookie = cookies.get(CSRF_COOKIE_NAME) is None
        new_token: str | None = self._mint() if needs_cookie else None

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start" and new_token is not None:
                raw_headers: list[tuple[bytes, bytes]] = list(message.get("headers") or [])
                cookie_value = (
                    f"{CSRF_COOKIE_NAME}={new_token}; Path=/; SameSite=Lax; "
                    f"Max-Age={CSRF_TOKEN_TTL_S}; HttpOnly"
                )
                raw_headers.append((b"set-cookie", cookie_value.encode("ascii")))
                message["headers"] = raw_headers
            await send(message)

        # Make the per-request CSRF token available to handlers via
        # ``request.state.csrf_token`` so the base template can echo it
        # back to HTMX. The token is whatever the client already has, or
        # the new one we just minted.
        scope_state: dict[str, object] = scope.setdefault("state", {})
        scope_state["csrf_token"] = (
            new_token if new_token is not None else cookies.get(CSRF_COOKIE_NAME, "")
        )

        await self.app(scope, receive, send_wrapper)

    def _mint(self) -> str:
        """Return a fresh, HMAC-signed CSRF token."""
        nonce = secrets.token_urlsafe(16)
        ts = str(int(time.time()))
        payload = f"{nonce}.{ts}"
        mac = hmac.new(self.secret, payload.encode("ascii"), sha256).digest()
        return f"{payload}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode('ascii')}"

    def _verify(self, token: str) -> bool:
        """Verify HMAC and freshness for a presented CSRF token."""
        if token.count(".") != 2:
            return False
        nonce, ts_str, sig = token.split(".", 2)
        if not nonce or not ts_str.isdigit():
            return False
        try:
            ts = int(ts_str)
        except ValueError:
            return False
        if time.time() - ts > CSRF_TOKEN_TTL_S:
            return False
        expected = hmac.new(self.secret, f"{nonce}.{ts_str}".encode("ascii"), sha256).digest()
        try:
            sig_bytes = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(expected, sig_bytes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers_dict(scope: Scope) -> dict[str, str]:
    """Lower-cased header dict from an ASGI scope. Last value wins (RFC 7230)."""
    raw: Iterable[tuple[bytes, bytes]] = scope.get("headers") or []
    out: dict[str, str] = {}
    for name, value in raw:
        out[name.decode("latin-1").lower()] = value.decode("latin-1")
    return out


def _parse_cookies(header: str) -> dict[str, str]:
    """Tiny cookie parser. Tolerates spaces, ignores invalid items."""
    out: dict[str, str] = {}
    for item in header.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, _, value = item.partition("=")
        out[name.strip()] = value.strip()
    return out


def csrf_token_for_request(request: Request) -> str:
    """Return the CSRF token templates should echo, or '' if CSRF is disabled."""
    state = getattr(request, "state", None)
    if state is None:
        return ""
    return str(getattr(state, "csrf_token", "") or "")


__all__ = [
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "CSRF_TOKEN_TTL_S",
    "SESSION_COOKIE_NAME",
    "BearerAuthMiddleware",
    "CSRFMiddleware",
    "csrf_token_for_request",
    "warn_if_public_host",
]
