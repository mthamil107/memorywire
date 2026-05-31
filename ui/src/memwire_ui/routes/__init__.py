"""Per-screen Starlette route modules.

Each module exposes plain async callables that the
:mod:`amp_ui.app` factory binds to specific URL patterns. Importing this
package re-exports the route handlers for convenience.
"""

from __future__ import annotations

from memwire_ui.routes import approvals, audit, co_memorize, health, patterns

__all__ = ["approvals", "audit", "co_memorize", "health", "patterns"]
