"""amp-governance-ui â€” Pro-tier governance surface over the memorywire protocol.

The UI consumes the same SQLite database the
:class:`memorywire.store.sqlite_vec.SqliteVecStore` adapter writes to. It exposes
five screens (pending approvals, health dashboard, audit log, co-memorize
bulk review, approval patterns) backed by Starlette + Jinja2 + HTMX.

See :mod:`amp_ui.app` for the application factory.
"""

from __future__ import annotations

from memorywire_ui.app import create_app

__all__ = ["create_app"]
