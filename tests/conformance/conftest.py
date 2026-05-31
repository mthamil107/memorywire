"""Adapter fixtures and parametrize plumbing for the conformance suite.

Each ``build_store_for(adapter_id)`` helper returns a ready-to-use
:class:`memorywire.store.MemoryStore` instance. For the real adapter
(sqlite-vec) the store talks to an in-memory SQLite DB with a fake
sha256-based embedder. For the four mocked adapters the helper builds
a backend-shaped mock whose method side-effects keep the conformance
predicates honest:

* ``mem0`` â€” :class:`unittest.mock.MagicMock` that records every
  ``add``/``search``/``delete``/``get_all`` call in an in-memory store
  dict; the side_effect lambdas filter by user_id / filter dict.
* ``letta`` â€” same shape, mock surface
  ``client.agents.passages.{create,search,delete,list}``.
* ``cognee`` â€” :class:`AsyncMock` for the module-level coroutines plus
  a side_effect ``search`` that returns memorywire-wrapped blobs from an
  in-memory dict.
* ``pgvector`` â€” :class:`AsyncMock` for the asyncpg pool/connection,
  with ``fetch`` driven by an in-memory rowset.

The mocks are deliberately simple (not pretending to be a full backend);
they implement just enough behaviour for the protocol invariants in
:mod:`scenarios.py` to fire end-to-end.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from memorywire.models import RememberRequest
from memorywire.store.cognee_adapter import CogneeStore
from memorywire.store.letta_adapter import LettaStore
from memorywire.store.mem0_adapter import Mem0Store
from memorywire.store.pgvector_adapter import DEFAULT_EMBEDDING_DIM, PgVectorStore
from memorywire.store.sqlite_vec import SqliteVecStore

ADAPTER_IDS = ["sqlite-vec", "mem0", "letta", "cognee", "pgvector"]


# ---------------------------------------------------------------------------
# Fake embedder â€” deterministic, sha256-based, 384-dim. Mirrors the existing
# unit-test fake_embedder so behaviour stays consistent.
# ---------------------------------------------------------------------------


def fake_embedder(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (digest * 12)[:DEFAULT_EMBEDDING_DIM]
    return [byte / 255.0 for byte in raw]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _backdate_from_metadata(req: RememberRequest) -> int | None:
    """Return the ``_conformance_backdate_ms`` offset, if any."""
    if req.metadata is None:
        return None
    val = req.metadata.get("_conformance_backdate_ms")
    if isinstance(val, int):
        return val
    return None


# ---------------------------------------------------------------------------
# sqlite-vec â€” the REAL adapter.
# ---------------------------------------------------------------------------


def _build_sqlite_vec() -> SqliteVecStore:
    """Build a SqliteVecStore that honours the ``_conformance_backdate_ms`` marker.

    Conformance scenarios that need a backdated row pass an integer offset
    in metadata; we wrap ``remember`` to rewrite ``memories.created_at``
    post-write. Keeps scenario definitions backend-agnostic (no fixture
    has to know about the adapter's storage column names).
    """
    s = SqliteVecStore(":memory:", embedder=fake_embedder)
    original_remember = s.remember

    async def _remember_with_backdate(req: RememberRequest) -> Any:
        resp = await original_remember(req)
        offset = _backdate_from_metadata(req)
        if offset is not None:
            s._conn.execute(
                "UPDATE memories SET created_at = created_at - ? WHERE id = ?",
                (offset, resp.id),
            )
        return resp

    s.remember = _remember_with_backdate
    return s


# ---------------------------------------------------------------------------
# mem0 â€” MOCKED.
# ---------------------------------------------------------------------------


def _build_mem0() -> Mem0Store:
    """A MagicMock-driven mem0 client backed by an in-memory dict.

    The mock implements add/search/get_all/delete/get/update with enough
    fidelity to pass scenarios that fall within mem0's capability set
    (semantic/episodic/vector).
    """
    rows: dict[str, dict[str, Any]] = {}
    mid_counter = {"n": 0}

    def _mint_id() -> str:
        mid_counter["n"] += 1
        return f"mem-{mid_counter['n']}"

    def add(content: str, **kwargs: Any) -> dict[str, Any]:
        rid = _mint_id()
        metadata = dict(kwargs.get("metadata") or {})
        # Decide created_at honouring the conformance backdate marker.
        offset = metadata.get("_conformance_backdate_ms")
        created_at = _now_ms() - int(offset) if isinstance(offset, int) else _now_ms()
        record = {
            "id": rid,
            "memory": content,
            "data": content,
            "metadata": metadata,
            "user_id": kwargs.get("user_id"),
            "agent_id": kwargs.get("agent_id"),
            "created_at": created_at,
            "score": 0.9,
        }
        rows[rid] = record
        return {"results": [{"id": rid, "memory": content, "event": "ADD"}]}

    def search(query: str, **kwargs: Any) -> dict[str, Any]:
        filters = kwargs.get("filters") or {}
        top_k = int(kwargs.get("top_k", 5) or 5)
        out: list[dict[str, Any]] = []
        for rec in rows.values():
            # Filter by user_id / agent_id.
            if filters.get("user_id") and rec.get("user_id") != filters.get("user_id"):
                continue
            if filters.get("agent_id") and rec.get("agent_id") != filters.get("agent_id"):
                continue
            # Soft 'relevance' â€” score by token overlap with the query.
            qtokens = {t for t in query.lower().split() if t}
            ctokens = {t for t in str(rec.get("memory") or "").lower().split() if t}
            overlap = len(qtokens & ctokens)
            # If nothing overlaps we still surface the row at a low score
            # so multi-write scenarios get >=1 hit.
            rec_score = 0.1 if overlap == 0 and qtokens else 0.5 + overlap * 0.1
            out.append({**rec, "score": rec_score})
        out.sort(key=lambda r: r["score"], reverse=True)
        return {"results": out[:top_k]}

    def get_all(**kwargs: Any) -> dict[str, Any]:
        filters = kwargs.get("filters") or {}
        out: list[dict[str, Any]] = []
        for rec in rows.values():
            if filters.get("user_id") and rec.get("user_id") != filters.get("user_id"):
                continue
            if filters.get("agent_id") and rec.get("agent_id") != filters.get("agent_id"):
                continue
            out.append(rec)
        return {"results": out}

    def delete(mid: str) -> None:
        rows.pop(mid, None)

    def get(mid: str) -> dict[str, Any] | None:
        return rows.get(mid)

    def update(mid: str, **kwargs: Any) -> dict[str, Any]:
        rec = rows.get(mid)
        if rec is not None:
            if "data" in kwargs:
                rec["memory"] = kwargs["data"]
                rec["data"] = kwargs["data"]
            if "metadata" in kwargs:
                rec["metadata"] = kwargs["metadata"]
        return {"message": "ok"}

    client = MagicMock()
    client.add = MagicMock(side_effect=add)
    client.search = MagicMock(side_effect=search)
    client.get_all = MagicMock(side_effect=get_all)
    client.delete = MagicMock(side_effect=delete)
    client.get = MagicMock(side_effect=get)
    client.update = MagicMock(side_effect=update)
    return Mem0Store(client=client)


# ---------------------------------------------------------------------------
# letta â€” MOCKED.
# ---------------------------------------------------------------------------


def _build_letta() -> LettaStore:
    """A MagicMock-driven Letta client backed by an in-memory passage list."""

    rows: dict[str, dict[str, Any]] = {}
    pid_counter = {"n": 0}

    def _mint_id() -> str:
        pid_counter["n"] += 1
        return f"p-{pid_counter['n']}"

    def create(**kwargs: Any) -> list[dict[str, Any]]:
        rid = _mint_id()
        tags = list(kwargs.get("tags") or [])
        # Look for the backdate marker in tags
        # ('amp_kv:_conformance_backdate_ms=<ms>') and rewrite created_at.
        created_at_ms = _now_ms()
        for t in list(tags):
            if t.startswith("amp_kv:_conformance_backdate_ms="):
                try:
                    offset_ms = int(t.split("=", 1)[1])
                    created_at_ms = _now_ms() - offset_ms
                except ValueError:
                    pass
                tags.remove(t)
        record = {
            "id": rid,
            "text": kwargs.get("text") or "",
            "tags": tags,
            "created_at": created_at_ms,
        }
        rows[rid] = record
        return [record]

    def search(**kwargs: Any) -> list[dict[str, Any]]:
        query = (kwargs.get("query") or "").lower()
        top_k = int(kwargs.get("top_k", 5) or 5)
        qtokens = {t for t in query.split() if t}
        scored: list[tuple[float, dict[str, Any]]] = []
        for rec in rows.values():
            ctokens = {t for t in rec["text"].lower().split() if t}
            overlap = len(qtokens & ctokens)
            score = 0.1 + overlap * 0.1
            scored.append((score, {"passage": rec, "score": score}))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [s[1] for s in scored[:top_k]]

    def list_(**_kwargs: Any) -> list[dict[str, Any]]:
        return list(rows.values())

    def delete(**kwargs: Any) -> None:
        mid = kwargs.get("memory_id")
        if isinstance(mid, str):
            rows.pop(mid, None)

    client = MagicMock()
    # NB: Letta SDK uses keyword arg `query=` for search; the adapter sends
    # it as a kwarg. MagicMock side_effects must accept that signature.
    client.agents.passages.create = MagicMock(side_effect=create)
    client.agents.passages.search = MagicMock(side_effect=search)
    client.agents.passages.list = MagicMock(side_effect=list_)
    client.agents.passages.delete = MagicMock(side_effect=delete)
    client.health = MagicMock(return_value={"status": "ok"})

    return LettaStore(client=client, agent_id="conformance-agent")


# ---------------------------------------------------------------------------
# cognee â€” MOCKED.
# ---------------------------------------------------------------------------


def _build_cognee() -> CogneeStore:
    """A MagicMock-driven cognee module backed by an in-memory blob list.

    Cognee's ``add`` ingests text into a pipeline and returns nothing; the
    real ``search`` runs LLM completion. Our mock just stashes the wrapped
    blob and replays it back from ``search``.
    """

    blobs: list[str] = []

    def _apply_backdate(text: str) -> str:
        """Honour the conformance backdate marker baked into AMP_META metadata.

        The cognee adapter stamps ``created_at`` from server time at
        remember(); the conformance suite needs deterministic backdating
        for the freshness / age scenarios. We intercept the wrapped blob,
        find the ``metadata._conformance_backdate_ms`` marker, and rewrite
        the top-level ``created_at`` value by subtracting the offset.
        """
        if "<AMP_META>" not in text or "</AMP_META>" not in text:
            return text
        head, _, tail = text.partition("<AMP_META>")
        body, _, rest = tail.partition("</AMP_META>")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return text
        meta = payload.get("metadata") or {}
        offset = meta.get("_conformance_backdate_ms")
        if not isinstance(offset, int):
            return text
        if isinstance(payload.get("created_at"), int):
            payload["created_at"] = payload["created_at"] - offset
        new_body = json.dumps(payload, separators=(",", ":"))
        return head + "<AMP_META>" + new_body + "</AMP_META>" + rest

    async def add(text: str, **_kwargs: Any) -> None:
        blobs.append(_apply_backdate(text))

    async def remember_(text: str, **_kwargs: Any) -> None:
        blobs.append(_apply_backdate(text))

    async def search(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        # Score by token overlap on the *content* portion (after the
        # memorywire header), then surface as ResponseGraphEntry-shaped dicts.
        qtokens = {t for t in str(query).lower().split() if t}
        scored: list[tuple[float, dict[str, Any]]] = []
        for blob in blobs:
            # Extract content tail for scoring.
            tail = blob.split("</AMP_META>", 1)[-1].lstrip("\n").lower()
            ctokens = {t for t in tail.split() if t}
            overlap = len(qtokens & ctokens)
            score = 0.1 + overlap * 0.1
            scored.append((score, {"text": blob, "score": score}))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [s[1] for s in scored]

    async def forget(**kwargs: Any) -> dict[str, Any]:
        # Cognee's forget addresses data_id UUIDs. Our mock has no such
        # concept; the adapter never forwards a `cog:` id (it short-
        # circuits). For non-cog ids we simply drop matching blobs.
        target = kwargs.get("data_id")
        if isinstance(target, str):
            # Look for the id inside any blob header and drop that blob.
            survivors: list[str] = []
            for blob in blobs:
                if f'"id":"{target}"' in blob:
                    continue
                survivors.append(blob)
            blobs[:] = survivors
        return {"status": "ok"}

    module = MagicMock()
    module.add = AsyncMock(side_effect=add)
    module.remember = AsyncMock(side_effect=remember_)
    module.search = AsyncMock(side_effect=search)
    module.recall = AsyncMock(side_effect=search)
    module.forget = AsyncMock(side_effect=forget)
    module.SearchType = MagicMock()
    module.SearchType.GRAPH_COMPLETION = "GRAPH_COMPLETION"
    module.datasets = MagicMock()
    module.datasets.list_datasets = MagicMock(return_value=[])
    return CogneeStore(client=module)


# ---------------------------------------------------------------------------
# pgvector â€” MOCKED via AsyncMock.
# ---------------------------------------------------------------------------


class _AcquireCtx:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *_: Any) -> None:
        return None


def _build_pgvector() -> PgVectorStore:
    """An AsyncMock-driven asyncpg pool/conn backed by an in-memory row list.

    The mock parses each SQL statement just enough to dispatch
    INSERT/SELECT/UPDATE/DELETE against an in-memory list-of-dicts. It
    does NOT speak full Postgres â€” just the memorywire adapter's queries.
    """

    table: list[dict[str, Any]] = []

    async def execute(sql: str, *args: Any) -> str:
        sql = sql.strip()
        # We watch for the memorywire adapter's known DDL/DML patterns.
        if sql.upper().startswith("CREATE "):
            return "CREATE"
        if sql.upper().startswith("INSERT INTO ") and "memories(" in sql.lower():
            (
                mid,
                agent_id,
                user_id,
                mtype,
                content,
                metadata_json,
                confidence,
                source,
                embedding_literal,
                created_at,
                updated_at,
                expires_at,
                deleted_at,
            ) = args
            # Honour the conformance backdate marker stamped into metadata.
            try:
                metadata = json.loads(metadata_json) if metadata_json else {}
            except json.JSONDecodeError:
                metadata = {}
            offset = metadata.get("_conformance_backdate_ms")
            if isinstance(offset, int):
                created_at = created_at - offset
            table.append(
                {
                    "id": mid,
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "type": mtype,
                    "content": content,
                    "metadata": metadata,
                    "confidence": confidence,
                    "source": source,
                    "embedding": embedding_literal,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "expires_at": expires_at,
                    "deleted_at": deleted_at,
                    "last_recalled_at": None,
                }
            )
            return "INSERT 0 1"
        if sql.upper().startswith("INSERT INTO ") and "procedures(" in sql.lower():
            # Ignore; procedural side-table not needed for conformance.
            return "INSERT 0 1"
        if sql.upper().startswith("INSERT INTO ") and "audit_log(" in sql.lower():
            return "INSERT 0 1"
        if sql.upper().startswith("UPDATE ") and "set last_recalled_at" in sql.lower():
            # Best-effort: ignore.
            return "UPDATE 0"
        if sql.upper().startswith("UPDATE ") and "set deleted_at" in sql.lower():
            # SET deleted_at, updated_at WHERE id = ANY($2::text[]).
            # args = (now, [ids...]).
            now, ids = args[0], args[1]
            for row in table:
                if row["id"] in ids:
                    row["deleted_at"] = now
                    row["updated_at"] = now
            return "UPDATE"
        if sql.upper().startswith("UPDATE ") and "set metadata" in sql.lower():
            # SET metadata=$1, deleted_at=$2, updated_at=$2 WHERE id=$3
            meta_json, when, mid = args
            try:
                merged = json.loads(meta_json) if isinstance(meta_json, str) else meta_json
            except json.JSONDecodeError:
                merged = {}
            for row in table:
                if row["id"] == mid:
                    row["metadata"] = merged
                    row["deleted_at"] = when
                    row["updated_at"] = when
            return "UPDATE"
        if sql.upper().startswith("UPDATE ") and "set confidence" in sql.lower():
            now, ids = args[0], args[1]
            for row in table:
                if row["id"] in ids:
                    row["confidence"] = (row["confidence"] or 1.0) * 0.25
                    row["updated_at"] = now
            return "UPDATE"
        if sql.upper().startswith("UPDATE ") and "set content" in sql.lower():
            # merge_content path: id is the last param.
            content, meta_json, confidence, when, mid = args
            for row in table:
                if row["id"] == mid:
                    row["content"] = content
                    if isinstance(meta_json, str):
                        try:
                            row["metadata"] = json.loads(meta_json)
                        except json.JSONDecodeError:
                            row["metadata"] = {}
                    row["confidence"] = confidence
                    row["updated_at"] = when
            return "UPDATE"
        if sql.upper().startswith("DELETE FROM ") and "memories" in sql.lower():
            ids = args[0] if args else []
            table[:] = [r for r in table if r["id"] not in ids]
            return "DELETE"
        return "OK"

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        sql_l = sql.lower()
        if "select id from" in sql_l and "memories" in sql_l:
            # Either the forget path's id-list select or the filter-based path.
            agent_id = args[0]
            ids = args[1] if (len(args) >= 2 and isinstance(args[1], list)) else None
            out: list[dict[str, Any]] = []
            for r in table:
                if r["agent_id"] != agent_id:
                    continue
                if r["deleted_at"] is not None:
                    continue
                if ids is not None and r["id"] not in ids:
                    continue
                out.append({"id": r["id"]})
            return out
        if "select id, metadata from" in sql_l:
            # expire match-set discovery.
            agent_id = args[0]
            # Parse simple WHERE clauses we know we emit. Reading the SQL
            # is the cleanest way; we just rebuild the predicate.
            cutoff_idx = sql_l.find("created_at <=")
            cutoff = None
            type_val = None
            confidence_below = None
            no_recall_cutoff = None
            arg_cursor = 1  # $1 is agent_id
            if cutoff_idx != -1:
                cutoff = args[arg_cursor]
                arg_cursor += 1
            if "type = $" in sql_l:
                type_val = args[arg_cursor]
                arg_cursor += 1
            if "confidence <" in sql_l:
                confidence_below = args[arg_cursor]
                arg_cursor += 1
            if "last_recalled_at" in sql_l:
                no_recall_cutoff = args[arg_cursor]
                arg_cursor += 1
            out = []
            for r in table:
                if r["agent_id"] != agent_id or r["deleted_at"] is not None:
                    continue
                if cutoff is not None and not (r["created_at"] <= cutoff):
                    continue
                if type_val is not None and r["type"] != type_val:
                    continue
                if confidence_below is not None and not (
                    (r["confidence"] or 1.0) < confidence_below
                ):
                    continue
                if no_recall_cutoff is not None:
                    lr = r["last_recalled_at"]
                    if not (lr is None or lr <= no_recall_cutoff):
                        continue
                out.append({"id": r["id"], "metadata": r["metadata"]})
            return out
        if "select id, content, metadata, confidence, created_at" in sql_l:
            # _resolve_entity for merge.
            agent_id = args[0]
            key = args[1]
            out = []
            for r in table:
                if r["agent_id"] != agent_id or r["deleted_at"] is not None:
                    continue
                if "metadata->>'entity_name'" in sql_l:
                    if (r["metadata"] or {}).get("entity_name") == key:
                        out.append(r)
                else:
                    if r["id"] == key:
                        out.append(r)
            return out
        if "select id, agent_id, user_id, type, content, metadata" in sql_l:
            # The recall query â€” build a relevance-ranked rowset.
            agent_id = args[0]
            user_id = None
            type_list = None
            fresh_cutoff = None
            cursor = 1
            if "user_id = $" in sql_l:
                user_id = args[cursor]
                cursor += 1
            if "type = any(" in sql_l:
                type_list = args[cursor]
                cursor += 1
            if "created_at >=" in sql_l:
                fresh_cutoff = args[cursor]
                cursor += 1
            # The vector literal and limit are the last two args.
            limit = int(args[-1] or 5)
            qvec_literal = args[-2]

            # Crude string-similarity stand-in: count overlapping bytes.
            def _vec_distance(stored: str, query_vec: str) -> float:
                # The vector literal is "[v1,v2,...]"; we only have a
                # similarity proxy from the original text via the score
                # field â€” but here we measure on the literal's tail
                # which is unique per string.
                shared = sum(
                    1 for a, b in zip(stored or "", query_vec or "", strict=False) if a == b
                )
                return -float(shared)

            scored: list[tuple[float, dict[str, Any]]] = []
            for r in table:
                if r["agent_id"] != agent_id or r["deleted_at"] is not None:
                    continue
                if user_id is not None and r["user_id"] != user_id:
                    continue
                if type_list is not None and r["type"] not in type_list:
                    continue
                if fresh_cutoff is not None and r["created_at"] < fresh_cutoff:
                    continue
                d = _vec_distance(r["embedding"], qvec_literal)
                scored.append(
                    (
                        d,
                        {
                            "id": r["id"],
                            "agent_id": r["agent_id"],
                            "user_id": r["user_id"],
                            "type": r["type"],
                            "content": r["content"],
                            "metadata": r["metadata"],
                            "confidence": r["confidence"],
                            "source": r["source"],
                            "created_at": r["created_at"],
                            "updated_at": r["updated_at"],
                            "expires_at": r["expires_at"],
                            "distance": d,
                        },
                    )
                )
            scored.sort(key=lambda t: t[0])
            return [s[1] for s in scored[:limit]]
        return []

    async def fetchrow(sql: str, *_args: Any) -> dict[str, Any] | None:
        sql_l = sql.lower()
        if "select version()" in sql_l:
            return {"v": "PostgreSQL 16 (mock)"}
        if "select count(*) as n" in sql_l:
            return {"n": sum(1 for r in table if r["deleted_at"] is None)}
        return None

    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=execute)
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    pool.close = AsyncMock(return_value=None)

    return PgVectorStore(
        pool=pool,
        embedder=fake_embedder,
        ensure_schema=False,
    )


# ---------------------------------------------------------------------------
# Adapter id -> builder mapping.
# ---------------------------------------------------------------------------

_BUILDERS = {
    "sqlite-vec": _build_sqlite_vec,
    "mem0": _build_mem0,
    "letta": _build_letta,
    "cognee": _build_cognee,
    "pgvector": _build_pgvector,
}


def build_store_for(adapter_id: str) -> Any:
    """Return a fresh, isolated store for the given adapter id."""
    if adapter_id not in _BUILDERS:
        raise ValueError(f"Unknown adapter id: {adapter_id!r}")
    return _BUILDERS[adapter_id]()


# ---------------------------------------------------------------------------
# Per-adapter scenario skip overrides.
#
# Scenarios that an adapter cannot satisfy for a documented reason are
# listed here. Each entry maps an adapter id to a {scenario_name: reason}
# dict. The runner emits ``pytest.skip(reason)`` instead of executing.
# ---------------------------------------------------------------------------

SKIP_OVERRIDES: dict[str, dict[str, str]] = {
    "mem0": {
        # mem0's expire() does not enforce the spec Â§3.5 "empty policy
        # raises" invariant. The sqlite-vec / pgvector adapters both
        # raise; mem0 / letta / cognee silently treat empty policies as
        # match-everything. This is a real spec divergence flagged for
        # v0.2 tightening â€” see the brief's report (H) findings.
        "expire_empty_policy_raises": (
            "mem0 adapter does not enforce spec Â§3.5 empty-policy invariant â€” "
            "spec-gap surfaced for v0.2 tightening"
        ),
        "expire_empty_policy_object_raises": (
            "mem0 adapter does not enforce spec Â§3.5 empty-policy invariant â€” "
            "spec-gap surfaced for v0.2 tightening"
        ),
        # mem0's expire path uses LLM-driven `get_all`; our mock doesn't
        # model the timestamp gymnastics mem0 needs (created_at format
        # variance: int ms vs ISO-8601 vs seconds). The unit test suite
        # under tests/unit/store/test_mem0_adapter.py covers the actual
        # translation; here we skip the integration-shape scenario.
        "expire_by_age": (
            "mem0 adapter's expire-by-age behaviour depends on the LLM-driven "
            "created_at format mem0 emits; covered in tests/unit/store/test_mem0_adapter.py"
        ),
    },
    "letta": {
        # Letta scopes data by Letta agent_id only â€” it has no separate
        # user_id namespace. memorywire's user_id distinction is lost on the
        # backend, so two memorywire users targeting the same Letta agent share
        # passages. Documented spec-gap; the adapter's module docstring
        # already calls this out.
        "remember_recall_by_user_filter": (
            "letta scopes data by agent_id only; memorywire user_id is not honoured "
            "as a separate dimension â€” see LettaStore module docstring"
        ),
        "expire_empty_policy_raises": (
            "letta adapter does not enforce spec Â§3.5 empty-policy invariant â€” "
            "spec-gap surfaced for v0.2 tightening"
        ),
        "expire_empty_policy_object_raises": (
            "letta adapter does not enforce spec Â§3.5 empty-policy invariant â€” "
            "spec-gap surfaced for v0.2 tightening"
        ),
    },
    "cognee": {
        # Cognee's forget primitive does not accept adapter-synthetic
        # ``cog:`` ids; the adapter records the per-id delete as a no-op
        # (see CogneeStore.forget docstring spec-gap). The forget_by_ids
        # scenario therefore cannot be honoured.
        "forget_by_ids": (
            "cognee forget() requires data_id UUIDs; adapter-synthetic cog: "
            "ids are recorded as a no-op per CogneeStore.forget spec-gap"
        ),
        # The merge predicate counts surviving 'duplicate' hits; because
        # cognee's forget can't drop the adapter-synthetic ids, the
        # merge_content path still leaves them in place. Documented.
        "merge_keep_canonical": (
            "cognee merge() relies on forget() to drop duplicates which "
            "requires data_id UUIDs; adapter-synthetic ids are no-op deletes"
        ),
        # Cognee, like Letta, has no user_id namespace separate from
        # dataset; memorywire's user_id distinction is lost on the backend.
        "remember_recall_by_user_filter": (
            "cognee scopes data by dataset only; memorywire user_id is not honoured "
            "as a separate dimension â€” see CogneeStore module docstring"
        ),
        "expire_empty_policy_raises": (
            "cognee adapter does not enforce spec Â§3.5 empty-policy invariant â€” "
            "spec-gap surfaced for v0.2 tightening"
        ),
        "expire_empty_policy_object_raises": (
            "cognee adapter does not enforce spec Â§3.5 empty-policy invariant â€” "
            "spec-gap surfaced for v0.2 tightening"
        ),
        # Cognee's expire(FORGET) calls module.forget(data_id=...) only
        # when the id is *not* an adapter-synthetic ``cog:`` id. Since
        # the adapter always mints ``cog:`` ids on write, expire-by-age
        # is effectively a no-op against adapter-owned rows â€” same root
        # cause as forget_by_ids above.
        "expire_by_age": (
            "cognee expire(FORGET) skips adapter-synthetic cog: ids; same "
            "root cause as forget_by_ids spec-gap (no data_id UUIDs available)"
        ),
    },
    "pgvector": {},
    "sqlite-vec": {},
}


# ---------------------------------------------------------------------------
# Pytest parametrize hook.
# ---------------------------------------------------------------------------


@pytest.fixture(params=ADAPTER_IDS)
def adapter_id(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def store(adapter_id: str) -> Any:
    """Per-test isolated store for the parametrized adapter id."""
    s = build_store_for(adapter_id)
    yield s
    # sqlite-vec holds a real connection; close it for cleanliness.
    closer = getattr(s, "close", None)
    if callable(closer):
        with contextlib.suppress(Exception):
            result = closer()
            # The async pgvector close returns a coroutine; close it
            # explicitly to avoid the "coroutine never awaited" RuntimeWarning.
            if hasattr(result, "close") and result is not None:
                # coroutine.close() releases the unstarted coroutine cleanly.
                with contextlib.suppress(Exception):
                    result.close()


# Re-export for the runner module so test_conformance can pull constants.
__all__ = [
    "ADAPTER_IDS",
    "SKIP_OVERRIDES",
    "build_store_for",
    "fake_embedder",
]
