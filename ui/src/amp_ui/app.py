"""Starlette application factory for the AMP Governance UI.

The :func:`create_app` function wires the five route modules, mounts the
static directory, registers the Jinja2 environment on ``app.state``, and
ensures the UI-owned schema (``approval_patterns``) exists on the configured
SQLite database.

The factory accepts a ``db_path`` directly so tests can construct a fresh
app against a temporary database. Production use is via :mod:`amp_ui.__main__`,
which builds the same factory off environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from amp_ui import services
from amp_ui.routes import approvals, audit, co_memorize, health, patterns

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    *,
    db_path: str | Path | None = None,
    agent_id: str = "default",
) -> Starlette:
    """Build the Starlette app.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database the OSS adapter writes to.
        If ``None``, fall back to the ``AMP_UI_DB_PATH`` env var, then to
        ``./amp-cli.db``. Pass ``":memory:"`` for an ephemeral app (only
        useful for smoke tests).
    agent_id:
        Agent scope used by every screen. Defaults to ``"default"``.
    """
    resolved_db = _resolve_db_path(db_path)
    services.ensure_schema(resolved_db)

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals["agent_id"] = agent_id

    app = Starlette(
        debug=False,
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
    # rather than module globals so the factory remains pure — tests can
    # build multiple isolated apps against different databases.
    app.state.db_path = str(resolved_db)
    app.state.agent_id = agent_id
    app.state.templates = templates
    return app


def _resolve_db_path(db_path: str | Path | None) -> str:
    if db_path is not None:
        return ":memory:" if str(db_path) == ":memory:" else str(Path(db_path))
    env = os.environ.get("AMP_UI_DB_PATH")
    if env:
        return env
    return str(Path("./amp-cli.db"))


__all__ = ["create_app"]
