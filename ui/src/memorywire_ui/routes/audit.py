"""Audit Log screen (``/audit``).

GET ``/audit`` renders the full table; ``GET /audit/export?format=json|csv``
streams the rows as a downloadable file.

The list view is HTMX-aware: on an ``HX-Request`` we return the table
partial only so live-filter changes don't redraw the whole page.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response
from starlette.templating import Jinja2Templates

from memorywire_ui import services

_DEFAULT_LIMIT = services.DEFAULT_AUDIT_PAGE


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


def _filters_from_query(request: Request) -> services.AuditFilters:
    q = request.query_params
    return services.AuditFilters(
        operation=q.get("operation") or None,
        agent_id=q.get("agent_id") or None,
        user_id=q.get("user_id") or None,
        memory_id=q.get("memory_id") or None,
        since_ms=int(q["since_ms"]) if q.get("since_ms", "").isdigit() else None,
        until_ms=int(q["until_ms"]) if q.get("until_ms", "").isdigit() else None,
    )


def _int_query(request: Request, key: str, default: int) -> int:
    raw = request.query_params.get(key)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


async def list_rows(request: Request) -> Response:
    """GET ``/audit`` â€” paginated, filterable audit-log view."""
    db_path: str = request.app.state.db_path
    filters = _filters_from_query(request)
    limit = _int_query(request, "limit", _DEFAULT_LIMIT)
    offset = _int_query(request, "offset", 0)

    rows, total = services.audit_query(db_path, filters, limit=limit, offset=offset)

    context = {
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": filters,
        "active": "audit",
        "has_prev": offset > 0,
        "has_next": offset + limit < total,
        "next_offset": offset + limit,
        "prev_offset": max(0, offset - limit),
    }

    template = (
        "_partials/audit_table.html"
        if request.headers.get("HX-Request") == "true"
        else "audit.html"
    )
    return _templates(request).TemplateResponse(request, template, context)


async def export(request: Request) -> Response:
    """GET ``/audit/export?format=...`` â€” JSON or CSV download."""
    db_path: str = request.app.state.db_path
    fmt = request.query_params.get("format", "json").lower()
    if fmt not in {"json", "csv"}:
        return Response("format must be 'json' or 'csv'", status_code=400)

    filters = _filters_from_query(request)
    body, content_type = services.audit_export(db_path, filters, fmt)  # type: ignore[arg-type]
    filename = f"amp-audit.{fmt}"
    return Response(
        content=body,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


__all__ = ["export", "list_rows"]
