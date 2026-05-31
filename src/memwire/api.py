"""The :class:`Memory` facade â€” the public ergonomic entry point for memwire.

This module is intentionally a *thin* wrapper. All real fan-out logic lives
in :class:`memwire.router.MemoryRouter`; this class translates ergonomic
kwargs-based call signatures into pydantic ``*Request`` models, dispatches
them through the router, and reshapes the responses where the user-facing
contract diverges from the protocol contract (e.g. :meth:`recall` returns
the bare results list).

URL dispatch
------------
``stores`` accepts either pre-built :class:`MemoryStore` instances or URL
strings. The URL â†’ adapter mapping is centralized in :func:`_build_store`:

* ``sqlite-vec://<path>`` â†’ :class:`memwire.store.sqlite_vec.SqliteVecStore`
* ``mem0://<profile>``    â†’ :class:`memwire.store.mem0_adapter.Mem0Store`
* ``letta://<host>``      â†’ :class:`memwire.store.letta_adapter.LettaStore`

Unknown schemes raise :class:`ValueError`. This is the only place where
URL â†’ backend wiring lives; adapters under :mod:`memwire.store` are
responsible for parsing their own URL paths via ``from_url``.

Phase-6 hook (governance)
-------------------------
The ``governance`` constructor kwarg is accepted but inert at Phase 5 â€”
the governance client lands in Phase 6. The attribute is stored on the
instance so external code can inspect it; the router itself does not
consume it yet. See spec Â§6.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

from memwire.models import (
    ExpireAction,
    ExpirePolicy,
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    FusionAlgorithm,
    MemoryType,
    MergeRequest,
    MergeResponse,
    MergeStrategy,
    RecallHit,
    RecallRequest,
    RememberRequest,
    RememberResponse,
)
from memwire.router import MemoryRouter
from memwire.store.base import MemoryStore

if TYPE_CHECKING:  # pragma: no cover â€” typing-only.
    pass


# ---------------------------------------------------------------------------
# URL dispatch
# ---------------------------------------------------------------------------


def _build_store(url: str) -> MemoryStore:
    """Build a :class:`MemoryStore` adapter from a URL string.

    Recognised schemes:

    * ``sqlite-vec://...`` (also ``sqlite+vec``, ``sqlitevec``) â€” local
      SQLite + sqlite-vec store.
    * ``mem0://...`` â€” mem0 SDK adapter.
    * ``letta://...`` â€” Letta (letta-client) archival-memory adapter.
    * ``cognee://...`` â€” Cognee graph + vector adapter.
    * ``pgvector://...`` (also ``pgvector+postgres``) â€” Postgres + pgvector
      ANN store. ``pgvector://default`` reads ``DATABASE_URL``.

    Any other scheme raises :class:`ValueError`. The function does *not*
    validate that the optional dependencies for the chosen adapter are
    installed; the adapter constructor surfaces a clearer error if not.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme in {"sqlite-vec", "sqlite+vec", "sqlitevec"}:
        # Local import keeps the import graph shallow when only one
        # adapter is used and the other's optional deps are missing.
        from memwire.store.sqlite_vec import SqliteVecStore

        return SqliteVecStore.from_url(url)
    if scheme == "mem0":
        from memwire.store.mem0_adapter import Mem0Store

        return Mem0Store.from_url(url)
    if scheme == "letta":
        from memwire.store.letta_adapter import LettaStore

        return LettaStore.from_url(url)
    if scheme == "cognee":
        from memwire.store.cognee_adapter import CogneeStore

        return CogneeStore.from_url(url)
    if scheme in {"pgvector", "pgvector+postgres", "pgvector+postgresql"}:
        from memwire.store.pgvector_adapter import PgVectorStore

        return PgVectorStore.from_url(url)
    raise ValueError(f"unknown store URL scheme: {url}")


# ---------------------------------------------------------------------------
# Memory facade
# ---------------------------------------------------------------------------


class Memory:
    """Ergonomic facade over :class:`MemoryRouter`.

    Construct once with an ``agent_id`` and a list of stores; call
    :meth:`remember` / :meth:`recall` / :meth:`forget` / :meth:`merge` /
    :meth:`expire` with plain kwargs. The facade builds the pydantic
    request objects internally so callers don't have to.

    Parameters
    ----------
    agent_id:
        The agent identifier scoped to every operation routed through
        this instance. Required because every memwire request carries an
        ``agent_id``.
    stores:
        Non-empty sequence of either URL strings or pre-built
        :class:`MemoryStore` instances. URL strings are dispatched via
        :func:`_build_store`.
    fusion:
        Default fusion algorithm passed to the router. Per-call overrides
        on :meth:`recall` win when set.
    governance:
        Phase-6 hook. Accepted but currently inert â€” stored on the
        instance for future wiring. Pass ``None`` at Phase 5.
    write_policy:
        ``"all"`` (default) fans :meth:`remember` out to every capable
        child store. ``"primary_only"`` writes only to the first store.
    """

    def __init__(
        self,
        agent_id: str,
        stores: Sequence[str | MemoryStore],
        *,
        fusion: FusionAlgorithm = FusionAlgorithm.RRF,
        governance: Any | None = None,
        write_policy: Literal["all", "primary_only"] = "all",
    ) -> None:
        if not agent_id:
            raise ValueError("Memory requires a non-empty agent_id")
        if not stores:
            raise ValueError("Memory requires at least one store")

        built: list[MemoryStore] = []
        for entry in stores:
            if isinstance(entry, str):
                built.append(_build_store(entry))
            else:
                # Trust the caller â€” duck-typed against the Protocol. The
                # router does its own isinstance(MemoryStore, ...) check
                # only at construction-time validation if asked, but the
                # Protocol is structural so any compatible object works.
                built.append(entry)

        self._agent_id: str = agent_id
        self._governance: Any | None = governance
        self._router: MemoryRouter = MemoryRouter(
            built,
            default_fusion=fusion,
            write_policy=write_policy,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> str:
        """The agent_id scope for every operation on this facade."""
        return self._agent_id

    @property
    def router(self) -> MemoryRouter:
        """The underlying :class:`MemoryRouter`. Exposed for power users."""
        return self._router

    @property
    def capabilities(self) -> set[str]:
        """Union of capability strings across child stores."""
        return self._router.capabilities

    @property
    def governance(self) -> Any | None:
        """The governance client placeholder. Phase 5: always ``None``."""
        return self._governance

    # ------------------------------------------------------------------
    # remember
    # ------------------------------------------------------------------

    async def remember(
        self,
        content: str,
        *,
        type: MemoryType = MemoryType.SEMANTIC,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        confidence: float = 1.0,
        source: str | None = None,
        expires_at: int | None = None,
        approval_required: bool = False,
    ) -> RememberResponse:
        """Write a memory and return the protocol response.

        See spec Â§3.1 for the field contract.
        """
        req = RememberRequest(
            agent_id=self._agent_id,
            user_id=user_id,
            type=type,
            content=content,
            metadata=metadata,
            confidence=confidence,
            source=source,
            expires_at=expires_at,
            approval_required=approval_required,
        )
        return await self._router.remember(req)

    # ------------------------------------------------------------------
    # recall
    # ------------------------------------------------------------------

    async def recall(
        self,
        query: str,
        *,
        k: int = 5,
        types: Sequence[MemoryType] | None = None,
        hops: int = 0,
        fusion: FusionAlgorithm | None = None,
        filter: dict[str, Any] | None = None,
        fresher_than_days: int | None = None,
        user_id: str | None = None,
    ) -> list[RecallHit]:
        """Read memories matching ``query`` and return the bare hit list.

        Unlike the protocol's :class:`RecallResponse` shape, this method
        returns just the ``results`` list â€” callers usually want the rows,
        not the bookkeeping fields. Use ``self.router.recall()`` directly
        if you need ``latency_ms`` / ``stores_queried`` / ``fusion_used``.
        """
        req = RecallRequest(
            agent_id=self._agent_id,
            user_id=user_id,
            query=query,
            k=k,
            types=list(types) if types is not None else None,
            hops=hops,
            fusion=fusion,
            filter=filter,
            fresher_than_days=fresher_than_days,
        )
        response = await self._router.recall(req)
        return list(response.results)

    # ------------------------------------------------------------------
    # forget
    # ------------------------------------------------------------------

    async def forget(
        self,
        *,
        ids: Sequence[str] | None = None,
        filter: dict[str, Any] | None = None,
        hard_delete: bool = False,
        reason: str | None = None,
        user_id: str | None = None,
    ) -> ForgetResponse:
        """Delete memories by id list or filter.

        Spec Â§3.3: at least one of ``ids`` / ``filter`` is required.
        """
        if not ids and not filter:
            raise ValueError("forget requires `ids` or `filter`")
        req = ForgetRequest(
            agent_id=self._agent_id,
            user_id=user_id,
            ids=list(ids) if ids is not None else None,
            filter=filter,
            hard_delete=hard_delete,
            reason=reason,
        )
        return await self._router.forget(req)

    # ------------------------------------------------------------------
    # merge
    # ------------------------------------------------------------------

    async def merge(
        self,
        canonical: str,
        duplicates: Sequence[str],
        *,
        strategy: MergeStrategy = MergeStrategy.KEEP_CANONICAL,
    ) -> MergeResponse:
        """Collapse ``duplicates`` into ``canonical`` per ``strategy``."""
        req = MergeRequest(
            agent_id=self._agent_id,
            canonical=canonical,
            duplicates=list(duplicates),
            strategy=strategy,
        )
        return await self._router.merge(req)

    # ------------------------------------------------------------------
    # expire
    # ------------------------------------------------------------------

    async def expire(
        self,
        policy: dict[str, Any],
        *,
        action: ExpireAction = ExpireAction.FORGET,
    ) -> ExpireResponse:
        """Apply an expiry ``policy`` with the given ``action``."""
        # Validate policy fields through the pydantic model so bad keys
        # surface as a clean ValidationError rather than a silent no-op.
        expire_policy = ExpirePolicy(**policy)
        req = ExpireRequest(
            agent_id=self._agent_id,
            policy=expire_policy,
            action=action,
        )
        return await self._router.expire(req)

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """Return the router-shaped health dict (status + per-store rows)."""
        return await self._router.health()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close every child store that exposes a ``close`` method.

        Some adapters (notably :class:`SqliteVecStore`) hold connection
        resources; calling ``close()`` releases them. Adapters without a
        ``close`` method are skipped. Both sync and async ``close``
        signatures are honoured.
        """
        import inspect

        for store in self._router.stores:
            closer = getattr(store, "close", None)
            if closer is None:
                continue
            try:
                result = closer()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # Closing is best-effort â€” never raise out of ``close``.
                continue


__all__ = ["Memory", "_build_store"]
