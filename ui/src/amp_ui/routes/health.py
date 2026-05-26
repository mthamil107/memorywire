"""Memory Health dashboard (``/health-dashboard``).

Renders four cards: total memory count, staleness percentage, drift
contradiction-pair count, and a HTML/CSS bar chart of memory counts by
type. Each card links into a pre-filtered audit log query so operators
can drill straight from a metric to the underlying events.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response
from starlette.templating import Jinja2Templates

from amp_ui import services


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


async def dashboard(request: Request) -> Response:
    """GET ``/health-dashboard`` — render the four health cards."""
    db_path: str = request.app.state.db_path
    agent_id: str = request.app.state.agent_id

    metrics = services.health_metrics(db_path, agent_id)

    # Pre-compute the bar chart layout server-side so the template stays
    # logic-light.
    max_count = max(metrics.coverage_by_type.values(), default=0)
    coverage_view = [
        {
            "type": t,
            "count": n,
            "width_pct": (100.0 * n / max_count) if max_count else 0.0,
        }
        for t, n in sorted(metrics.coverage_by_type.items(), key=lambda item: -item[1])
    ]

    return _templates(request).TemplateResponse(
        request,
        "health.html",
        {
            "metrics": metrics,
            "coverage": coverage_view,
            "active": "health",
        },
    )


__all__ = ["dashboard"]
