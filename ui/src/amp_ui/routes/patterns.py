"""Approval Patterns screen (``/patterns``).

GET ``/patterns`` shows the clustered recommendations from
:func:`amp_ui.services.pattern_recommendations`. POST
``/patterns/{key}/auto-allow`` accepts a recommendation so future pending
approvals matching the same (operation, type, keyword) cluster get
flagged as auto-approved on the Pending Approvals screen.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.templating import Jinja2Templates

from amp_ui import services


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


async def list_recos(request: Request) -> Response:
    """GET ``/patterns`` — render the recommendation table."""
    db_path: str = request.app.state.db_path
    agent_id: str = request.app.state.agent_id
    threshold_raw = request.query_params.get("threshold")
    try:
        threshold = (
            int(threshold_raw)
            if threshold_raw and threshold_raw.isdigit()
            else services.DEFAULT_PATTERN_THRESHOLD
        )
    except ValueError:
        threshold = services.DEFAULT_PATTERN_THRESHOLD

    recos = services.pattern_recommendations(db_path, agent_id, threshold=threshold)
    return _templates(request).TemplateResponse(
        request,
        "patterns.html",
        {"recos": recos, "threshold": threshold, "active": "patterns"},
    )


async def accept(request: Request) -> Response:
    """POST ``/patterns/{pattern_key}/auto-allow`` — persist the rule."""
    db_path: str = request.app.state.db_path
    agent_id: str = request.app.state.agent_id
    key = request.path_params["pattern_key"]
    form = await request.form()
    reviewer = str(form.get("reviewer") or "ui-operator")
    services.accept_pattern(db_path, key, agent_id=agent_id, reviewer=reviewer)

    if request.headers.get("HX-Request") == "true":
        recos = services.pattern_recommendations(db_path, agent_id)
        return _templates(request).TemplateResponse(
            request,
            "patterns.html",
            {
                "recos": recos,
                "threshold": services.DEFAULT_PATTERN_THRESHOLD,
                "active": "patterns",
            },
        )
    return RedirectResponse(url="/patterns", status_code=303)


__all__ = ["accept", "list_recos"]
