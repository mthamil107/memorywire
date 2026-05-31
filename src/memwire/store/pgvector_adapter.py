"""Postgres + ``pgvector`` :class:`MemoryStore` adapter (Phase 3, day-1 backend #5).

This module exposes :class:`PgVectorStore`, a :class:`memwire.store.MemoryStore`
implementation backed by PostgreSQL with the ``pgvector`` extension. It is the
production-grade analogue to :class:`memwire.store.sqlite_vec.SqliteVecStore`:
same conceptual schema (see :file:`docs/kickoff/ARCHITECTURE.md` Â§3), but
translated to the Postgres dialect, with the ANN index served by ``pgvector``'s
``vector(N)`` column type plus an ``ivfflat`` index.

Design notes
------------
* The ``asyncpg`` + ``pgvector`` packages are *optional extras* (``pip install
  agent-memory-protocol[postgres]``). The imports live behind ``TYPE_CHECKING``
  and inside :meth:`PgVectorStore._get_pool` so this module loads cleanly even
  without the extras installed â€” unit tests use ``unittest.mock.AsyncMock`` and
  never need a running Postgres.
* asyncpg is natively async; no thread-pool wrapping is needed, unlike
  :mod:`memwire.store.sqlite_vec` / :mod:`memwire.store.mem0_adapter`. Every method on
  this adapter is awaited directly.
* Postgres has a rich permission model and a real schema namespace, so we
  default to placing every table under the ``amp`` schema. Multiple agents
  can share a database by giving each a separate schema (overridable via
  the ``schema=`` constructor kwarg).
* The default embedder mirrors :mod:`memwire.store.sqlite_vec`: 384-d output from
  ``sentence-transformers/all-MiniLM-L6-v2``, lazy-loaded on first use,
  injectable via ``embedder=`` for tests.
* FTS is deferred: Postgres has its own ``tsvector`` machinery but the v0
  adapter only exercises vector ANN. The :attr:`Capability.FTS` flag is not
  declared. spec-gap: documented below.
* All SQL is parameterised; identifiers like the schema name are validated
  on construction so they cannot reach the SQL string with hostile content.
* IDs use :func:`uuid.uuid4` hex â€” same choice and same deferral note as
  :mod:`memwire.store.sqlite_vec` (uuid7 once Python 3.14 is the floor).

URL anatomy
-----------
``PgVectorStore.from_url`` accepts three forms:

* ``pgvector://<full-dsn>`` â€” everything after ``pgvector://`` is interpreted
  as a Postgres DSN. Example: ``pgvector://user:pw@localhost:5432/amp``.
* ``pgvector+postgres://user:pw@host:port/db`` â€” explicit
  ``pgvector+postgres`` scheme; the ``+postgres`` half is purely cosmetic and
  is stripped before handing the DSN to asyncpg.
* ``pgvector://default`` â€” reads ``DATABASE_URL`` from the environment.

Spec-gap summary
----------------
* No FTS column / GIN index on ``content`` at v0; recall is vector-only. A
  hybrid mode is on the v0.2 roadmap.
* The ``ivfflat`` index uses ``vector_l2_ops`` (Euclidean distance). The
  default sentence-transformers embedder is L2-normalised so cosine and L2
  produce the same ranking; users who plug a non-normalised embedder may
  want to redefine the index with ``vector_cosine_ops``.
* ``ivfflat`` requires training data before it speeds anything up; on an
  empty schema the index exists but planner falls back to a sequential
  scan until ``ANALYZE`` runs. Documented; not a correctness issue.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

from memwire.models import (
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
from memwire.store.base import Capability

# Re-export the public sentinel from the sqlite-vec adapter so governance UIs
# and downstream consumers only need to import it from one place.
from memwire.store.sqlite_vec import PENDING_APPROVAL_DELETED_AT

if TYPE_CHECKING:  # pragma: no cover â€” typing-only.
    import asyncpg  # noqa: F401


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKEND_NAME = "pgvector"
SCHEMA_VERSION = 1
DEFAULT_EMBEDDING_DIM: Final[int] = 384

EmbedderFn = Callable[[str], list[float]]

# Identifier-safe characters for the schema namespace. We refuse anything
# outside this set rather than try to quote â€” the schema name appears in
# raw DDL because PostgreSQL does not parameterise identifiers.
_IDENT_RE = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _now_ms() -> int:
    """Return the current Unix time in milliseconds (memwire timestamp format)."""
    return int(time.time() * 1000)


def _validate_identifier(name: str, kind: str = "identifier") -> str:
    """Reject identifiers that cannot safely be interpolated into DDL."""
    if not _IDENT_RE.match(name):
        raise ValueError(
            f"{kind} must match [A-Za-z_][A-Za-z0-9_]*; got {name!r}. "
            "Quoted/Unicode identifiers are not supported by the pgvector adapter."
        )
    return name


def _format_vector_literal(vec: list[float]) -> str:
    """Render a vector as the ``pgvector`` literal syntax: ``'[0.1, 0.2, ...]'``.

    asyncpg can encode lists/tuples directly when the ``vector`` type is
    registered on the connection, but we keep the wire format explicit so the
    unit tests (which mock asyncpg) can match the SQL+params exactly without
    pulling the real ``pgvector`` codec.
    """
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class PgVectorStore:
    """memwire adapter for PostgreSQL + ``pgvector``.

    Parameters
    ----------
    dsn:
        Postgres connection string (``postgres://user:pw@host:port/db``).
        Mutually exclusive with ``pool`` â€” supply one or the other.
    pool:
        An already-constructed ``asyncpg.Pool`` (or compatible
        :class:`unittest.mock.AsyncMock`). Useful for dependency injection
        in tests and for sharing a single pool across multiple adapters.
    schema:
        Postgres schema namespace under which memwire tables live. Defaults to
        ``"memwire"``. Must match ``[A-Za-z_][A-Za-z0-9_]*``.
    embedding_dim:
        Vector length the embedder produces. Defaults to 384 to match
        sentence-transformers' all-MiniLM-L6-v2 (same as
        :mod:`memwire.store.sqlite_vec`).
    embedder:
        Optional ``text -> list[float]`` callable. When omitted, the default
        sentence-transformers model is lazy-loaded on first use. Tests inject
        a fake embedder via this kwarg.
    ensure_schema:
        When ``True`` (the default), the first operation runs
        ``CREATE EXTENSION``, ``CREATE SCHEMA``, and ``CREATE TABLE`` DDL.
        Set to ``False`` to skip bootstrap (e.g. when running against a
        DBA-provisioned schema where the application user lacks DDL rights).
    """

    BACKEND_NAME = BACKEND_NAME

    def __init__(
        self,
        dsn: str | None = None,
        *,
        pool: Any | None = None,
        schema: str = "memwire",
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        embedder: EmbedderFn | None = None,
        ensure_schema: bool = True,
    ) -> None:
        if dsn is None and pool is None:
            raise ValueError("PgVectorStore requires either a `dsn` or an injected `pool`")

        self._dsn: str | None = dsn
        self._pool: Any | None = pool
        self._schema: str = _validate_identifier(schema, kind="schema")
        self._embedding_dim: int = int(embedding_dim)
        self._embedder_override: EmbedderFn | None = embedder
        self._lazy_embedder: EmbedderFn | None = None
        self._ensure_schema_enabled: bool = bool(ensure_schema)
        self._schema_ready: bool = False

    # ------------------------------------------------------------------
    # URL form
    # ------------------------------------------------------------------

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        pool: Any | None = None,
        schema: str = "memwire",
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        embedder: EmbedderFn | None = None,
        ensure_schema: bool = True,
    ) -> PgVectorStore:
        """Construct a store from a ``pgvector://...`` URL.

        Recognised forms:

        * ``pgvector://<dsn>`` â€” everything after the scheme is the DSN. The
          adapter prepends ``postgres://`` if no scheme is present in the
          tail (the ``urlparse`` round-trip strips it).
        * ``pgvector+postgres://user:pw@host:port/db`` â€” explicit composite
          scheme; the ``+postgres`` half is stripped to recover the DSN.
        * ``pgvector://default`` â€” reads ``DATABASE_URL`` from the
          environment. Raises :class:`ValueError` if unset.
        """
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in {"pgvector", "pgvector+postgres", "pgvector+postgresql"}:
            raise ValueError(
                f"PgVectorStore.from_url expects a 'pgvector://' scheme; got {parsed.scheme!r}"
            )

        # Handle the magic ``pgvector://default`` form first.
        if scheme == "pgvector" and parsed.netloc == "default" and not parsed.path:
            dsn_env = os.environ.get("DATABASE_URL")
            if not dsn_env:
                raise ValueError(
                    "pgvector://default requires the DATABASE_URL environment variable to be set"
                )
            return cls(
                dsn=dsn_env,
                pool=pool,
                schema=schema,
                embedding_dim=embedding_dim,
                embedder=embedder,
                ensure_schema=ensure_schema,
            )

        # For the composite scheme, just swap the leading ``pgvector+`` off
        # so asyncpg sees a regular ``postgres://`` DSN.
        if scheme in {"pgvector+postgres", "pgvector+postgresql"}:
            dsn = url[len("pgvector+") :]
        else:
            # Plain ``pgvector://...`` form. The tail after ``pgvector://``
            # is the DSN; we re-prefix it with ``postgres://`` so asyncpg
            # parses it as expected.
            tail = url[len("pgvector://") :]
            if tail.startswith("postgres://") or tail.startswith("postgresql://"):
                dsn = tail
            else:
                dsn = "postgres://" + tail

        return cls(
            dsn=dsn,
            pool=pool,
            schema=schema,
            embedding_dim=embedding_dim,
            embedder=embedder,
            ensure_schema=ensure_schema,
        )

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    @property
    def capabilities(self) -> set[str]:
        """Capability set declared for the Postgres + pgvector backend.

        Postgres has rich primitive support, so we declare every memory-type
        flag plus ``VECTOR``, ``RECALL_TRACKING`` (the ``last_recalled_at``
        column is updated on every recall hit), and ``GOVERNANCE`` (the
        ``PENDING_APPROVAL_DELETED_AT`` sentinel is honoured by recall). FTS
        is deliberately absent at v0 â€” see module docstring.
        """
        return {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.PROCEDURAL,
            Capability.EMOTIONAL,
            Capability.VECTOR,
            Capability.RECALL_TRACKING,
            Capability.GOVERNANCE,
        }

    # ------------------------------------------------------------------
    # Pool / connection plumbing
    # ------------------------------------------------------------------

    async def _get_pool(self) -> Any:
        """Return the asyncpg pool, constructing it on first use."""
        if self._pool is not None:
            return self._pool

        # Lazy import keeps the module import-safe without the postgres extra.
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - exercised by integration
            raise RuntimeError(
                "PgVectorStore requires asyncpg. "
                "Install with `pip install 'agent-memory-protocol[postgres]'`."
            ) from exc

        # ``self._dsn is None`` is impossible here because the constructor
        # enforces ``dsn or pool``; the assertion documents that invariant.
        assert self._dsn is not None
        self._pool = await asyncpg.create_pool(dsn=self._dsn)
        return self._pool

    async def _ensure_schema(self) -> None:
        """Run idempotent ``CREATE EXTENSION``/``CREATE SCHEMA``/``CREATE TABLE`` DDL.

        Called from the top of every public method. Becomes a no-op after
        the first successful invocation. Skipped entirely when the
        constructor was invoked with ``ensure_schema=False``.
        """
        if self._schema_ready or not self._ensure_schema_enabled:
            self._schema_ready = True
            return

        pool = await self._get_pool()
        schema = self._schema
        dim = self._embedding_dim

        # All DDL statements are idempotent â€” IF NOT EXISTS everywhere. The
        # schema/identifier strings are validated on construction.
        ddl: list[str] = [
            "CREATE EXTENSION IF NOT EXISTS vector",
            f"CREATE SCHEMA IF NOT EXISTS {schema}",
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.memories (
              id              text PRIMARY KEY,
              agent_id        text NOT NULL,
              user_id         text,
              type            text NOT NULL CHECK (type IN
                                ('semantic','episodic','procedural','emotional')),
              content         text NOT NULL,
              metadata        jsonb DEFAULT '{{}}'::jsonb,
              confidence      real DEFAULT 1.0,
              source          text,
              embedding       vector({dim}),
              created_at      bigint NOT NULL,
              updated_at      bigint NOT NULL,
              expires_at      bigint,
              deleted_at      bigint,
              last_recalled_at bigint
            )
            """,
            f"CREATE INDEX IF NOT EXISTS idx_memories_agent ON {schema}.memories(agent_id, type)",
            f"CREATE INDEX IF NOT EXISTS idx_memories_user  ON {schema}.memories(user_id)",
            f"CREATE INDEX IF NOT EXISTS idx_memories_created ON {schema}.memories(created_at)",
            f"CREATE INDEX IF NOT EXISTS idx_memories_embedding "
            f"ON {schema}.memories USING ivfflat (embedding vector_l2_ops)",
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.procedures (
              id text PRIMARY KEY,
              agent_id text NOT NULL,
              name text NOT NULL,
              states jsonb NOT NULL,
              current text,
              metadata jsonb DEFAULT '{{}}'::jsonb,
              created_at bigint NOT NULL,
              updated_at bigint NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.audit_log (
              id           bigserial PRIMARY KEY,
              ts           bigint NOT NULL,
              operation    text NOT NULL,
              agent_id     text,
              user_id      text,
              memory_id    text,
              payload      jsonb NOT NULL,
              result       jsonb,
              approved_by  text,
              approval_at  bigint
            )
            """,
            f"CREATE INDEX IF NOT EXISTS idx_audit_ts ON {schema}.audit_log(ts)",
        ]

        async with pool.acquire() as conn:
            for stmt in ddl:
                await conn.execute(stmt)

        self._schema_ready = True

    async def close(self) -> None:
        """Close the underlying asyncpg pool. Idempotent.

        Adapters constructed with an injected pool should let the caller
        manage the pool's lifecycle and not invoke :meth:`close`; we still
        attempt the close defensively because the facade calls it.
        """
        if self._pool is None:
            return
        closer = getattr(self._pool, "close", None)
        if closer is None:
            return
        try:
            result = closer()
            if hasattr(result, "__await__"):
                await result
        except Exception:
            # ``close`` is best-effort â€” never raise out of teardown.
            return

    # ------------------------------------------------------------------
    # Embedder
    # ------------------------------------------------------------------

    def _get_embedder(self) -> EmbedderFn:
        """Return the embedder, loading the default model on first use."""
        if self._embedder_override is not None:
            return self._embedder_override
        if self._lazy_embedder is not None:
            return self._lazy_embedder

        # Lazy import â€” sentence-transformers is an optional dependency. The
        # try/except gives a more actionable error than ImportError.
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised by integration
            raise RuntimeError(
                "PgVectorStore default embedder requires sentence-transformers. "
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
    # Audit
    # ------------------------------------------------------------------

    async def _audit(
        self,
        conn: Any,
        operation: str,
        *,
        agent_id: str | None,
        user_id: str | None,
        memory_id: str | None,
        payload: Mapping[str, Any] | dict[str, Any],
        result: Mapping[str, Any] | dict[str, Any] | None = None,
    ) -> None:
        """Append a row to ``audit_log`` over the supplied connection."""
        await conn.execute(
            f"INSERT INTO {self._schema}.audit_log("
            f"ts, operation, agent_id, user_id, memory_id, payload, result) "
            f"VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)",
            _now_ms(),
            operation,
            agent_id,
            user_id,
            memory_id,
            json.dumps(dict(payload), default=str),
            json.dumps(dict(result), default=str) if result is not None else None,
        )

    # ------------------------------------------------------------------
    # remember
    # ------------------------------------------------------------------

    async def remember(self, req: RememberRequest) -> RememberResponse:
        await self._ensure_schema()
        pool = await self._get_pool()

        memory_id = uuid.uuid4().hex
        stored_at = _now_ms()
        approval_required = bool(req.approval_required)
        deleted_at = PENDING_APPROVAL_DELETED_AT if approval_required else None
        stores = [] if approval_required else [BACKEND_NAME]

        embedding = self._embed(req.content)
        embedding_literal = _format_vector_literal(embedding)
        metadata_json = json.dumps(req.metadata if req.metadata is not None else {})
        confidence = req.confidence if req.confidence is not None else 1.0

        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self._schema}.memories(
                    id, agent_id, user_id, type, content, metadata,
                    confidence, source, embedding,
                    created_at, updated_at, expires_at, deleted_at, last_recalled_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6::jsonb,
                    $7, $8, $9::vector,
                    $10, $11, $12, $13, NULL
                )
                """,
                memory_id,
                req.agent_id,
                req.user_id,
                req.type.value,
                req.content,
                metadata_json,
                float(confidence),
                req.source,
                embedding_literal,
                stored_at,
                stored_at,
                req.expires_at,
                deleted_at,
            )

            # Procedural side-table: keep one row per procedural memory.
            if req.type is MemoryType.PROCEDURAL:
                fsm = self._parse_fsm(req.content)
                await conn.execute(
                    f"""
                    INSERT INTO {self._schema}.procedures(
                        id, agent_id, name, states, current, metadata,
                        created_at, updated_at
                    ) VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb, $7, $8)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        states = EXCLUDED.states,
                        current = EXCLUDED.current,
                        metadata = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                    """,
                    memory_id,
                    req.agent_id,
                    str(fsm.get("name", memory_id)),
                    json.dumps(fsm),
                    fsm.get("current"),
                    metadata_json,
                    stored_at,
                    stored_at,
                )

            await self._audit(
                conn,
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
        """Best-effort decode of a procedural memory's content as an FSM dict."""
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
        await self._ensure_schema()
        pool = await self._get_pool()

        started_ms = _now_ms()
        k = req.k if req.k is not None else 5

        where_sql, params = self._build_recall_filter(req)

        query_vec = self._embed(req.query)
        vec_literal = _format_vector_literal(query_vec)

        # ``embedding <-> $N::vector`` is the L2 distance operator. Smaller is
        # better, hence the ASC order; we convert to a positive score (1 /
        # (1 + d)) on the client side so RecallHit.score is monotonic with
        # relevance (higher = better) â€” matches the sqlite_vec adapter's
        # convention via RRF scoring.
        params.append(vec_literal)
        vec_param_idx = len(params)
        params.append(int(k))
        limit_param_idx = len(params)

        sql = (
            f"SELECT id, agent_id, user_id, type, content, metadata, "
            f"       confidence, source, created_at, updated_at, expires_at, "
            f"       (embedding <-> ${vec_param_idx}::vector) AS distance "
            f"FROM {self._schema}.memories "
            f"WHERE {where_sql} "
            f"ORDER BY embedding <-> ${vec_param_idx}::vector "
            f"LIMIT ${limit_param_idx}"
        )

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

            hits: list[RecallHit] = []
            recalled_ids: list[str] = []
            for row in rows:
                distance = row["distance"]
                score = 1.0 / (1.0 + float(distance)) if distance is not None else 0.0
                hits.append(self._row_to_hit(row, score))
                recalled_ids.append(row["id"])

            # Update last_recalled_at for the rows we surfaced. Best-effort â€”
            # never fail the recall on a tracker write.
            if recalled_ids:
                await conn.execute(
                    f"UPDATE {self._schema}.memories SET last_recalled_at = $1 "
                    f"WHERE id = ANY($2::text[])",
                    _now_ms(),
                    recalled_ids,
                )

            await self._audit(
                conn,
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
        """Return ``(where_sql, params)`` for the recall path.

        Uses 1-indexed Postgres ``$N`` placeholders. The caller is expected
        to extend the params list with the vector + limit before composing
        the final SQL.
        """
        clauses: list[str] = []
        params: list[Any] = []

        params.append(req.agent_id)
        clauses.append(f"agent_id = ${len(params)}")

        # ``deleted_at IS NULL`` hides soft-deleted rows *and* PENDING ones
        # (the latter use a non-NULL sentinel) â€” same shape as sqlite_vec.
        clauses.append("deleted_at IS NULL")

        if req.user_id is not None:
            params.append(req.user_id)
            clauses.append(f"user_id = ${len(params)}")

        if req.types:
            params.append([t.value for t in req.types])
            clauses.append(f"type = ANY(${len(params)}::text[])")

        if req.fresher_than_days is not None:
            cutoff_ms = _now_ms() - int(req.fresher_than_days) * 86_400_000
            params.append(cutoff_ms)
            clauses.append(f"created_at >= ${len(params)}")

        if req.filter:
            filter_sql, _filter_params, params = self._filter_clause(req.filter, params)
            if filter_sql:
                clauses.append(filter_sql)

        return " AND ".join(clauses), params

    def _row_to_hit(self, row: Any, score: float) -> RecallHit:
        """Convert a ``memories`` row + a score into a :class:`RecallHit`.

        ``row`` may be an asyncpg.Record (mapping-like) or a plain dict in
        tests; both expose ``[key]`` access.
        """
        metadata_raw = row["metadata"]
        metadata: dict[str, Any] | None
        if metadata_raw:
            # asyncpg returns jsonb as a string by default unless a codec is
            # registered. Handle both shapes defensively.
            if isinstance(metadata_raw, str):
                try:
                    loaded = json.loads(metadata_raw)
                except json.JSONDecodeError:
                    loaded = None
            else:
                loaded = metadata_raw
            metadata = loaded if isinstance(loaded, dict) and loaded else None
        else:
            metadata = None
        return RecallHit(
            id=row["id"],
            type=MemoryType(row["type"]),
            content=row["content"],
            score=float(score),
            metadata=metadata,
            created_at=row["created_at"],
            supporting=[],
            source_store=BACKEND_NAME,
        )

    # ------------------------------------------------------------------
    # forget
    # ------------------------------------------------------------------

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        # Spec section 3.3 Editor's note: refuse no-scope mass delete BEFORE
        # any side-effect (e.g. schema bootstrap) so the error is fast and
        # cheap.
        if not req.ids and not req.filter:
            raise ValueError("forget requires `ids` or `filter`")

        await self._ensure_schema()
        pool = await self._get_pool()

        hard = bool(req.hard_delete)
        now = _now_ms()
        target_ids: list[str] = []

        async with pool.acquire() as conn:
            if req.ids:
                rows = await conn.fetch(
                    f"SELECT id FROM {self._schema}.memories "
                    f"WHERE agent_id = $1 AND id = ANY($2::text[]) "
                    f"AND deleted_at IS NULL",
                    req.agent_id,
                    list(req.ids),
                )
                target_ids.extend(r["id"] for r in rows)

            if req.filter:
                params: list[Any] = [req.agent_id]
                base_clause = (
                    f"SELECT id FROM {self._schema}.memories "
                    f"WHERE agent_id = $1 AND deleted_at IS NULL"
                )
                filter_sql, _filter_params, params = self._filter_clause(req.filter, params)
                sql = base_clause + " AND " + filter_sql if filter_sql else base_clause
                for r in await conn.fetch(sql, *params):
                    if r["id"] not in target_ids:
                        target_ids.append(r["id"])

            if target_ids:
                if hard:
                    await conn.execute(
                        f"DELETE FROM {self._schema}.memories WHERE id = ANY($1::text[])",
                        target_ids,
                    )
                else:
                    await conn.execute(
                        f"UPDATE {self._schema}.memories "
                        f"SET deleted_at = $1, updated_at = $1 "
                        f"WHERE id = ANY($2::text[])",
                        now,
                        target_ids,
                    )

            await self._audit(
                conn,
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
        await self._ensure_schema()
        pool = await self._get_pool()

        strategy = req.strategy if req.strategy is not None else MergeStrategy.KEEP_CANONICAL

        async with pool.acquire() as conn:
            canonical_rows = await self._resolve_entity(conn, req.agent_id, req.canonical)
            duplicate_rows: list[Any] = []
            for dup_key in req.duplicates:
                duplicate_rows.extend(await self._resolve_entity(conn, req.agent_id, dup_key))

            canonical_ids = {row["id"] for row in canonical_rows}
            duplicate_rows = [r for r in duplicate_rows if r["id"] not in canonical_ids]

            now = _now_ms()
            merged_count = 0

            if not canonical_rows and not duplicate_rows:
                response = MergeResponse(
                    canonical=req.canonical,
                    merged_count=0,
                    strategy_used=strategy,
                    stores=[BACKEND_NAME],
                )
                await self._audit(
                    conn,
                    "merge",
                    agent_id=req.agent_id,
                    user_id=None,
                    memory_id=req.canonical,
                    payload=req.model_dump(mode="json", exclude_none=True),
                    result={"merged_count": 0, "strategy_used": strategy.value},
                )
                return response

            if strategy is MergeStrategy.KEEP_CANONICAL:
                merged_count = await self._soft_delete_ids(
                    conn, [r["id"] for r in duplicate_rows], now
                )

            elif strategy is MergeStrategy.KEEP_HIGHEST_CONFIDENCE:
                all_rows = canonical_rows + duplicate_rows
                winner = max(
                    all_rows,
                    key=lambda r: (
                        r["confidence"] if r["confidence"] is not None else -1.0,
                        -(r["created_at"] or 0),  # older wins tie
                    ),
                )
                losers = [r["id"] for r in all_rows if r["id"] != winner["id"]]
                merged_count = await self._soft_delete_ids(conn, losers, now)

            elif strategy is MergeStrategy.MERGE_CONTENT:
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
                merged_metadata: dict[str, Any] = self._coerce_metadata(survivor["metadata"])
                best_confidence = survivor["confidence"] or 0.0

                for row in sorted(losers, key=lambda r: r["created_at"] or 0):
                    contents.append(row["content"])
                    merged_metadata.update(self._coerce_metadata(row["metadata"]))
                    if (row["confidence"] or 0.0) > best_confidence:
                        best_confidence = row["confidence"] or 0.0

                merged_content = " | ".join(contents)
                await conn.execute(
                    f"UPDATE {self._schema}.memories "
                    f"SET content = $1, metadata = $2::jsonb, confidence = $3, updated_at = $4 "
                    f"WHERE id = $5",
                    merged_content,
                    json.dumps(merged_metadata) if merged_metadata else "{}",
                    float(best_confidence),
                    now,
                    survivor["id"],
                )
                merged_count = await self._soft_delete_ids(conn, [r["id"] for r in losers], now)

            await self._audit(
                conn,
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

    async def _resolve_entity(self, conn: Any, agent_id: str, key: str) -> list[Any]:
        """Resolve a merge entity key to memory rows.

        Tries (a) exact id match and (b) ``metadata->>'entity_name'`` match.
        Mirrors :class:`memwire.store.sqlite_vec.SqliteVecStore._resolve_entity`.
        """
        rows = await conn.fetch(
            f"SELECT id, content, metadata, confidence, created_at "
            f"FROM {self._schema}.memories "
            f"WHERE agent_id = $1 AND id = $2 AND deleted_at IS NULL",
            agent_id,
            key,
        )
        if rows:
            return list(rows)
        rows = await conn.fetch(
            f"SELECT id, content, metadata, confidence, created_at "
            f"FROM {self._schema}.memories "
            f"WHERE agent_id = $1 AND deleted_at IS NULL "
            f"AND metadata->>'entity_name' = $2",
            agent_id,
            key,
        )
        return list(rows)

    async def _soft_delete_ids(self, conn: Any, ids: list[str], now: int) -> int:
        if not ids:
            return 0
        await conn.execute(
            f"UPDATE {self._schema}.memories "
            f"SET deleted_at = $1, updated_at = $1 "
            f"WHERE id = ANY($2::text[])",
            now,
            ids,
        )
        return len(ids)

    @staticmethod
    def _coerce_metadata(raw: Any) -> dict[str, Any]:
        """Normalise a metadata cell into a ``dict[str, Any]``.

        asyncpg may return jsonb as either a Python object (when a codec is
        registered) or a JSON string. Both shapes survive here.
        """
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str):
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return loaded if isinstance(loaded, dict) else {}
        return {}

    # ------------------------------------------------------------------
    # expire
    # ------------------------------------------------------------------

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        # Defensive: refuse empty policies BEFORE schema bootstrap so the
        # error is fast and cheap. Mirrors the sqlite_vec contract.
        policy = req.policy
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

        await self._ensure_schema()
        pool = await self._get_pool()

        action = req.action if req.action is not None else ExpireAction.FORGET
        now = _now_ms()

        params: list[Any] = [req.agent_id]
        clauses: list[str] = ["agent_id = $1", "deleted_at IS NULL"]

        if policy.older_than_days is not None:
            cutoff = now - int(policy.older_than_days) * 86_400_000
            params.append(cutoff)
            clauses.append(f"created_at <= ${len(params)}")
        if policy.type is not None:
            params.append(policy.type.value)
            clauses.append(f"type = ${len(params)}")
        if policy.confidence_below is not None:
            params.append(float(policy.confidence_below))
            clauses.append(f"confidence < ${len(params)}")
        if policy.no_recall_in_days is not None:
            cutoff = now - int(policy.no_recall_in_days) * 86_400_000
            params.append(cutoff)
            # Never-recalled rows count as "not recalled in N days", matching
            # the sqlite_vec adapter.
            clauses.append(f"(last_recalled_at IS NULL OR last_recalled_at <= ${len(params)})")

        where_sql = " AND ".join(clauses)

        async with pool.acquire() as conn:
            target_rows = await conn.fetch(
                f"SELECT id, metadata FROM {self._schema}.memories WHERE {where_sql}",
                *params,
            )
            target_ids = [row["id"] for row in target_rows]

            if target_ids:
                if action is ExpireAction.FORGET:
                    await conn.execute(
                        f"UPDATE {self._schema}.memories "
                        f"SET deleted_at = $1, updated_at = $1 "
                        f"WHERE id = ANY($2::text[])",
                        now,
                        target_ids,
                    )
                elif action is ExpireAction.ARCHIVE:
                    # Stamp metadata.archived = true row-by-row, then soft-delete.
                    for row in target_rows:
                        merged = self._coerce_metadata(row["metadata"])
                        merged["archived"] = True
                        await conn.execute(
                            f"UPDATE {self._schema}.memories "
                            f"SET metadata = $1::jsonb, deleted_at = $2, updated_at = $2 "
                            f"WHERE id = $3",
                            json.dumps(merged),
                            now,
                            row["id"],
                        )
                elif action is ExpireAction.DEMOTE:
                    await conn.execute(
                        f"UPDATE {self._schema}.memories "
                        f"SET confidence = COALESCE(confidence, 1.0) * 0.25, updated_at = $1 "
                        f"WHERE id = ANY($2::text[])",
                        now,
                        target_ids,
                    )

            await self._audit(
                conn,
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
    # is matched against the JSON metadata blob via ``->>``.
    _TOP_LEVEL_FILTER_COLUMNS = frozenset({"agent_id", "user_id", "type", "source", "confidence"})

    def _filter_clause(
        self,
        flt: Mapping[str, Any],
        params: list[Any],
    ) -> tuple[str, list[Any], list[Any]]:
        """Build a parameterised WHERE fragment from a flat filter mapping.

        Returns ``(where_sql, this_call_params, all_params)``. The first
        return value is the SQL fragment using ``$N`` placeholders indexed
        into ``all_params`` (which is the caller's ``params`` list extended
        in place). ``this_call_params`` is included for symmetry but the
        composed ``all_params`` is what the caller should pass to asyncpg.
        """
        clauses: list[str] = []
        added: list[Any] = []
        for key, value in flt.items():
            if key in self._TOP_LEVEL_FILTER_COLUMNS:
                if isinstance(value, MemoryType):
                    value = value.value
                params.append(value)
                added.append(value)
                clauses.append(f"{key} = ${len(params)}")
            else:
                # Match against the jsonb metadata blob. ``->>`` extracts as
                # text so we compare as text to keep this dialect-portable.
                params.append(str(value))
                added.append(str(value))
                clauses.append(f"metadata->>'{self._escape_json_key(key)}' = ${len(params)}")
        return (" AND ".join(clauses), added, params) if clauses else ("", [], params)

    @staticmethod
    def _escape_json_key(key: str) -> str:
        """Escape a JSON key for embedding inside a ``metadata->>'...'`` literal.

        We accept ``[A-Za-z0-9_]+`` keys only â€” anything else is replaced
        with ``_`` so a hostile caller cannot inject SQL. The recall path
        already passes the *value* as a parameter; this just keeps the
        keypath out of injection range.
        """
        return "".join(c if (c.isalnum() or c == "_") else "_" for c in key)

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        try:
            await self._ensure_schema()
        except Exception as exc:
            return {"status": "error", "backend": BACKEND_NAME, "error": str(exc)}

        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                pg_version_row = await conn.fetchrow("SELECT version() AS v")
                count_row = await conn.fetchrow(
                    f"SELECT COUNT(*) AS n FROM {self._schema}.memories WHERE deleted_at IS NULL"
                )
        except Exception as exc:
            return {"status": "error", "backend": BACKEND_NAME, "error": str(exc)}

        pg_version = pg_version_row["v"] if pg_version_row is not None else None
        memory_count = int(count_row["n"]) if count_row is not None else 0
        return {
            "status": "ok",
            "backend": BACKEND_NAME,
            "schema": self._schema,
            "pg_version": pg_version,
            "memory_count": memory_count,
            "schema_version": SCHEMA_VERSION,
        }


__all__ = [
    "BACKEND_NAME",
    "DEFAULT_EMBEDDING_DIM",
    "PENDING_APPROVAL_DELETED_AT",
    "PgVectorStore",
]
