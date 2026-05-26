"""Co-memorize Bulk Review screen (``/co-memorize``).

GET ``/co-memorize`` surfaces forget + merge candidates per the heuristic
in :mod:`amp_ui.services`. POST ``/co-memorize/apply`` accepts a
checkbox-form submission and applies every selected op via
:func:`services.apply_co_memorize`.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.templating import Jinja2Templates

from amp_ui import services


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


async def list_candidates(request: Request) -> Response:
    """GET ``/co-memorize`` — render forget/merge candidates."""
    db_path: str = request.app.state.db_path
    agent_id: str = request.app.state.agent_id
    candidates = services.co_memorize_candidates(db_path, agent_id)
    return _templates(request).TemplateResponse(
        request,
        "co_memorize.html",
        {"candidates": candidates, "active": "co_memorize", "result": None},
    )


async def apply(request: Request) -> Response:
    """POST ``/co-memorize/apply`` — apply every checked candidate.

    The form sends one ``op`` field per selected row of the form
    ``"<op_type>:<primary_id>:<secondary_id or empty>"`` so the route can
    parse a stable list without needing nested form encoding.
    """
    db_path: str = request.app.state.db_path
    agent_id: str = request.app.state.agent_id
    form = await request.form()
    raw_ops = form.getlist("op")
    ops: list[services.CoMemOp] = []
    for raw in raw_ops:
        if not isinstance(raw, str):
            continue
        parts = raw.split(":", 2)
        if len(parts) < 2 or parts[0] not in {"forget", "merge"}:
            continue
        op_type = parts[0]
        primary = parts[1]
        secondary = parts[2] if len(parts) == 3 and parts[2] else None
        # Cast op_type to the Literal expected by CoMemOp; safe because we
        # check the membership in the guard above.
        if op_type == "forget":
            ops.append(services.CoMemOp(op_type="forget", primary_id=primary))
        else:
            ops.append(
                services.CoMemOp(op_type="merge", primary_id=primary, secondary_id=secondary)
            )

    result = services.apply_co_memorize(db_path, ops)

    if request.headers.get("HX-Request") == "true":
        candidates = services.co_memorize_candidates(db_path, agent_id)
        return _templates(request).TemplateResponse(
            request,
            "co_memorize.html",
            {"candidates": candidates, "active": "co_memorize", "result": result},
        )
    # Non-HTMX form post: 303 back to the bulk review page.
    return RedirectResponse(url="/co-memorize", status_code=303)


__all__ = ["apply", "list_candidates"]
