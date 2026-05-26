"""SQLite + ``sqlite-vec`` reference :class:`MemoryStore` adapter.

This adapter is the default local backend for the AMP reference
implementation. It implements every operation in the
:class:`amp.store.MemoryStore` Protocol on top of a single SQLite database
extended with the ``vec0`` virtual table (sqlite-vec) for ANN search and
FTS5 for keyword search.

Design notes
------------
* The canonical storage shape is defined in :file:`docs/kickoff/ARCHITECTURE.md`
  §3. This module implements that shape with one deliberate dimension change:
  the kickoff document writes ``float[768]`` but the default embedder ships
  here is ``sentence-transformers/all-MiniLM-L6-v2``, which produces 384-d
  vectors. Constructor's ``embedding_dim`` parameter overrides the default if
  you wire a different embedder.
* The store is composed of three tables that share rowids:
  ``memories`` (the canonical row), ``memories_vec`` (vec0 ANN), and
  ``memories_fts`` (FTS5 keyword). vec0 cannot be a content-table follower
  the way FTS5 can — we manage its rows by hand. FTS5 *is* set up as a
  content-following virtual table on ``memories``.
* SQLite is fundamentally synchronous; the Protocol is async. We wrap every
  blocking call in :func:`anyio.to_thread.run_sync` so the adapter is safe
  to use from an async event loop.
* The default embedder is lazy-loaded from sentence-transformers on first
  use. Unit tests inject a fake embedder via the constructor to avoid
  pulling the model into CI.
* ID generation uses :func:`uuid.uuid4` (hex). Python 3.14 will add
  :func:`uuid.uuid7` which is more appropriate for time-ordered keys — the
  switch is tracked but deferred until 3.14 is the floor (current floor is
  3.11). Recorded as a spec-gap deviation per spec section 2.
* RRF is the intra-store fusion algorithm for v0; the router (Phase 4) does
  the inter-store fusion separately.

Schema deviations from the kickoff document (each minor, each documented):

* ``memories.last_recalled_at`` column added — required to honor
  ``expire(policy={"no_recall_in_days": ...})`` and to satisfy the
  :attr:`amp.store.Capability.RECALL_TRACKING` claim.
* ``embedding float[384]`` rather than ``float[768]``; the dim is a
  constructor parameter so backends with a different model can override.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, Final
from urllib.parse import urlparse

import anyio.to_thread
import sqlite_vec

from amp.models import (
    ExpireAction,
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    ForgetStoreResult,
    FusionAlgorithm,
    MemoryType,
    MergeRequest,
    MergeResponse,
    MergeStrategy,
    RecallHit,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)
from amp.store.base import Capability

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKEND_NAME = "sqlite-vec"
SCHEMA_VERSION = 1
# Reciprocal Rank Fusion constant (spec section 5).
RRF_K = 60
# Sentinel marker stored in ``deleted_at`` for memories that are awaiting
# governance approval and so MUST NOT appear in recall. Distinct from a
# normal soft-delete timestamp; chosen well outside any plausible Unix-ms.
PENDING_APPROVAL_DELETED_AT: Final[int] = -1
"""Public sentinel value stored in ``memories.deleted_at`` to mark a row that
is awaiting governance approval (i.e. written via ``remember(approval_required=True)``).

Governance UIs and other downstream consumers should import this rather than
hard-coding ``-1``. The OSS adapter treats the value as an invariant of the
storage contract — any change here must bump :data:`SCHEMA_VERSION`.
"""
# Backwards-compat alias for the previously private name; existing call sites
# inside this module still use the underscore form. Keep the alias so any
# external import (tests, downstream forks) does not break.
_PENDING_APPROVAL_DELETED_AT = PENDING_APPROVAL_DELETED_AT
# Default embedding dimension (sentence-transformers/all-MiniLM-L6-v2).
DEFAULT_EMBEDDING_DIM = 384

EmbedderFn = Callable[[str], list[float]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    """Return the current Unix time in milliseconds (AMP timestamp format)."""
    return int(time.time() * 1000)


def _fts_quote(query: str) -> str:
    """Wrap an arbitrary user query for safe use inside an FTS5 MATCH clause.

    FTS5 has its own query syntax (NEAR, AND, OR, column filters, …). Users
    pass natural language; we wrap each token in double quotes and join with
    space (implicit AND). Empty / whitespace-only strings return a literal
    no-match token so the SQL does not error.
    """
    tokens = [tok for tok in query.split() if tok.strip()]
    if not tokens:
        # FTS5 rejects an empty MATCH expression. Use a token that cannot
        # appear in any indexed content (control char) so the query is
        # well-formed and matches nothing.
        return '"\x01"'
    # Strip embedded double quotes from each token and wrap in quotes; FTS5
    # treats a quoted token as a literal phrase.
    return " ".join(f'"{tok.replace(chr(34), "")}"' for tok in tokens)


def _row_to_hit(row: sqlite3.Row, score: float) -> RecallHit:
    """Convert a ``memories`` row + a score into a :class:`RecallHit`."""
    metadata_raw = row["metadata"]
    metadata: dict[str, Any] | None
    if metadata_raw:
        loaded = json.loads(metadata_raw)
        metadata = loaded if isinstance(loaded, dict) else None
    else:
        metadata = None
    return RecallHit(
        id=row["id"],
        type=MemoryType(row["type"]),
        content=row["content"],
        score=score,
        metadata=metadata,
        created_at=row["created_at"],
        supporting=[],
        source_store=BACKEND_NAME,
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class SqliteVecStore:
    """SQLite + sqlite-vec reference adapter implementing :class:`MemoryStore`.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database file, or ``":memory:"`` for an
        ephemeral in-memory store. Defaults to ``":memory:"`` so unit tests
        can construct one without filesystem setup.
    embedding_dim:
        Vector length the embedder produces. Defaults to 384 to match
        sentence-transformers' all-MiniLM-L6-v2.
    embedder:
        Optional ``text -> list[float]`` function. If ``None``, the default
        sentence-transformers model is lazy-loaded on first use.
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        embedder: EmbedderFn | None = None,
    ) -> None:
        self.db_path: str = ":memory:" if str(db_path) == ":memory:" else str(Path(db_path))
        self._embedding_dim: int = int(embedding_dim)
        self._embedder_override: EmbedderFn | None = embedder
        self._lazy_embedder: EmbedderFn | None = None

        self._conn: sqlite3.Connection = sqlite3.connect(
            self.db_path,
            isolation_level=None,  # autocommit; we wrap mutations in BEGIN/COMMIT
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        # Loading further extensions on this connection is a footgun for users;
        # re-disable now that vec0 is in.
        self._conn.enable_load_extension(False)

        # WAL gives concurrent readers + one writer at the same time. Not
        # supported for :memory: dbs (silently kept as "memory" journal mode).
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")

        self._init_schema()

    # ------------------------------------------------------------------
    # URL form
    # ------------------------------------------------------------------

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        embedder: EmbedderFn | None = None,
    ) -> SqliteVecStore:
        """Construct a store from a ``sqlite-vec://...`` URL.

        Examples
        --------
        ``sqlite-vec://:memory:`` -> in-memory.
        ``sqlite-vec://./mem.db`` -> relative file path.
        ``sqlite-vec:///absolute/path/mem.db`` -> absolute file path.
        """
        parsed = urlparse(url)
        if parsed.scheme not in {"sqlite-vec", "sqlite+vec", "sqlitevec"}:
            raise ValueError(f"sqlite-vec URL must start with 'sqlite-vec://', got: {url!r}")
        # Reassemble host + path so ``sqlite-vec://./mem.db`` (host=".", path="/mem.db")
        # and ``sqlite-vec:///abs.db`` (host="", path="/abs.db") both round-trip.
        netloc = parsed.netloc
        path = parsed.path
        if netloc == ":memory:" or path == ":memory:":
            db_path: str = ":memory:"
        elif netloc and path:
            db_path = f"{netloc}{path}"
        elif netloc:
            db_path = netloc
        else:
            # leading "///abs.db" form yields netloc="" path="/abs.db"
            db_path = path
        return cls(db_path, embedding_dim=embedding_dim, embedder=embedder)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> SqliteVecStore:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection. Idempotent."""
        # A second close() raises ProgrammingError; swallow it for ergonomics.
        with contextlib.suppress(sqlite3.ProgrammingError):
            self._conn.close()

    # ------------------------------------------------------------------
    # Embedder
    # ------------------------------------------------------------------

    def _get_embedder(self) -> EmbedderFn:
        """Return the embedder, loading the default model on first use."""
        if self._embedder_override is not None:
            return self._embedder_override
        if self._lazy_embedder is not None:
            return self._lazy_embedder

        # Lazy import — sentence-transformers is an optional dependency. The
        # try/except gives a more actionable error than ImportError.
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised by integration
            raise RuntimeError(
                "SqliteVecStore default embedder requires sentence-transformers. "
                "Install with `pip install 'agent-memory-protocol[sqlite-vec]'` "
                "or pass an explicit `embedder=` callable to the constructor."
            ) from exc

        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

        def _encode(text: str) -> list[float]:
            vec = model.encode(text, normalize_embeddings=True)
            return [float(x) for x in vec]

        self._lazy_embedder = _encode
        return _encode

    def _embed(self, text: str) -> list[float]:
        vec = self._get_embedder()(text)
        if len(vec) != self._embedding_dim:
            raise ValueError(
                f"embedder returned {len(vec)}-dim vector, expected {self._embedding_dim}-dim"
            )
        return vec

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Create the AMP storage schema if it does not already exist."""
        ddl = [
            # Canonical memories table — ARCHITECTURE.md §3 with the addition
            # of ``last_recalled_at`` for the recall_tracking capability.
            """
            CREATE TABLE IF NOT EXISTS memories (
              id                TEXT PRIMARY KEY,
              agent_id          TEXT NOT NULL,
              user_id           TEXT,
              type              TEXT NOT NULL
                                  CHECK (type IN ('semantic','episodic','procedural','emotional')),
              content           TEXT NOT NULL,
              metadata          TEXT,
              confidence        REAL DEFAULT 1.0,
              source            TEXT,
              created_at        INTEGER NOT NULL,
              updated_at        INTEGER NOT NULL,
              expires_at        INTEGER,
              deleted_at        INTEGER,
              last_recalled_at  INTEGER
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id, type)",
            "CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)",
            # FTS5 over content. content='memories' content_rowid='rowid' lets
            # us push rows in directly with INSERT INTO memories_fts(rowid,
            # content) ... SELECT against memories.
            (
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5("
                "content, content='memories', content_rowid='rowid')"
            ),
            # vec0 ANN table — its rowid matches memories.rowid.
            (
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0("
                f"embedding float[{self._embedding_dim}])"
            ),
            # Procedures: FSM JSON blobs (ARCHITECTURE.md §3).
            """
            CREATE TABLE IF NOT EXISTS procedures (
              id          TEXT PRIMARY KEY,
              agent_id    TEXT NOT NULL,
              name        TEXT NOT NULL,
              states      TEXT NOT NULL,
              current     TEXT,
              metadata    TEXT,
              created_at  INTEGER NOT NULL,
              updated_at  INTEGER NOT NULL
            )
            """,
            # Episodes (bounded sequences of memories).
            """
            CREATE TABLE IF NOT EXISTS episodes (
              id          TEXT PRIMARY KEY,
              agent_id    TEXT NOT NULL,
              title       TEXT,
              started_at  INTEGER NOT NULL,
              ended_at    INTEGER,
              memory_ids  TEXT NOT NULL
            )
            """,
            # Append-only audit log.
            """
            CREATE TABLE IF NOT EXISTS audit_log (
              id           INTEGER PRIMARY KEY AUTOINCREMENT,
              ts           INTEGER NOT NULL,
              operation    TEXT NOT NULL,
              agent_id     TEXT,
              user_id      TEXT,
              memory_id    TEXT,
              payload      TEXT NOT NULL,
              result       TEXT,
              approved_by  TEXT,
              approval_at  INTEGER
            )
            """,
        ]
        with self._conn:
            for stmt in ddl:
                self._conn.execute(stmt)

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _audit(
        self,
        operation: str,
        *,
        agent_id: str | None,
        user_id: str | None,
        memory_id: str | None,
        payload: Mapping[str, Any] | dict[str, Any],
        result: Mapping[str, Any] | dict[str, Any] | None = None,
    ) -> None:
        """Append a row to ``audit_log``. Best-effort, no exception escape."""
        self._conn.execute(
            "INSERT INTO audit_log(ts, operation, agent_id, user_id, memory_id, payload, result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _now_ms(),
                operation,
                agent_id,
                user_id,
                memory_id,
                json.dumps(payload, default=str),
                json.dumps(result, default=str) if result is not None else None,
            ),
        )

    # ------------------------------------------------------------------
    # remember
    # ------------------------------------------------------------------

    async def remember(self, req: RememberRequest) -> RememberResponse:
        return await anyio.to_thread.run_sync(self._remember_sync, req)

    def _remember_sync(self, req: RememberRequest) -> RememberResponse:
        memory_id = uuid.uuid4().hex
        stored_at = _now_ms()
        approval_required = bool(req.approval_required)
        # Pending-approval rows are written but hidden from recall via the
        # ``_PENDING_APPROVAL_DELETED_AT`` sentinel. Phase 6 will surface them
        # for HITL review.
        deleted_at = _PENDING_APPROVAL_DELETED_AT if approval_required else None
        stores = [] if approval_required else [BACKEND_NAME]

        embedding = self._embed(req.content)
        embedding_blob = sqlite_vec.serialize_float32(embedding)
        metadata_json = json.dumps(req.metadata) if req.metadata is not None else None
        confidence = req.confidence if req.confidence is not None else 1.0

        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO memories(
                    id, agent_id, user_id, type, content, metadata,
                    confidence, source, created_at, updated_at,
                    expires_at, deleted_at, last_recalled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    memory_id,
                    req.agent_id,
                    req.user_id,
                    req.type.value,
                    req.content,
                    metadata_json,
                    confidence,
                    req.source,
                    stored_at,
                    stored_at,
                    req.expires_at,
                    deleted_at,
                ),
            )
            rowid = cursor.lastrowid
            self._conn.execute(
                "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                (rowid, embedding_blob),
            )
            self._conn.execute(
                "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
                (rowid, req.content),
            )

            # Procedural side-table: keep one row per procedural memory using
            # the same id, parsed from the JSON-stringified FSM in ``content``.
            if req.type is MemoryType.PROCEDURAL:
                fsm = self._parse_fsm(req.content)
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO procedures(
                        id, agent_id, name, states, current, metadata,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        req.agent_id,
                        str(fsm.get("name", memory_id)),
                        json.dumps(fsm),
                        fsm.get("current"),
                        metadata_json,
                        stored_at,
                        stored_at,
                    ),
                )

            self._audit(
                "remember",
                agent_id=req.agent_id,
                user_id=req.user_id,
                memory_id=memory_id,
                payload=req.model_dump(mode="json", exclude_none=True),
                result={"id": memory_id, "pending_approval": approval_required},
            )

        return RememberResponse(
            id=memory_id,
            stored_at=stored_at,
            stores=stores,
            pending_approval=approval_required,
            approval_url=None,
        )

    @staticmethod
    def _parse_fsm(content: str) -> dict[str, Any]:
        """Best-effort decode of a procedural memory's content as an FSM dict.

        We accept any well-formed JSON object; full schema validation happens
        in :class:`amp.models.ProcedureSpec`. Non-object payloads still get a
        ``procedures`` row so callers can debug, with ``states='{}'`` so the
        column remains valid JSON.
        """
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return {}
        if not isinstance(decoded, dict):
            return {}
        return decoded

    # ------------------------------------------------------------------
    # recall
    # ------------------------------------------------------------------

    async def recall(self, req: RecallRequest) -> RecallResponse:
        return await anyio.to_thread.run_sync(self._recall_sync, req)

    def _recall_sync(self, req: RecallRequest) -> RecallResponse:
        started_ms = _now_ms()
        k = req.k if req.k is not None else 5
        # Pull a wider candidate set per source so RRF has rows to fuse.
        candidate_k = max(k * 4, 20)

        where_sql, where_params = self._build_recall_filter(req)

        # Vector ANN candidates.
        query_vec = self._embed(req.query)
        vec_rows = list(
            self._conn.execute(
                "SELECT rowid, distance FROM memories_vec "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (sqlite_vec.serialize_float32(query_vec), candidate_k),
            )
        )

        # FTS keyword candidates.
        fts_query = _fts_quote(req.query)
        fts_rows = list(
            self._conn.execute(
                "SELECT rowid, rank FROM memories_fts "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, candidate_k),
            )
        )

        # Intra-store RRF fusion.
        fused_scores: dict[int, float] = {}
        for rank, row in enumerate(vec_rows):
            fused_scores[int(row["rowid"])] = fused_scores.get(int(row["rowid"]), 0.0) + 1.0 / (
                RRF_K + rank
            )
        for rank, row in enumerate(fts_rows):
            fused_scores[int(row["rowid"])] = fused_scores.get(int(row["rowid"]), 0.0) + 1.0 / (
                RRF_K + rank
            )

        if not fused_scores:
            self._audit(
                "recall",
                agent_id=req.agent_id,
                user_id=req.user_id,
                memory_id=None,
                payload=req.model_dump(mode="json", exclude_none=True),
                result={"matched": 0},
            )
            return RecallResponse(
                results=[],
                fusion_used=req.fusion if req.fusion is not None else FusionAlgorithm.RRF,
                stores_queried=[BACKEND_NAME],
                latency_ms=max(_now_ms() - started_ms, 0),
            )

        # Pull full rows for the candidates that match the where-clause.
        rowid_list = list(fused_scores.keys())
        placeholders = ",".join("?" * len(rowid_list))
        sql = (
            "SELECT rowid AS rowid, id, agent_id, user_id, type, content, metadata, "
            "       confidence, source, created_at, updated_at, expires_at "
            "FROM memories WHERE rowid IN (" + placeholders + ") AND " + where_sql
        )
        params: list[Any] = [*rowid_list, *where_params]
        full_rows = list(self._conn.execute(sql, params))

        # Build, sort, truncate.
        hits = [_row_to_hit(row, fused_scores[row["rowid"]]) for row in full_rows]
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:k]

        # Update last_recalled_at for the rows we surfaced. Best-effort —
        # never fail the recall on a tracker write.
        if hits:
            now = _now_ms()
            self._conn.executemany(
                "UPDATE memories SET last_recalled_at = ? WHERE id = ?",
                [(now, hit.id) for hit in hits],
            )

        self._audit(
            "recall",
            agent_id=req.agent_id,
            user_id=req.user_id,
            memory_id=None,
            payload=req.model_dump(mode="json", exclude_none=True),
            result={"matched": len(hits)},
        )

        return RecallResponse(
            results=hits,
            fusion_used=req.fusion if req.fusion is not None else FusionAlgorithm.RRF,
            stores_queried=[BACKEND_NAME],
            latency_ms=max(_now_ms() - started_ms, 0),
        )

    def _build_recall_filter(self, req: RecallRequest) -> tuple[str, list[Any]]:
        """Return ``(where_sql, params)`` for the non-rowid part of recall.

        Includes the agent scope, optional user scope, type filter, freshness
        window, the ``deleted_at IS NULL`` rule (which also hides pending
        approvals), and any flat ``filter`` keys.
        """
        clauses: list[str] = ["agent_id = ?", "deleted_at IS NULL"]
        params: list[Any] = [req.agent_id]

        if req.user_id is not None:
            clauses.append("user_id = ?")
            params.append(req.user_id)

        if req.types:
            placeholders = ",".join("?" * len(req.types))
            clauses.append(f"type IN ({placeholders})")
            params.extend(t.value for t in req.types)

        if req.fresher_than_days is not None:
            cutoff_ms = _now_ms() - int(req.fresher_than_days) * 86_400_000
            clauses.append("created_at >= ?")
            params.append(cutoff_ms)

        if req.filter:
            filter_sql, filter_params = self._filter_clause(req.filter)
            if filter_sql:
                clauses.append(filter_sql)
                params.extend(filter_params)

        return " AND ".join(clauses), params

    # ------------------------------------------------------------------
    # forget
    # ------------------------------------------------------------------

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        return await anyio.to_thread.run_sync(self._forget_sync, req)

    def _forget_sync(self, req: ForgetRequest) -> ForgetResponse:
        if not req.ids and not req.filter:
            # Spec section 3.3 Editor's note: refuse no-scope mass delete.
            raise ValueError("forget requires `ids` or `filter`")

        target_ids: list[str] = []
        if req.ids:
            placeholders = ",".join("?" * len(req.ids))
            rows = self._conn.execute(
                f"SELECT id FROM memories WHERE agent_id = ? AND id IN ({placeholders}) "
                "AND deleted_at IS NULL",
                (req.agent_id, *req.ids),
            )
            target_ids.extend(r["id"] for r in rows)

        if req.filter:
            filter_sql, filter_params = self._filter_clause(req.filter)
            base_sql = "SELECT id FROM memories WHERE agent_id = ? AND deleted_at IS NULL"
            if filter_sql:
                base_sql = base_sql + " AND " + filter_sql
            params: list[Any] = [req.agent_id, *filter_params]
            for r in self._conn.execute(base_sql, params):
                if r["id"] not in target_ids:
                    target_ids.append(r["id"])

        hard = bool(req.hard_delete)
        now = _now_ms()

        with self._conn:
            if target_ids:
                placeholders = ",".join("?" * len(target_ids))
                # Resolve rowids before deletes for vec/fts maintenance.
                rowids = [
                    int(r["rowid"])
                    for r in self._conn.execute(
                        f"SELECT rowid FROM memories WHERE id IN ({placeholders})",
                        target_ids,
                    )
                ]
                if hard:
                    self._conn.execute(
                        f"DELETE FROM memories WHERE id IN ({placeholders})",
                        target_ids,
                    )
                    for rowid in rowids:
                        self._conn.execute("DELETE FROM memories_vec WHERE rowid = ?", (rowid,))
                        self._conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (rowid,))
                else:
                    self._conn.execute(
                        f"UPDATE memories SET deleted_at = ?, updated_at = ? "
                        f"WHERE id IN ({placeholders})",
                        (now, now, *target_ids),
                    )

            self._audit(
                "forget",
                agent_id=req.agent_id,
                user_id=req.user_id,
                memory_id=None,
                payload=req.model_dump(mode="json", exclude_none=True),
                result={
                    "forgotten_ids": target_ids,
                    "hard_delete": hard,
                    "reason": req.reason,
                },
            )

        return ForgetResponse(
            forgotten_ids=target_ids,
            hard_delete=hard,
            stores=[ForgetStoreResult(store=BACKEND_NAME, count=len(target_ids))],
            pending_approval=False,
            approval_url=None,
        )

    # ------------------------------------------------------------------
    # merge
    # ------------------------------------------------------------------

    async def merge(self, req: MergeRequest) -> MergeResponse:
        return await anyio.to_thread.run_sync(self._merge_sync, req)

    def _merge_sync(self, req: MergeRequest) -> MergeResponse:
        """Collapse duplicates into the canonical row.

        Entity resolution (adapter-specific choice, documented):
        the canonical and duplicate strings may be either AMP memory ids or
        ``metadata.entity_name`` values. We resolve both sides by trying
        each interpretation in turn; the first non-empty match wins. Spec
        section 3.4 leaves this open for v0; v0.2 will tighten.
        """
        strategy = req.strategy if req.strategy is not None else MergeStrategy.KEEP_CANONICAL

        canonical_rows = self._resolve_entity(req.agent_id, req.canonical)
        duplicate_rows: list[sqlite3.Row] = []
        for dup_key in req.duplicates:
            duplicate_rows.extend(self._resolve_entity(req.agent_id, dup_key))

        # Drop any duplicate-side rows that already coincide with the canonical row.
        canonical_ids = {row["id"] for row in canonical_rows}
        duplicate_rows = [r for r in duplicate_rows if r["id"] not in canonical_ids]

        if not canonical_rows and not duplicate_rows:
            return MergeResponse(
                canonical=req.canonical,
                merged_count=0,
                strategy_used=strategy,
                stores=[BACKEND_NAME],
            )

        now = _now_ms()
        merged_count = 0

        with self._conn:
            if strategy is MergeStrategy.KEEP_CANONICAL:
                merged_count = self._soft_delete_rows(duplicate_rows, now)

            elif strategy is MergeStrategy.KEEP_HIGHEST_CONFIDENCE:
                all_rows = canonical_rows + duplicate_rows
                if all_rows:
                    winner = max(
                        all_rows,
                        key=lambda r: (
                            r["confidence"] if r["confidence"] is not None else -1.0,
                            -(r["created_at"] or 0),  # older wins tie
                        ),
                    )
                    losers = [r for r in all_rows if r["id"] != winner["id"]]
                    merged_count = self._soft_delete_rows(losers, now)

            elif strategy is MergeStrategy.MERGE_CONTENT:
                # Pick a survivor: prefer a row that resolved as canonical;
                # fall back to the highest-confidence duplicate so merge_content
                # still works when the caller addresses everything by entity_name.
                survivors = canonical_rows or duplicate_rows
                survivor = max(
                    survivors,
                    key=lambda r: (
                        r["confidence"] if r["confidence"] is not None else -1.0,
                        -(r["created_at"] or 0),
                    ),
                )
                losers = [r for r in (canonical_rows + duplicate_rows) if r["id"] != survivor["id"]]

                contents: list[str] = [survivor["content"]]
                merged_metadata: dict[str, Any] = {}
                if survivor["metadata"]:
                    try:
                        loaded = json.loads(survivor["metadata"])
                        if isinstance(loaded, dict):
                            merged_metadata.update(loaded)
                    except json.JSONDecodeError:
                        pass
                best_confidence = survivor["confidence"] or 0.0

                # Sort losers by created_at asc so last-write-wins (spec §3.4)
                # corresponds to the newest contributor.
                for row in sorted(losers, key=lambda r: r["created_at"] or 0):
                    contents.append(row["content"])
                    if row["metadata"]:
                        try:
                            loaded = json.loads(row["metadata"])
                            if isinstance(loaded, dict):
                                merged_metadata.update(loaded)
                        except json.JSONDecodeError:
                            pass
                    if (row["confidence"] or 0.0) > best_confidence:
                        best_confidence = row["confidence"] or 0.0

                merged_content = " | ".join(contents)
                self._conn.execute(
                    "UPDATE memories SET content = ?, metadata = ?, confidence = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        merged_content,
                        json.dumps(merged_metadata) if merged_metadata else None,
                        best_confidence,
                        now,
                        survivor["id"],
                    ),
                )
                # Re-sync the FTS row so future keyword searches hit the merged content.
                self._conn.execute(
                    "INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', ?, ?)",
                    (survivor["rowid"], survivor["content"]),
                )
                self._conn.execute(
                    "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
                    (survivor["rowid"], merged_content),
                )
                merged_count = self._soft_delete_rows(losers, now)

            self._audit(
                "merge",
                agent_id=req.agent_id,
                user_id=None,
                memory_id=req.canonical,
                payload=req.model_dump(mode="json", exclude_none=True),
                result={"merged_count": merged_count, "strategy_used": strategy.value},
            )

        return MergeResponse(
            canonical=req.canonical,
            merged_count=merged_count,
            strategy_used=strategy,
            stores=[BACKEND_NAME],
        )

    def _resolve_entity(self, agent_id: str, key: str) -> list[sqlite3.Row]:
        """Resolve a merge entity key to memory rows.

        Tries (a) exact id match and (b) ``metadata.entity_name`` match. We
        deliberately do not match on raw substrings — that would be too loose
        for a destructive operation.
        """
        rows = list(
            self._conn.execute(
                "SELECT rowid, * FROM memories "
                "WHERE agent_id = ? AND id = ? AND deleted_at IS NULL",
                (agent_id, key),
            )
        )
        if rows:
            return rows
        return list(
            self._conn.execute(
                "SELECT rowid, * FROM memories "
                "WHERE agent_id = ? AND deleted_at IS NULL "
                "AND json_extract(metadata, '$.entity_name') = ?",
                (agent_id, key),
            )
        )

    def _soft_delete_rows(self, rows: Iterable[sqlite3.Row], now: int) -> int:
        ids = [row["id"] for row in rows]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        self._conn.execute(
            f"UPDATE memories SET deleted_at = ?, updated_at = ? WHERE id IN ({placeholders})",
            (now, now, *ids),
        )
        return len(ids)

    # ------------------------------------------------------------------
    # expire
    # ------------------------------------------------------------------

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        return await anyio.to_thread.run_sync(self._expire_sync, req)

    def _expire_sync(self, req: ExpireRequest) -> ExpireResponse:
        action = req.action if req.action is not None else ExpireAction.FORGET
        policy = req.policy

        # Defensive: never trust router-layer validation. An empty/None
        # policy with action=FORGET (the default) would otherwise
        # soft-delete every live row for the agent. Mirror the router's
        # guard so direct adapter use is equally safe.
        if policy is None or (
            policy.older_than_days is None
            and policy.type is None
            and policy.confidence_below is None
            and policy.no_recall_in_days is None
        ):
            raise ValueError(
                "expire requires a non-empty policy: at least one of "
                "older_than_days, type, confidence_below, or no_recall_in_days "
                "must be set"
            )

        clauses: list[str] = ["agent_id = ?", "deleted_at IS NULL"]
        params: list[Any] = [req.agent_id]
        now = _now_ms()

        if policy is not None:
            if policy.older_than_days is not None:
                cutoff = now - int(policy.older_than_days) * 86_400_000
                clauses.append("created_at <= ?")
                params.append(cutoff)
            if policy.type is not None:
                clauses.append("type = ?")
                params.append(policy.type.value)
            if policy.confidence_below is not None:
                clauses.append("confidence < ?")
                params.append(float(policy.confidence_below))
            if policy.no_recall_in_days is not None:
                cutoff = now - int(policy.no_recall_in_days) * 86_400_000
                # Memories never recalled also count as "not recalled in N days".
                clauses.append("(last_recalled_at IS NULL OR last_recalled_at <= ?)")
                params.append(cutoff)

        where_sql = " AND ".join(clauses)

        with self._conn:
            target_rows = list(
                self._conn.execute(
                    f"SELECT id, metadata FROM memories WHERE {where_sql}",
                    params,
                )
            )
            target_ids = [row["id"] for row in target_rows]

            if target_ids:
                placeholders = ",".join("?" * len(target_ids))
                if action is ExpireAction.FORGET:
                    self._conn.execute(
                        f"UPDATE memories SET deleted_at = ?, updated_at = ? "
                        f"WHERE id IN ({placeholders})",
                        (now, now, *target_ids),
                    )
                elif action is ExpireAction.ARCHIVE:
                    # Update each row's metadata to set archived=true, then soft-delete.
                    for row in target_rows:
                        merged: dict[str, Any] = {}
                        if row["metadata"]:
                            try:
                                loaded = json.loads(row["metadata"])
                                if isinstance(loaded, dict):
                                    merged.update(loaded)
                            except json.JSONDecodeError:
                                pass
                        merged["archived"] = True
                        self._conn.execute(
                            "UPDATE memories SET metadata = ?, deleted_at = ?, updated_at = ? "
                            "WHERE id = ?",
                            (json.dumps(merged), now, now, row["id"]),
                        )
                elif action is ExpireAction.DEMOTE:
                    self._conn.execute(
                        f"UPDATE memories SET confidence = COALESCE(confidence, 1.0) * 0.25, "
                        f"updated_at = ? WHERE id IN ({placeholders})",
                        (now, *target_ids),
                    )

            self._audit(
                "expire",
                agent_id=req.agent_id,
                user_id=None,
                memory_id=None,
                payload=req.model_dump(mode="json", exclude_none=True),
                result={"matched_count": len(target_ids), "action_taken": action.value},
            )

        return ExpireResponse(
            matched_count=len(target_ids),
            action_taken=action,
            stores=[BACKEND_NAME],
        )

    # ------------------------------------------------------------------
    # filter clause helper (shared by recall + forget)
    # ------------------------------------------------------------------

    # Top-level columns that flat filters may target directly. Any other key
    # is matched against the JSON metadata blob.
    _TOP_LEVEL_FILTER_COLUMNS = frozenset({"agent_id", "user_id", "type", "source", "confidence"})

    def _filter_clause(self, flt: Mapping[str, Any]) -> tuple[str, list[Any]]:
        """Build a parameterised WHERE fragment from a flat filter mapping."""
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in flt.items():
            if key in self._TOP_LEVEL_FILTER_COLUMNS:
                clauses.append(f"{key} = ?")
                if isinstance(value, MemoryType):
                    params.append(value.value)
                else:
                    params.append(value)
            else:
                # Match against the JSON metadata blob.
                clauses.append("json_extract(metadata, ?) = ?")
                params.append(f"$.{key}")
                params.append(value)
        return (" AND ".join(clauses), params) if clauses else ("", [])

    # ------------------------------------------------------------------
    # health + capabilities
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(self._health_sync)

    def _health_sync(self) -> dict[str, Any]:
        count_row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM memories WHERE deleted_at IS NULL"
        ).fetchone()
        memory_count = int(count_row["n"]) if count_row is not None else 0
        return {
            "status": "ok",
            "backend": BACKEND_NAME,
            "db_path": self.db_path,
            "memory_count": memory_count,
            "schema_version": SCHEMA_VERSION,
        }

    @property
    def capabilities(self) -> set[str]:
        return {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.PROCEDURAL,
            Capability.EMOTIONAL,
            Capability.FTS,
            Capability.VECTOR,
            Capability.RECALL_TRACKING,
        }


__all__ = [
    "BACKEND_NAME",
    "DEFAULT_EMBEDDING_DIM",
    "PENDING_APPROVAL_DELETED_AT",
    "SqliteVecStore",
]
