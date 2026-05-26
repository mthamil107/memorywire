"""Pending Approvals screen — the home page (``/``).

GET ``/`` renders every pending memory awaiting HITL review. The page
auto-refreshes every 10s via HTMX; each row carries Approve / Reject
buttons that POST to the per-row endpoints below.

When an HTMX request comes in (``HX-Request`` header set) we render the
list partial only, so the auto-refresh doesn't blow away the page chrome.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.templating import Jinja2Templates

from amp_ui import services


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


async def list_pending(request: Request) -> Response:
    """GET ``/`` — render the pending-approvals list."""
    db_path: str = request.app.state.db_path
    agent_id: str = request.app.state.agent_id

    rows = services.list_pending(db_path, agent_id)

    template = (
        "_partials/approvals_list.html"
        if request.headers.get("HX-Request") == "true"
        else "approvals.html"
    )
    return _templates(request).TemplateResponse(
        request, template, {"rows": rows, "active": "approvals"}
    )


async def approve(request: Request) -> Response:
    """POST ``/approvals/{memory_id}/approve`` — flip the row to approved."""
    db_path: str = request.app.state.db_path
    memory_id = request.path_params["memory_id"]
    form = await request.form()
    reviewer = str(form.get("reviewer") or "ui-operator")
    reason = form.get("reason")
    services.approve(db_path, memory_id, reviewer, str(reason) if reason else None)
    return _post_action_response(request)


async def reject(request: Request) -> Response:
    """POST ``/approvals/{memory_id}/reject`` — soft-delete the row."""
    db_path: str = request.app.state.db_path
    memory_id = request.path_params["memory_id"]
    form = await request.form()
    reviewer = str(form.get("reviewer") or "ui-operator")
    reason = form.get("reason")
    services.reject(db_path, memory_id, reviewer, str(reason) if reason else None)
    return _post_action_response(request)


def _post_action_response(request: Request) -> Response:
    """After approve/reject: HTMX gets the refreshed list partial; plain
    POSTs get a 303 back to the home page so the browser address bar stays
    clean."""
    if request.headers.get("HX-Request") == "true":
        db_path: str = request.app.state.db_path
        agent_id: str = request.app.state.agent_id
        rows = services.list_pending(db_path, agent_id)
        return _templates(request).TemplateResponse(
            request,
            "_partials/approvals_list.html",
            {"rows": rows, "active": "approvals"},
        )
    return RedirectResponse(url="/", status_code=303)


__all__ = ["approve", "list_pending", "reject"]
