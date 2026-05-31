"""Starlette application factory for the memorywire Governance UI.

The :func:`create_app` function wires the five route modules, mounts the
static directory, registers the Jinja2 environment on ``app.state``, and
ensures the UI-owned schema (``approval_patterns``) exists on the configured
SQLite database.

The factory accepts a ``db_path`` directly so tests can construct a fresh
app against a temporary database. Production use is via :mod:`memorywire_ui.__main__`,
which builds the same factory off environment variables.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from memorywire_ui import services
from memorywire_ui.middleware import (
    BearerAuthMiddleware,
    CSRFMiddleware,
    csrf_token_for_request,
    warn_if_public_host,
)
from memorywire_ui.routes import approvals, audit, co_memorize, health, patterns

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    *,
    db_path: str | Path | None = None,
    agent_id: str = "default",
    token: str | None = None,
    csrf_secret: bytes | None = None,
) -> Starlette:
    """Build the Starlette app.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database the OSS adapter writes to.
        If ``None``, fall back to the ``MEMORYWIRE_UI_DB_PATH`` env var, then to
        ``./memorywire-cli.db``. Pass ``":memory:"`` for an ephemeral app (only
        useful for smoke tests).
    agent_id:
        Agent scope used by every screen. Defaults to ``"default"``.
    token:
        Optional bearer-token for the governance API. When set, every
        request must carry ``Authorization: Bearer <token>`` (server
        clients) or the ``memorywire_ui_session=<token>`` cookie (browsers).
        When unset, auth is a no-op Ã¢â‚¬â€ preserved as the opt-in default
        so local dev keeps working without ceremony.
    csrf_secret:
        HMAC secret used to sign CSRF tokens. When ``None`` a fresh
        random secret is generated per-process. That is fine for v0 dev
        (and tests) but will mean operators are logged out across
        restarts; production deployments should pin it explicitly.
    """
    resolved_db = _resolve_db_path(db_path)
    services.ensure_schema(resolved_db)

    if token is None:
        warn_if_public_host()

    if csrf_secret is None:
        csrf_secret = secrets.token_bytes(32)

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals["agent_id"] = agent_id
    # Expose the per-request CSRF token to templates so the base template
    # can wire it onto HTMX's hx-headers attribute. The lambda reads from
    # the active request via Jinja's context, so callers don't have to
    # pass it through every TemplateResponse manually.
    templates.env.globals["csrf_token_for_request"] = csrf_token_for_request

    app = Starlette(
        debug=False,
        middleware=[
            Middleware(BearerAuthMiddleware, token=token),
            Middleware(CSRFMiddleware, secret=csrf_secret),
        ],
        routes=[
            Route("/", approvals.list_pending, name="approvals.list"),
            Route(
                "/approvals/{memory_id}/approve",
                approvals.approve,
                methods=["POST"],
                name="approvals.approve",
            ),
            Route(
                "/approvals/{memory_id}/reject",
                approvals.reject,
                methods=["POST"],
                name="approvals.reject",
            ),
            Route("/health-dashboard", health.dashboard, name="health.dashboard"),
            Route("/audit", audit.list_rows, name="audit.list"),
            Route("/audit/export", audit.export, name="audit.export"),
            Route("/co-memorize", co_memorize.list_candidates, name="co_memorize.list"),
            Route(
                "/co-memorize/apply",
                co_memorize.apply,
                methods=["POST"],
                name="co_memorize.apply",
            ),
            Route("/patterns", patterns.list_recos, name="patterns.list"),
            Route(
                "/patterns/{pattern_key}/auto-allow",
                patterns.accept,
                methods=["POST"],
                name="patterns.accept",
            ),
            Mount("/static", app=StaticFiles(directory=str(_STATIC_DIR)), name="static"),
        ],
    )

    # Attach shared state for the route modules. Stored on ``app.state``
    # rather than module globals so the factory remains pure Ã¢â‚¬â€ tests can
    # build multiple isolated apps against different databases.
    app.state.db_path = str(resolved_db)
    app.state.agent_id = agent_id
    app.state.templates = templates
    app.state.token = token
    app.state.csrf_secret = csrf_secret
    return app


def _resolve_db_path(db_path: str | Path | None) -> str:
    if db_path is not None:
        return ":memory:" if str(db_path) == ":memory:" else str(Path(db_path))
    env = os.environ.get("MEMORYWIRE_UI_DB_PATH")
    if env:
        return env
    return str(Path("./memorywire-cli.db"))


__all__ = ["create_app"]
