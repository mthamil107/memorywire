"""Data-access layer for the AMP Governance UI.

The UI is a thin renderer over the same SQLite database the
:class:`amp.store.sqlite_vec.SqliteVecStore` adapter writes to. This module
opens a separate connection (read-mostly, single-writer-via-WAL) and exposes
typed helpers for each screen:

* :func:`list_pending`           — Pending Approvals screen.
* :func:`approve` / :func:`reject` — HITL actions on a pending row.
* :func:`audit_query`            — Audit Log screen + the patterns clustering.
* :func:`health_metrics`         — Memory Health dashboard.
* :func:`co_memorize_candidates` / :func:`apply_co_memorize` — Bulk-review screen.
* :func:`pattern_recommendations` / :func:`accept_pattern` — Approval Patterns
  screen, with an idempotent :func:`ensure_schema` that adds the small
  ``approval_patterns`` table the UI owns.

The schema we read is owned by the OSS protocol; we never alter its tables.
The single table we *do* write to of our own is ``approval_patterns``, gated
behind :func:`ensure_schema`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from amp.store.sqlite_vec import PENDING_APPROVAL_DELETED_AT

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sentinel for memories awaiting governance approval. Re-exported from the OSS
# adapter so the UI and the storage contract stay in lockstep — when the OSS
# side bumps SCHEMA_VERSION and changes the sentinel, the UI follows
# automatically rather than silently desyncing on a hand-copied literal.
PENDING_SENTINEL = PENDING_APPROVAL_DELETED_AT

# Co-memorize forget-candidate thresholds. Documented in the heuristic.
_FORGET_AGE_DAYS = 90
_FORGET_CONFIDENCE_BELOW = 0.5

# Co-memorize merge-candidate threshold (Jaccard token overlap).
_MERGE_OVERLAP = 0.7

# Health dashboard staleness window.
_STALE_DAYS = 30

# Health dashboard drift heuristic — token-overlap threshold above which two
# memories of the same user_id are flagged as a contradiction pair.
_DRIFT_OVERLAP = 0.7

# Approval-pattern clustering default minimum cluster size.
DEFAULT_PATTERN_THRESHOLD = 5

# Audit-log pagination default.
DEFAULT_AUDIT_PAGE = 50


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PendingApproval:
    """A row on the Pending Approvals screen."""

    id: str
    agent_id: str
    user_id: str | None
    type: str
    content: str
    metadata: dict[str, Any] | None
    confidence: float | None
    source: str | None
    created_at: int
    diff: dict[str, list[dict[str, Any]]]
    auto_approved: bool = False
    auto_pattern_key: str | None = None


@dataclass(slots=True)
class AuditFilters:
    """GET query params for the Audit Log screen."""

    operation: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    memory_id: str | None = None
    since_ms: int | None = None
    until_ms: int | None = None


@dataclass(slots=True)
class AuditRow:
    """One row in an audit-log query result."""

    id: int
    ts: int
    operation: str
    agent_id: str | None
    user_id: str | None
    memory_id: str | None
    payload: dict[str, Any]
    result: dict[str, Any] | None
    approved_by: str | None
    approval_at: int | None


@dataclass(slots=True)
class HealthMetrics:
    """The four cards on the Memory Health dashboard."""

    total: int
    stale_count: int
    stale_pct: float
    drift_pairs: int
    coverage_by_type: dict[str, int]


@dataclass(slots=True)
class CoMemCandidate:
    """A row on the Co-memorize Bulk Review screen."""

    op_type: Literal["forget", "merge"]
    primary_id: str
    secondary_id: str | None
    content: str
    reasoning: str


@dataclass(slots=True)
class CoMemOp:
    """A single operation submitted from the Co-memorize Apply form."""

    op_type: Literal["forget", "merge"]
    primary_id: str
    secondary_id: str | None = None


@dataclass(slots=True)
class ApplyOpResult:
    """Per-op outcome inside an :class:`ApplyResult`.

    ``skipped`` is true when the row did not exist, did not belong to the
    requesting agent, or was already soft-deleted — none of those are bugs
    in the operator's workflow, so we report them rather than raising.
    """

    op_type: Literal["forget", "merge"]
    primary_id: str
    secondary_id: str | None = None
    skipped: bool = False
    reason: str | None = None


@dataclass(slots=True)
class ApplyResult:
    """Aggregate result of a Co-memorize Apply submission."""

    applied: int
    skipped: int
    errors: list[str]
    results: list[ApplyOpResult] = field(default_factory=list)


@dataclass(slots=True)
class PatternReco:
    """A clustered approval-decision recommendation."""

    key: str
    approver: str
    operation: str
    memory_type: str
    keyword: str
    decision: Literal["approve", "reject"]
    count: int
    accepted: bool


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a fresh connection to the AMP SQLite database.

    The UI opens its own connection per call (Starlette's request lifecycle
    is short and SQLite connections are cheap). WAL mode is set so the
    write path the OSS adapter uses does not block our reads.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL is not supported on :memory: (silently kept as ``memory`` journal).
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now_ms() -> int:
    return int(time.time() * 1000)


def _parse_json(value: Any) -> dict[str, Any] | None:
    """Decode a JSON-encoded column value into a dict, or return ``None``."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if not isinstance(value, str | bytes):
        return None
    try:
        loaded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row into a plain dict, parsing the metadata column."""
    out: dict[str, Any] = dict(row)
    if "metadata" in out:
        out["metadata"] = _parse_json(out.get("metadata"))
    return out


_WORD_RE = re.compile(r"\w+")


def _tokens(text: str) -> set[str]:
    """Lowercase token set used by the heuristics."""
    return {t.lower() for t in _WORD_RE.findall(text or "")}


def _jaccard(a: str, b: str) -> float:
    """Token-set Jaccard similarity in [0, 1]."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _extract_keyword(content: str) -> str:
    """Pick a single representative keyword from a memory's content.

    Used to bucket approval decisions into clusters. We pick the longest
    word that is not a stop-word; ties go to the first occurrence. The
    keyword extractor is deliberately tiny — pattern-recommendation quality
    is bounded by audit-log signal, not by the keyword classifier.
    """
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "have",
        "has",
        "will",
        "was",
        "were",
        "are",
        "you",
        "your",
        "but",
        "not",
        "any",
        "all",
    }
    words = [w.lower() for w in _WORD_RE.findall(content or "")]
    candidates: list[str] = [w for w in words if len(w) >= 4 and w not in stop]
    if not candidates:
        return ""
    candidates.sort(key=lambda w: (-len(w), words.index(w)))
    return candidates[0]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NotPendingError(LookupError):
    """Raised when an approve/reject targets a row that is missing, not
    pending, or belongs to a different agent. Subclasses :class:`LookupError`
    so existing handlers that catch ``LookupError`` continue to work — and
    the route layer can map either to a 404.
    """


# ---------------------------------------------------------------------------
# Schema management — UI-owned tables + bootstrap of the OSS schema
# ---------------------------------------------------------------------------


def ensure_schema(db_path: str | Path) -> None:
    """Idempotently create both the UI-owned table and the OSS storage schema.

    The UI is a read-mostly renderer over the same database the OSS adapter
    writes to. In production the OSS process always boots first and creates
    its schema as a side effect of constructing a :class:`SqliteVecStore`;
    in tests we lean on the seeded_db fixture for the same effect. But when
    an operator points the UI at a brand-new file (the common dev-loop —
    ``python -m amp_ui`` against an empty ``./amp-cli.db``), nothing has
    ever created the OSS tables and every page returns 500 from a
    ``no such table: memories`` error.

    Fix: instantiate a ``SqliteVecStore`` here, let its ``_init_schema``
    run, then drop it. We pass a no-op embedder so the import is cheap and
    sentence-transformers is never touched — the embedder is only invoked
    on actual writes, which we never perform.

    The OSS schema bootstrap is idempotent (every CREATE uses ``IF NOT
    EXISTS``), so calling this on every app boot is safe.
    """
    # Lazy / inline import so this module stays importable even on builds
    # where the OSS adapter's optional deps are not installed. The fake
    # embedder below means we never load sentence-transformers.
    from amp.store.sqlite_vec import SqliteVecStore

    store = SqliteVecStore(db_path=str(db_path), embedder=lambda _text: [0.0])
    try:
        # Constructor already invoked _init_schema; we just need the side
        # effect of the tables existing on this file.
        pass
    finally:
        store.close()

    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_patterns (
              key         TEXT PRIMARY KEY,
              approver    TEXT NOT NULL,
              operation   TEXT NOT NULL,
              memory_type TEXT NOT NULL,
              keyword     TEXT NOT NULL,
              decision    TEXT NOT NULL CHECK (decision IN ('approve','reject')),
              accepted_at INTEGER NOT NULL
            )
            """
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pending Approvals
# ---------------------------------------------------------------------------


def _find_current_match(
    conn: sqlite3.Connection,
    agent_id: str,
    pending_row: sqlite3.Row,
) -> dict[str, Any] | None:
    """Look up the closest live row for diffing against a pending row.

    Match order:
    1. ``metadata.entity_name`` equality (same agent, not deleted).
    2. Same agent + same content prefix (first 32 chars).

    Returns the matched row as a plain dict, or ``None`` when nothing is
    close enough to diff against.
    """
    metadata = _parse_json(pending_row["metadata"])
    entity_name = metadata.get("entity_name") if metadata else None
    if entity_name:
        row = conn.execute(
            """
            SELECT * FROM memories
            WHERE agent_id = ?
              AND deleted_at IS NULL
              AND json_extract(metadata, '$.entity_name') = ?
              AND id != ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (agent_id, entity_name, pending_row["id"]),
        ).fetchone()
        if row is not None:
            return _row_dict(row)

    content_prefix = (pending_row["content"] or "")[:32]
    if content_prefix:
        row = conn.execute(
            """
            SELECT * FROM memories
            WHERE agent_id = ?
              AND deleted_at IS NULL
              AND substr(content, 1, ?) = ?
              AND id != ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (agent_id, len(content_prefix), content_prefix, pending_row["id"]),
        ).fetchone()
        if row is not None:
            return _row_dict(row)

    return None


def list_pending(db_path: str | Path, agent_id: str) -> list[PendingApproval]:
    """Return every pending-approval row for ``agent_id``.

    Each row carries a structured diff (via :mod:`amp_ui.diff`) against its
    closest live counterpart. If an approval-pattern row exists that
    matches the (approver-pending, operation=remember, type, keyword)
    tuple, ``auto_approved`` is set so the renderer can flag the row.
    """
    # Import lazily — keeps the services module importable without the
    # diff helper for callers that only use parts of the API.
    from amp_ui.diff import diff_memories

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE agent_id = ? AND deleted_at = ?
            ORDER BY created_at DESC
            """,
            (agent_id, PENDING_SENTINEL),
        ).fetchall()

        patterns = {
            (r["operation"], r["memory_type"], r["keyword"]): r["key"]
            for r in conn.execute(
                "SELECT key, operation, memory_type, keyword FROM approval_patterns "
                "WHERE decision = 'approve'"
            ).fetchall()
        }

        out: list[PendingApproval] = []
        for row in rows:
            pending_dict = _row_dict(row)
            current = _find_current_match(conn, agent_id, row)
            diff = diff_memories(pending_dict, current)

            keyword = _extract_keyword(row["content"])
            pattern_key = patterns.get(("remember", row["type"], keyword))

            out.append(
                PendingApproval(
                    id=row["id"],
                    agent_id=row["agent_id"],
                    user_id=row["user_id"],
                    type=row["type"],
                    content=row["content"],
                    metadata=_parse_json(row["metadata"]),
                    confidence=row["confidence"],
                    source=row["source"],
                    created_at=row["created_at"],
                    diff=diff,
                    auto_approved=pattern_key is not None,
                    auto_pattern_key=pattern_key,
                )
            )
        return out
    finally:
        conn.close()


def approve(
    db_path: str | Path,
    memory_id: str,
    agent_id: str,
    reviewer: str,
    reason: str | None = None,
) -> None:
    """Approve a pending memory: flip ``deleted_at`` to NULL + audit it.

    Strictly scoped to ``agent_id`` and the pending sentinel — any attempt
    to approve a row that is not pending, has been hard-deleted, or
    belongs to a different agent raises :class:`NotPendingError` (a
    :class:`LookupError` subclass) so the route layer can return 404.
    This closes the IDOR where a malicious operator with one agent's UI
    open could approve / resurrect arbitrary rows by guessing memory ids.
    """
    conn = _connect(db_path)
    try:
        now = _now_ms()
        with conn:
            cursor = conn.execute(
                "UPDATE memories SET deleted_at = NULL, updated_at = ? "
                "WHERE id = ? AND agent_id = ? AND deleted_at = ?",
                (now, memory_id, agent_id, PENDING_SENTINEL),
            )
            if cursor.rowcount == 0:
                raise NotPendingError(
                    f"memory {memory_id!r} is not a pending approval for agent {agent_id!r}"
                )
            conn.execute(
                "INSERT INTO audit_log(ts, operation, agent_id, user_id, memory_id, "
                "payload, result, approved_by, approval_at) "
                "VALUES (?, 'remember', ?, "
                "(SELECT user_id FROM memories WHERE id = ? AND agent_id = ?), "
                "?, ?, ?, ?, ?)",
                (
                    now,
                    agent_id,
                    memory_id,
                    agent_id,
                    memory_id,
                    json.dumps({"reason": reason, "action": "approve"}),
                    json.dumps({"approved": True}),
                    reviewer,
                    now,
                ),
            )
    finally:
        conn.close()


def reject(
    db_path: str | Path,
    memory_id: str,
    agent_id: str,
    reviewer: str,
    reason: str | None = None,
) -> None:
    """Reject a pending memory: soft-delete it + audit the reason.

    Strictly scoped to ``agent_id`` and the pending sentinel. See
    :func:`approve` for the security rationale; :class:`NotPendingError`
    raised on any mismatch.
    """
    conn = _connect(db_path)
    try:
        now = _now_ms()
        with conn:
            cursor = conn.execute(
                "UPDATE memories SET deleted_at = ?, updated_at = ? "
                "WHERE id = ? AND agent_id = ? AND deleted_at = ?",
                (now, now, memory_id, agent_id, PENDING_SENTINEL),
            )
            if cursor.rowcount == 0:
                raise NotPendingError(
                    f"memory {memory_id!r} is not a pending approval for agent {agent_id!r}"
                )
            conn.execute(
                "INSERT INTO audit_log(ts, operation, agent_id, user_id, memory_id, "
                "payload, result, approved_by, approval_at) "
                "VALUES (?, 'forget', ?, "
                "(SELECT user_id FROM memories WHERE id = ? AND agent_id = ?), "
                "?, ?, ?, ?, ?)",
                (
                    now,
                    agent_id,
                    memory_id,
                    agent_id,
                    memory_id,
                    json.dumps({"reason": reason, "action": "reject"}),
                    json.dumps({"approved": False}),
                    reviewer,
                    now,
                ),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------


def _audit_where(filters: AuditFilters) -> tuple[str, list[Any]]:
    """Build the WHERE clause for an audit query."""
    clauses: list[str] = []
    params: list[Any] = []
    if filters.operation:
        clauses.append("operation = ?")
        params.append(filters.operation)
    if filters.agent_id:
        clauses.append("agent_id = ?")
        params.append(filters.agent_id)
    if filters.user_id:
        clauses.append("user_id = ?")
        params.append(filters.user_id)
    if filters.memory_id:
        clauses.append("memory_id = ?")
        params.append(filters.memory_id)
    if filters.since_ms is not None:
        clauses.append("ts >= ?")
        params.append(filters.since_ms)
    if filters.until_ms is not None:
        clauses.append("ts <= ?")
        params.append(filters.until_ms)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def audit_query(
    db_path: str | Path,
    filters: AuditFilters,
    *,
    limit: int = DEFAULT_AUDIT_PAGE,
    offset: int = 0,
) -> tuple[list[AuditRow], int]:
    """Paginated audit-log query. Returns ``(rows, total_count)``."""
    where, params = _audit_where(filters)
    conn = _connect(db_path)
    try:
        total_row = conn.execute("SELECT COUNT(*) AS n FROM audit_log" + where, params).fetchone()
        total = int(total_row["n"]) if total_row is not None else 0

        rows = conn.execute(
            "SELECT * FROM audit_log" + where + " ORDER BY ts DESC LIMIT ? OFFSET ?",
            [*params, int(limit), int(offset)],
        ).fetchall()

        out = [
            AuditRow(
                id=int(r["id"]),
                ts=int(r["ts"]),
                operation=r["operation"],
                agent_id=r["agent_id"],
                user_id=r["user_id"],
                memory_id=r["memory_id"],
                payload=_parse_json(r["payload"]) or {},
                result=_parse_json(r["result"]),
                approved_by=r["approved_by"],
                approval_at=int(r["approval_at"]) if r["approval_at"] is not None else None,
            )
            for r in rows
        ]
        return out, total
    finally:
        conn.close()


def audit_export(
    db_path: str | Path,
    filters: AuditFilters,
    fmt: Literal["json", "csv"],
) -> tuple[bytes, str]:
    """Serialise the entire filtered audit log for download.

    Returns ``(payload, content_type)``. Cap defensively at 100k rows so a
    malicious filter cannot exhaust memory.
    """
    rows, _ = audit_query(db_path, filters, limit=100_000, offset=0)
    if fmt == "json":
        body = json.dumps(
            [
                {
                    "id": r.id,
                    "ts": r.ts,
                    "operation": r.operation,
                    "agent_id": r.agent_id,
                    "user_id": r.user_id,
                    "memory_id": r.memory_id,
                    "payload": r.payload,
                    "result": r.result,
                    "approved_by": r.approved_by,
                    "approval_at": r.approval_at,
                }
                for r in rows
            ],
            indent=2,
        ).encode("utf-8")
        return body, "application/json"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "ts",
            "operation",
            "agent_id",
            "user_id",
            "memory_id",
            "payload",
            "result",
            "approved_by",
            "approval_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.ts,
                r.operation,
                r.agent_id or "",
                r.user_id or "",
                r.memory_id or "",
                json.dumps(r.payload, default=str),
                json.dumps(r.result, default=str) if r.result is not None else "",
                r.approved_by or "",
                r.approval_at if r.approval_at is not None else "",
            ]
        )
    return buf.getvalue().encode("utf-8"), "text/csv"


# ---------------------------------------------------------------------------
# Memory Health dashboard
# ---------------------------------------------------------------------------


def health_metrics(db_path: str | Path, agent_id: str) -> HealthMetrics:
    """Compute the four cards on the Memory Health dashboard."""
    conn = _connect(db_path)
    try:
        live_rows = conn.execute(
            "SELECT id, user_id, content, last_recalled_at FROM memories "
            "WHERE agent_id = ? AND deleted_at IS NULL",
            (agent_id,),
        ).fetchall()
        total = len(live_rows)

        now = _now_ms()
        stale_cutoff = now - _STALE_DAYS * 86_400_000
        stale_count = 0
        for r in live_rows:
            last = r["last_recalled_at"]
            if last is None or int(last) < stale_cutoff:
                stale_count += 1
        stale_pct = (100.0 * stale_count / total) if total else 0.0

        # Drift: count contradiction pairs within the same user_id. O(n^2)
        # over a per-user bucket; in practice the agent / user partitions
        # keep n small. Documented as a v0 heuristic — Phase 7 will swap
        # in cosine distance against the real embedder.
        by_user: dict[str, list[sqlite3.Row]] = {}
        for r in live_rows:
            if r["user_id"] is None:
                continue
            by_user.setdefault(r["user_id"], []).append(r)
        drift_pairs = 0
        for bucket in by_user.values():
            for i, a in enumerate(bucket):
                for b in bucket[i + 1 :]:
                    if _jaccard(a["content"], b["content"]) >= _DRIFT_OVERLAP:
                        drift_pairs += 1

        coverage_rows = conn.execute(
            "SELECT type, COUNT(*) AS n FROM memories "
            "WHERE agent_id = ? AND deleted_at IS NULL "
            "GROUP BY type",
            (agent_id,),
        ).fetchall()
        coverage: dict[str, int] = {r["type"]: int(r["n"]) for r in coverage_rows}

        return HealthMetrics(
            total=total,
            stale_count=stale_count,
            stale_pct=stale_pct,
            drift_pairs=drift_pairs,
            coverage_by_type=coverage,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Co-memorize Bulk Review
# ---------------------------------------------------------------------------


def co_memorize_candidates(
    db_path: str | Path, agent_id: str, *, limit: int = 50
) -> list[CoMemCandidate]:
    """Return forget + merge candidates per the heuristic.

    Heuristic (documented):

    * Forget — ``last_recalled_at IS NULL`` AND ``created_at < now - 90d``
      AND ``confidence < 0.5``.
    * Merge — pairs with the same ``user_id`` and token-overlap > 0.7.

    Each candidate carries a deterministic, human-readable reasoning string.
    Capped at ``limit`` total rows (forget first, then merge).
    """
    conn = _connect(db_path)
    try:
        now = _now_ms()
        old_cutoff = now - _FORGET_AGE_DAYS * 86_400_000

        forget_rows = conn.execute(
            """
            SELECT id, content, created_at, confidence
            FROM memories
            WHERE agent_id = ?
              AND deleted_at IS NULL
              AND last_recalled_at IS NULL
              AND created_at < ?
              AND COALESCE(confidence, 1.0) < ?
            ORDER BY created_at ASC
            """,
            (agent_id, old_cutoff, _FORGET_CONFIDENCE_BELOW),
        ).fetchall()

        candidates: list[CoMemCandidate] = []
        for r in forget_rows:
            age_days = max(1, int((now - int(r["created_at"])) / 86_400_000))
            reasoning = (
                f"created {age_days} days ago, never recalled, "
                f"confidence {float(r['confidence'] or 0):.2f}"
            )
            candidates.append(
                CoMemCandidate(
                    op_type="forget",
                    primary_id=r["id"],
                    secondary_id=None,
                    content=r["content"],
                    reasoning=reasoning,
                )
            )

        # Merge pairs — bucketed by user_id, deterministic ordering.
        live = conn.execute(
            "SELECT id, user_id, content FROM memories "
            "WHERE agent_id = ? AND deleted_at IS NULL AND user_id IS NOT NULL "
            "ORDER BY created_at ASC",
            (agent_id,),
        ).fetchall()
        by_user: dict[str, list[sqlite3.Row]] = {}
        for r in live:
            by_user.setdefault(r["user_id"], []).append(r)
        for bucket in by_user.values():
            for i, a in enumerate(bucket):
                for b in bucket[i + 1 :]:
                    overlap = _jaccard(a["content"], b["content"])
                    if overlap >= _MERGE_OVERLAP:
                        candidates.append(
                            CoMemCandidate(
                                op_type="merge",
                                primary_id=a["id"],
                                secondary_id=b["id"],
                                content=f"{a['content']}  ↔  {b['content']}",
                                reasoning=(
                                    f"same user, token-overlap {overlap:.0%} — merge candidates"
                                ),
                            )
                        )

        return candidates[:limit]
    finally:
        conn.close()


def apply_co_memorize(
    db_path: str | Path,
    agent_id: str,
    ops: Iterable[CoMemOp],
    reviewer: str = "co-memorize",
) -> ApplyResult:
    """Apply a list of bulk-review operations, strictly scoped to ``agent_id``.

    * ``forget`` — soft-delete the primary and audit it.
    * ``merge``  — soft-delete the secondary; keep the primary as canonical.

    Every UPDATE includes ``AND agent_id = ?`` so a malicious operator
    cannot pivot from their own UI session to another agent's rows by
    guessing memory ids. If a row is missing, not live, or belongs to a
    different agent, the op is recorded in ``ApplyResult.results[i]``
    with ``skipped=True`` and a human-readable reason — we do *not* raise
    the whole batch, since legitimate races (the row was forgotten by
    another process between page render and apply) look identical to the
    cross-agent case at the SQL layer.
    """
    conn = _connect(db_path)
    applied = 0
    skipped = 0
    errors: list[str] = []
    results: list[ApplyOpResult] = []
    try:
        now = _now_ms()
        for op in ops:
            try:
                with conn:
                    if op.op_type == "forget":
                        cursor = conn.execute(
                            "UPDATE memories SET deleted_at = ?, updated_at = ? "
                            "WHERE id = ? AND agent_id = ? AND deleted_at IS NULL",
                            (now, now, op.primary_id, agent_id),
                        )
                        if cursor.rowcount == 0:
                            skipped += 1
                            results.append(
                                ApplyOpResult(
                                    op_type="forget",
                                    primary_id=op.primary_id,
                                    secondary_id=None,
                                    skipped=True,
                                    reason=("not found, not live, or belongs to a different agent"),
                                )
                            )
                            continue
                        conn.execute(
                            "INSERT INTO audit_log(ts, operation, agent_id, user_id, "
                            "memory_id, payload, result, approved_by, approval_at) "
                            "VALUES (?, 'forget', ?, "
                            "(SELECT user_id FROM memories WHERE id = ? AND agent_id = ?), "
                            "?, ?, ?, ?, ?)",
                            (
                                now,
                                agent_id,
                                op.primary_id,
                                agent_id,
                                op.primary_id,
                                json.dumps({"reason": "co-memorize bulk forget"}),
                                json.dumps({"forgotten_ids": [op.primary_id]}),
                                reviewer,
                                now,
                            ),
                        )
                        applied += 1
                        results.append(
                            ApplyOpResult(
                                op_type="forget",
                                primary_id=op.primary_id,
                                secondary_id=None,
                                skipped=False,
                            )
                        )

                    elif op.op_type == "merge":
                        if not op.secondary_id:
                            skipped += 1
                            results.append(
                                ApplyOpResult(
                                    op_type="merge",
                                    primary_id=op.primary_id,
                                    secondary_id=None,
                                    skipped=True,
                                    reason="merge op missing secondary_id",
                                )
                            )
                            continue
                        # Verify the canonical (primary) also belongs to this
                        # agent. Otherwise an attacker could resolve their own
                        # primary against another agent's secondary, exfiltrating
                        # the relationship via the audit log.
                        primary_row = conn.execute(
                            "SELECT 1 FROM memories WHERE id = ? AND agent_id = ?",
                            (op.primary_id, agent_id),
                        ).fetchone()
                        if primary_row is None:
                            skipped += 1
                            results.append(
                                ApplyOpResult(
                                    op_type="merge",
                                    primary_id=op.primary_id,
                                    secondary_id=op.secondary_id,
                                    skipped=True,
                                    reason="primary not found for this agent",
                                )
                            )
                            continue
                        cursor = conn.execute(
                            "UPDATE memories SET deleted_at = ?, updated_at = ? "
                            "WHERE id = ? AND agent_id = ? AND deleted_at IS NULL",
                            (now, now, op.secondary_id, agent_id),
                        )
                        if cursor.rowcount == 0:
                            skipped += 1
                            results.append(
                                ApplyOpResult(
                                    op_type="merge",
                                    primary_id=op.primary_id,
                                    secondary_id=op.secondary_id,
                                    skipped=True,
                                    reason=(
                                        "secondary not found, not live, or belongs to a "
                                        "different agent"
                                    ),
                                )
                            )
                            continue
                        conn.execute(
                            "INSERT INTO audit_log(ts, operation, agent_id, user_id, "
                            "memory_id, payload, result, approved_by, approval_at) "
                            "VALUES (?, 'merge', ?, "
                            "(SELECT user_id FROM memories WHERE id = ? AND agent_id = ?), "
                            "?, ?, ?, ?, ?)",
                            (
                                now,
                                agent_id,
                                op.primary_id,
                                agent_id,
                                op.primary_id,
                                json.dumps(
                                    {
                                        "canonical": op.primary_id,
                                        "duplicates": [op.secondary_id],
                                        "reason": "co-memorize bulk merge",
                                    }
                                ),
                                json.dumps({"merged_count": 1}),
                                reviewer,
                                now,
                            ),
                        )
                        applied += 1
                        results.append(
                            ApplyOpResult(
                                op_type="merge",
                                primary_id=op.primary_id,
                                secondary_id=op.secondary_id,
                                skipped=False,
                            )
                        )
                    else:
                        # Unreachable per CoMemOp's Literal type, but keep a
                        # defensive branch in case a future op_type is added
                        # without updating this dispatch.
                        skipped += 1
                        results.append(
                            ApplyOpResult(
                                op_type=op.op_type,
                                primary_id=op.primary_id,
                                secondary_id=op.secondary_id,
                                skipped=True,
                                reason=f"unknown op_type {op.op_type!r}",
                            )
                        )
            except sqlite3.Error as exc:
                errors.append(f"{op.op_type} {op.primary_id}: {exc}")

        return ApplyResult(applied=applied, skipped=skipped, errors=errors, results=results)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Approval Patterns
# ---------------------------------------------------------------------------


def _make_pattern_key(approver: str, operation: str, memory_type: str, keyword: str) -> str:
    """Stable key for an (approver, operation, type, keyword) cluster."""
    raw = "|".join([approver, operation, memory_type, keyword])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def pattern_recommendations(
    db_path: str | Path,
    agent_id: str,
    *,
    threshold: int = DEFAULT_PATTERN_THRESHOLD,
) -> list[PatternReco]:
    """Cluster audit-log approval decisions and surface candidates.

    A cluster is keyed on (approver, operation, memory_type, keyword). The
    keyword is extracted from the memory's content. Only clusters that
    have at least ``threshold`` matching rows surface as recommendations.

    Already-accepted clusters appear with ``accepted = True`` so the UI
    can render them in a separate state.
    """
    conn = _connect(db_path)
    try:
        # Pull approvals (audit_log rows with an approver) joined to the
        # underlying memory so we know the type + content. We tolerate
        # joins that miss (hard-deleted memories) — those rows are simply
        # skipped.
        rows = conn.execute(
            """
            SELECT a.operation, a.approved_by, a.payload, a.result,
                   m.type, m.content
            FROM audit_log a
            LEFT JOIN memories m ON m.id = a.memory_id
            WHERE a.agent_id = ?
              AND a.approved_by IS NOT NULL
              AND a.memory_id IS NOT NULL
              AND m.type IS NOT NULL
            """,
            (agent_id,),
        ).fetchall()

        ClusterKey = tuple[str, str, str, str, Literal["approve", "reject"]]
        clusters: dict[ClusterKey, int] = {}
        for r in rows:
            approver = r["approved_by"]
            operation = r["operation"]
            memory_type = r["type"]
            keyword = _extract_keyword(r["content"] or "")
            if not keyword:
                continue
            result = _parse_json(r["result"]) or {}
            payload = _parse_json(r["payload"]) or {}
            # "approve" if the operation was a remember accept; "reject" if
            # the audit payload action is reject OR the operation is forget
            # invoked by an approver.
            decision: Literal["approve", "reject"]
            if operation == "remember":
                decision = "approve"
            elif (operation == "forget" and payload.get("action") == "reject") or result.get(
                "approved"
            ) is False:
                decision = "reject"
            else:
                continue
            cluster_key: ClusterKey = (approver, operation, memory_type, keyword, decision)
            clusters[cluster_key] = clusters.get(cluster_key, 0) + 1

        accepted = {
            r["key"] for r in conn.execute("SELECT key FROM approval_patterns WHERE 1=1").fetchall()
        }

        recos: list[PatternReco] = []
        for (
            c_approver,
            c_operation,
            c_memory_type,
            c_keyword,
            c_decision,
        ), count in clusters.items():
            if count < threshold:
                continue
            reco_key = _make_pattern_key(c_approver, c_operation, c_memory_type, c_keyword)
            recos.append(
                PatternReco(
                    key=reco_key,
                    approver=c_approver,
                    operation=c_operation,
                    memory_type=c_memory_type,
                    keyword=c_keyword,
                    decision=c_decision,
                    count=count,
                    accepted=reco_key in accepted,
                )
            )
        recos.sort(key=lambda r: (-r.count, r.approver, r.keyword))
        return recos
    finally:
        conn.close()


def accept_pattern(
    db_path: str | Path,
    pattern_key: str,
    *,
    agent_id: str,
    reviewer: str,
    threshold: int = DEFAULT_PATTERN_THRESHOLD,
) -> bool:
    """Persist a recommendation as an active auto-allow rule.

    Returns ``True`` if a new row was inserted, ``False`` if the pattern
    was already accepted or could not be matched against the current
    recommendation set. The match is intentionally tight — we never let
    a caller fabricate a pattern_key that isn't actually backed by audit
    signal.
    """
    recos = pattern_recommendations(db_path, agent_id, threshold=threshold)
    target = next((r for r in recos if r.key == pattern_key), None)
    if target is None or target.accepted:
        return False

    conn = _connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO approval_patterns
                (key, approver, operation, memory_type, keyword, decision, accepted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target.key,
                    target.approver,
                    target.operation,
                    target.memory_type,
                    target.keyword,
                    target.decision,
                    _now_ms(),
                ),
            )
            # Best-effort audit so the acceptance shows up on the audit page.
            conn.execute(
                "INSERT INTO audit_log(ts, operation, agent_id, user_id, memory_id, "
                "payload, result, approved_by, approval_at) "
                "VALUES (?, 'pattern.accept', ?, NULL, NULL, ?, ?, ?, ?)",
                (
                    _now_ms(),
                    agent_id,
                    json.dumps(
                        {
                            "key": target.key,
                            "approver": target.approver,
                            "operation": target.operation,
                            "memory_type": target.memory_type,
                            "keyword": target.keyword,
                            "decision": target.decision,
                        }
                    ),
                    json.dumps({"accepted": True}),
                    reviewer,
                    _now_ms(),
                ),
            )
        return True
    finally:
        conn.close()


__all__ = [
    "DEFAULT_AUDIT_PAGE",
    "DEFAULT_PATTERN_THRESHOLD",
    "PENDING_SENTINEL",
    "ApplyOpResult",
    "ApplyResult",
    "AuditFilters",
    "AuditRow",
    "CoMemCandidate",
    "CoMemOp",
    "HealthMetrics",
    "NotPendingError",
    "PatternReco",
    "PendingApproval",
    "accept_pattern",
    "apply_co_memorize",
    "approve",
    "audit_export",
    "audit_query",
    "co_memorize_candidates",
    "ensure_schema",
    "health_metrics",
    "list_pending",
    "pattern_recommendations",
    "reject",
]
