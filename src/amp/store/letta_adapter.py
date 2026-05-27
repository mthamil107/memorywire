"""Letta backend adapter for AMP (Phase 3).

This module exposes :class:`LettaStore`, a :class:`amp.store.MemoryStore`
implementation that translates AMP operations onto the official
``letta-client`` SDK. Letta (formerly MemGPT) is a long-running stateful
agent framework with native long-term ("archival") memory backed by
embeddings + a passage index.

Design notes
------------
* The ``letta-client`` package is an *optional extra* (``pip install
  agent-memory-protocol[letta]``). The import lives behind ``TYPE_CHECKING``
  and inside :meth:`LettaStore._get_client` so this module loads cleanly
  even without the SDK installed — unit tests use ``unittest.mock`` and
  never need the real SDK.
* The Letta client (``letta_client.Letta``) is **synchronous**. Every method
  on this adapter awaits ``anyio.to_thread.run_sync`` so the AMP async
  surface stays honest.
* Letta's archival memory is per-agent: every passage is scoped to a Letta
  ``agent_id``. AMP's own ``agent_id`` is a different namespace — typically
  a logical identifier for the calling application's agent. We require the
  caller to supply a Letta ``agent_id`` at construction time (either via
  the ``agent_id`` kwarg or in the URL).
* Letta's ``agents.passages.create`` accepts ``text``, ``tags``, and
  ``created_at`` — and crucially, **no free-form metadata field**. AMP
  fields that don't map onto those three (``confidence``, ``source``,
  ``expires_at``, caller metadata) are encoded as structured ``amp_*``
  tags (e.g. ``amp_type:semantic``, ``amp_conf:0.9``) so they survive the
  round trip. The recall path parses these tags back out symmetrically.
  See ``spec-gap`` comments throughout.
* Letta's archival API is delete-only (no soft-delete primitive). When
  ``hard_delete=False`` is requested we still perform a hard delete —
  same convention as :mod:`amp.store.mem0_adapter`. The audit log (Phase
  6) is the deviation record.
* No native merge primitive in Letta either; the adapter emulates merge
  by fetch + write + delete, mirroring the mem0 adapter.

URL anatomy
-----------
``letta://<host>[:<port>][?token=<api-key>&agent_id=<id>]``

* The host slot is the Letta server host. ``letta://default`` is a
  reserved alias for "use the SDK's environment-driven defaults" (i.e.
  ``LETTA_API_KEY`` / ``LETTA_BASE_URL`` env vars).
* ``agent_id`` MAY be supplied as a query parameter. If omitted at URL
  time it MUST be supplied via the constructor ``agent_id`` kwarg before
  any operation is invoked, otherwise a :class:`ValueError` is raised.
* ``token`` MAY be supplied as a query parameter and is forwarded as the
  ``api_key`` constructor kwarg to ``letta_client.Letta``.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import anyio.to_thread

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

if TYPE_CHECKING:  # pragma: no cover — typing-only.
    # The real client class is only imported for static analysis so the
    # module body remains import-safe without the ``letta`` extra installed.
    from letta_client import Letta as _LettaClient  # noqa: F401


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BACKEND_NAME = "letta"

# AMP fields encoded as Letta tags. ``key:value`` form keeps the tag set a
# flat list[str] (Letta's only supported shape) while still letting the
# recall path parse the original AMP fields back out. Choose short prefixes
# so we stay well under any per-tag length limit.
_TAG_PREFIX_TYPE = "amp_type:"  # e.g. "amp_type:semantic"
_TAG_PREFIX_CONF = "amp_conf:"  # e.g. "amp_conf:0.9"
_TAG_PREFIX_SOURCE = "amp_src:"  # e.g. "amp_src:onboarding-form"
_TAG_PREFIX_EXPIRES = "amp_exp:"  # epoch ms
_TAG_ARCHIVED = "amp_archived"  # bare marker tag, no value
# Free-form caller metadata is encoded as ``amp_kv:<key>=<value>`` tags.
_TAG_PREFIX_KV = "amp_kv:"


def _now_ms() -> int:
    """Return Unix epoch milliseconds — the AMP wire timestamp format."""
    return int(time.time() * 1000)


def _datetime_to_epoch_ms(value: Any) -> int | None:
    """Best-effort conversion of a Letta ``created_at`` value into epoch ms.

    Letta's Pydantic ``Passage`` model declares ``created_at`` as
    ``datetime``; the SDK occasionally hands back ISO-8601 strings or
    naive datetimes depending on the server. We handle each shape and
    return ``None`` when nothing recognisable can be extracted.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        # Treat naive datetimes as UTC — Letta server emits UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # 13-digit ints already look like ms; 10-digit are seconds.
        ivalue = int(value)
        return ivalue if ivalue >= 1_000_000_000_000 else ivalue * 1000
    if isinstance(value, str):
        candidate = value.rstrip("Z")
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    return None


def _tags_to_amp_overlay(tags: list[str] | None) -> dict[str, Any]:
    """Parse an AMP-tag list back into a flat overlay dict.

    Inverse of :func:`_amp_overlay_to_tags`. Unrecognised tags are
    ignored. The returned dict carries the original AMP-field names
    (``type``, ``confidence``, ``source``, ``expires_at``, ``archived``,
    plus user metadata keys) so the recall path can rebuild a
    :class:`RecallHit` from a Letta passage.
    """
    overlay: dict[str, Any] = {}
    if not tags:
        return overlay
    user_metadata: dict[str, Any] = {}
    for tag in tags:
        if not isinstance(tag, str):
            continue
        if tag == _TAG_ARCHIVED:
            overlay["archived"] = True
            continue
        if tag.startswith(_TAG_PREFIX_TYPE):
            overlay["type"] = tag[len(_TAG_PREFIX_TYPE) :]
            continue
        if tag.startswith(_TAG_PREFIX_CONF):
            try:
                overlay["confidence"] = float(tag[len(_TAG_PREFIX_CONF) :])
            except ValueError:
                continue
            continue
        if tag.startswith(_TAG_PREFIX_SOURCE):
            overlay["source"] = tag[len(_TAG_PREFIX_SOURCE) :]
            continue
        if tag.startswith(_TAG_PREFIX_EXPIRES):
            try:
                overlay["expires_at"] = int(tag[len(_TAG_PREFIX_EXPIRES) :])
            except ValueError:
                continue
            continue
        if tag.startswith(_TAG_PREFIX_KV):
            kv = tag[len(_TAG_PREFIX_KV) :]
            if "=" in kv:
                k, _, v = kv.partition("=")
                if k:
                    user_metadata[k] = v
            continue
        # Unrecognised tag — preserve in metadata so callers can read it
        # back, but namespaced under "tags" to avoid collisions.
        user_metadata.setdefault("_letta_tags", []).append(tag)
    if user_metadata:
        overlay["metadata"] = user_metadata
    return overlay


def _amp_overlay_to_tags(
    *,
    type: MemoryType,
    confidence: float | None,
    source: str | None,
    expires_at: int | None,
    metadata: dict[str, Any] | None,
    archived: bool = False,
) -> list[str]:
    """Encode the AMP overlay onto a flat tag list for Letta.

    Letta does not surface a free-form metadata blob on its archival API
    (only ``tags: list[str]``). Every AMP-specific field is therefore
    encoded as a ``key:value`` tag. Caller-supplied metadata is flattened
    via ``amp_kv:<key>=<value>`` entries — non-string values are coerced
    via ``str()``. spec-gap: structured (nested) metadata is *lossy* on
    the Letta backend; documented in the module docstring and recall
    rebuilds the values as strings.
    """
    tags: list[str] = [f"{_TAG_PREFIX_TYPE}{type.value}"]
    if confidence is not None:
        tags.append(f"{_TAG_PREFIX_CONF}{confidence}")
    if source is not None:
        tags.append(f"{_TAG_PREFIX_SOURCE}{source}")
    if expires_at is not None:
        tags.append(f"{_TAG_PREFIX_EXPIRES}{expires_at}")
    if archived:
        tags.append(_TAG_ARCHIVED)
    if metadata:
        for k, v in metadata.items():
            if not isinstance(k, str):
                continue
            # Skip keys that would collide with our own namespacing.
            if k.startswith("amp_") or k == "_letta_tags":
                continue
            tags.append(f"{_TAG_PREFIX_KV}{k}={v}")
    return tags


def _passage_to_dict(passage: Any) -> dict[str, Any]:
    """Coerce a Letta ``Passage`` (pydantic model) into a plain dict.

    Tests inject plain dicts; the real SDK hands back pydantic models. We
    accept both by trying ``model_dump`` first and falling back to attr
    access. Returns an empty dict when neither shape works — the caller
    is expected to defensively skip such rows.
    """
    if passage is None:
        return {}
    if isinstance(passage, dict):
        return passage
    dumper = getattr(passage, "model_dump", None)
    if callable(dumper):
        try:
            data = dumper()
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    result: dict[str, Any] = {}
    for attr in ("id", "text", "created_at", "tags", "metadata"):
        if hasattr(passage, attr):
            result[attr] = getattr(passage, attr)
    return result


class LettaStore:
    """AMP adapter for the official ``letta-client`` SDK.

    Parameters
    ----------
    client:
        An already-constructed ``letta_client.Letta`` (or compatible mock)
        instance. When ``None``, the adapter lazily constructs a real
        client on first use using ``base_url`` / ``token`` — lazy because
        the real SDK opens an HTTP session that we don't want at import
        time or during unit testing.
    agent_id:
        The Letta-side agent id every passage is scoped to. May be set
        post-construction by writing to :attr:`agent_id`; operations
        invoked without one raise :class:`ValueError`.
    base_url:
        Optional Letta server URL forwarded to the SDK on lazy
        construction. Ignored if ``client`` is supplied.
    token:
        Optional API key forwarded as ``api_key`` to ``letta_client.Letta``
        on lazy construction. Ignored if ``client`` is supplied.

    Notes
    -----
    The class is **not** declared as ``class LettaStore(MemoryStore):`` —
    :class:`amp.store.MemoryStore` is a ``@runtime_checkable`` Protocol;
    structural typing via ``isinstance`` works without inheritance
    (verified in ``tests/unit/store/test_letta_adapter.py``).
    """

    BACKEND_NAME = _BACKEND_NAME

    def __init__(
        self,
        client: Any | None = None,
        *,
        agent_id: str | None = None,
        base_url: str | None = None,
        token: str | None = None,
    ) -> None:
        self._client: Any | None = client
        self._agent_id: str | None = agent_id
        self._base_url: str | None = base_url
        self._token: str | None = token

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_url(cls, url: str, *, client: Any | None = None) -> LettaStore:
        """Construct a :class:`LettaStore` from a ``letta://<host>`` URL.

        See the module docstring for the URL anatomy. The reserved alias
        ``letta://default`` resolves to "use SDK environment defaults"
        (no explicit ``base_url`` forwarded).

        spec-gap: agent_id is *required* at the Letta layer but AMP's
        ``RememberRequest.agent_id`` is a different namespace (logical
        application-side identifier). Callers MUST surface a Letta-side
        agent id via the URL query string or the constructor kwarg before
        invoking operations.

        Parameters
        ----------
        url:
            The URL string, e.g. ``"letta://default?agent_id=ag-1"``.
        client:
            Optional pre-built client to inject (primarily for tests).
        """
        parsed = urlparse(url)
        if parsed.scheme != "letta":
            raise ValueError(
                f"LettaStore.from_url expects a 'letta://' scheme; got {parsed.scheme!r}"
            )

        # Parse the host slot — "default" is the env-driven alias; anything
        # else is treated as a server host. The port (if present) is folded
        # back into the base_url.
        host = parsed.hostname
        port = parsed.port
        base_url: str | None
        if host is None or host == "default":
            base_url = None
        else:
            base_url = f"http://{host}" + (f":{port}" if port is not None else "")

        # Optional query parameters: token, agent_id, base_url override.
        query = parse_qs(parsed.query) if parsed.query else {}

        def _first(key: str) -> str | None:
            values = query.get(key)
            return values[0] if values else None

        token = _first("token")
        agent_id = _first("agent_id")
        url_base_override = _first("base_url")
        if url_base_override:
            base_url = url_base_override

        return cls(client=client, agent_id=agent_id, base_url=base_url, token=token)

    def _get_client(self) -> Any:
        """Return the underlying Letta client, constructing on first use."""
        if self._client is not None:
            return self._client
        # Lazy import keeps the module import-safe without the letta extra.
        from letta_client import Letta

        kwargs: dict[str, Any] = {}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        if self._token is not None:
            kwargs["api_key"] = self._token
        self._client = Letta(**kwargs)
        return self._client

    @property
    def agent_id(self) -> str | None:
        """The Letta-side agent id every passage is scoped to."""
        return self._agent_id

    @agent_id.setter
    def agent_id(self, value: str | None) -> None:
        self._agent_id = value

    def _require_agent_id(self) -> str:
        """Return the Letta agent id or raise a clear error."""
        if not self._agent_id:
            raise ValueError(
                "LettaStore requires a Letta `agent_id` set via the constructor "
                "or the `agent_id` query parameter on letta:// URLs"
            )
        return self._agent_id

    # ------------------------------------------------------------------
    # Capability declaration
    # ------------------------------------------------------------------

    @property
    def capabilities(self) -> set[str]:
        """Capabilities Letta supports under AMP semantics.

        * ``semantic`` / ``episodic`` — Letta archival memory stores any
          string passage; AMP type tags are encoded in the passage tag
          list and round-tripped via :func:`_amp_overlay_to_tags`.
        * ``vector`` — Letta indexes every passage with an embedding and
          serves ANN search via ``agents.passages.search``.

        Letta does **not** offer a procedural-FSM contract under AMP
        semantics, graph hops, FTS-only search, last-recalled-at
        tracking, or HITL governance. Those are absent from the set so
        the router can skip the adapter for those operations.
        """
        return {Capability.SEMANTIC, Capability.EPISODIC, Capability.VECTOR}

    # ------------------------------------------------------------------
    # MemoryStore Protocol surface
    # ------------------------------------------------------------------

    async def remember(self, req: RememberRequest) -> RememberResponse:
        """Persist a single passage via ``agents.passages.create``.

        AMP fields Letta doesn't natively model (``type``, ``confidence``,
        ``source``, ``expires_at``, caller metadata) are encoded as
        ``amp_*`` tags. See :func:`_amp_overlay_to_tags`.

        spec-gap: Letta's create returns a *list* of Passage objects (the
        server may split content into multiple passages on chunking). AMP
        v0 only surfaces the first id as the canonical id, matching the
        mem0 adapter convention; v0.2 should let callers reason about all
        of them.

        Governance: when ``req.approval_required`` is True, the adapter
        short-circuits and returns ``pending_approval=True`` *without*
        calling Letta. Higher-layer governance is expected to replay the
        request to the adapter on approval.
        """
        # Governance short-circuit — never write to the backend when an
        # approval is pending; mirror the mem0 adapter's behaviour.
        if req.approval_required:
            return RememberResponse(
                id=f"pending:{uuid.uuid4()}",
                stored_at=_now_ms(),
                stores=[],
                pending_approval=True,
                approval_url=None,
            )

        agent_id = self._require_agent_id()
        tags = _amp_overlay_to_tags(
            type=req.type,
            confidence=req.confidence,
            source=req.source,
            expires_at=req.expires_at,
            metadata=req.metadata,
        )

        client = self._get_client()

        def _do_create() -> Any:
            return client.agents.passages.create(
                agent_id=agent_id,
                text=req.content,
                tags=tags,
            )

        response = await anyio.to_thread.run_sync(_do_create)

        # Normalise the response. The SDK returns ``List[Passage]``; tests
        # may inject plain dicts. Handle a single-passage shape too just
        # in case a future server build elects not to wrap it.
        results: list[Any]
        if isinstance(response, list):
            results = list(response)
        elif response is None:
            results = []
        else:
            results = [response]

        first_id: str | None = None
        if results:
            first = _passage_to_dict(results[0])
            candidate = first.get("id")
            if isinstance(candidate, str) and candidate:
                first_id = candidate

        # spec-gap: synthesise a ``letta:none:`` id when Letta returns no
        # passages so the AMP response shape stays valid.
        if first_id is None:
            first_id = f"letta:none:{uuid.uuid4()}"

        return RememberResponse(
            id=first_id,
            stored_at=_now_ms(),
            stores=[_BACKEND_NAME],
            pending_approval=False,
            approval_url=None,
        )

    async def recall(self, req: RecallRequest) -> RecallResponse:
        """Retrieve passages via ``agents.passages.search`` and map to AMP hits.

        Post-filters in Python on ``req.types`` (against the ``amp_type``
        tag) and ``req.fresher_than_days`` (against the passage's
        ``created_at``). Letta's search returns a list of
        ``{passage, score, metadata}`` objects — the inner ``passage``
        carries the original text and tags.

        spec-gap: ``fusion_used`` is reported as ``"rrf"`` (the AMP
        default) even though Letta's internal ranking is opaque. The
        field documents the *adapter's* intent, not a guarantee about
        what Letta did internally. Acceptable wart, mirrors the mem0
        adapter.
        """
        started_ms = _now_ms()
        agent_id = self._require_agent_id()
        top_k = req.k if req.k is not None else 5

        client = self._get_client()

        def _do_search() -> Any:
            return client.agents.passages.search(
                agent_id=agent_id,
                query=req.query,
                top_k=top_k,
            )

        response = await anyio.to_thread.run_sync(_do_search)

        # Normalise the response into a list of result objects.
        raw_results: list[Any]
        if isinstance(response, list):
            raw_results = list(response)
        elif response is None:
            raw_results = []
        else:
            raw_results = [response]

        type_filter: set[MemoryType] | None = None
        if req.types:
            type_filter = set(req.types)

        fresher_cutoff_ms: int | None = None
        if req.fresher_than_days is not None:
            fresher_cutoff_ms = _now_ms() - (req.fresher_than_days * 86_400_000)

        hits: list[RecallHit] = []
        for raw in raw_results:
            # Each item may be a pydantic ``PassageSearchResponseItem``
            # ({passage, score, metadata}) or a plain dict. Normalise.
            if hasattr(raw, "model_dump"):
                row = raw.model_dump()
            elif isinstance(raw, dict):
                row = raw
            else:
                continue

            passage_data = row.get("passage")
            # Some search shapes return a flat dict with text/tags
            # directly — accept that too via the row fallback.
            passage = row if passage_data is None else _passage_to_dict(passage_data)

            tags = passage.get("tags") if isinstance(passage, dict) else None
            overlay = _tags_to_amp_overlay(tags if isinstance(tags, list) else None)

            type_str = overlay.get("type", "semantic")
            try:
                amp_type = MemoryType(type_str)
            except ValueError:
                amp_type = MemoryType.SEMANTIC

            if type_filter is not None and amp_type not in type_filter:
                continue

            created_at_ms = _datetime_to_epoch_ms(
                passage.get("created_at") if isinstance(passage, dict) else None
            )

            # Honour fresher_than_days when both sides are populated.
            if (
                fresher_cutoff_ms is not None
                and created_at_ms is not None
                and created_at_ms < fresher_cutoff_ms
            ):
                continue

            # Letta returns a per-hit ``score`` (float in [0, 1] under
            # cosine similarity); default to 0.5 if missing.
            score_raw = row.get("score")
            if isinstance(score_raw, (int, float)) and not isinstance(score_raw, bool):
                score = float(score_raw)
            else:
                score = 0.5

            content = passage.get("text") if isinstance(passage, dict) else None
            if not isinstance(content, str):
                content = "" if content is None else str(content)

            mem_id = passage.get("id") if isinstance(passage, dict) else None
            if not isinstance(mem_id, str) or not mem_id:
                continue

            # Pull metadata from the overlay; merge in any inline
            # passage.metadata that Letta itself stamps. Keep this best
            # effort — Letta's metadata field is currently always empty,
            # but its presence in the schema means it MAY appear later.
            metadata: dict[str, Any] = {}
            overlay_meta = overlay.get("metadata")
            if isinstance(overlay_meta, dict):
                metadata.update(overlay_meta)
            inline_meta = passage.get("metadata") if isinstance(passage, dict) else None
            if isinstance(inline_meta, dict):
                metadata.update(inline_meta)
            # Re-expose the AMP overlay so consumers can read confidence
            # / source / expires_at without parsing tags themselves.
            for k in ("confidence", "source", "expires_at"):
                if k in overlay:
                    metadata[f"amp_{k}"] = overlay[k]

            hits.append(
                RecallHit(
                    id=mem_id,
                    type=amp_type,
                    content=content,
                    score=score,
                    metadata=metadata or None,
                    created_at=created_at_ms,
                    supporting=[],
                    source_store=_BACKEND_NAME,
                )
            )

        latency_ms = max(_now_ms() - started_ms, 0)
        fusion_used = req.fusion if req.fusion is not None else FusionAlgorithm.RRF
        return RecallResponse(
            results=hits,
            fusion_used=fusion_used,
            stores_queried=[_BACKEND_NAME],
            latency_ms=latency_ms,
        )

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        """Delete by explicit ids or by a flat filter.

        spec-gap: Letta only supports **hard delete**. When
        ``req.hard_delete`` is False (the AMP default), this adapter
        still performs a hard delete and surfaces the request's
        ``hard_delete`` value verbatim — same convention as the mem0
        adapter. Per spec §3.3 a request with neither ``ids`` nor
        ``filter`` is rejected as a no-scope mass-delete.
        """
        if not req.ids and not req.filter:
            raise ValueError("forget requires `ids` or `filter`")

        agent_id = self._require_agent_id()
        client = self._get_client()
        forgotten: list[str] = []

        # Path A — explicit ids.
        if req.ids:
            for mid in req.ids:

                def _do_delete(mid: str = mid) -> None:
                    client.agents.passages.delete(memory_id=mid, agent_id=agent_id)

                try:
                    await anyio.to_thread.run_sync(_do_delete)
                    forgotten.append(mid)
                except Exception:
                    # Treat per-id errors the same as mem0 — skip and
                    # continue. The audit log (Phase 6) tracks outcomes.
                    continue

        # Path B — filter-based delete. Letta has no server-side filter
        # primitive beyond agent_id, so resolve client-side via list().
        if req.filter:

            def _do_list() -> Any:
                return client.agents.passages.list(agent_id=agent_id, limit=1000)

            response = await anyio.to_thread.run_sync(_do_list)
            records = list(response) if isinstance(response, list) else []

            requested_type = req.filter.get("type")
            if isinstance(requested_type, MemoryType):
                requested_type = requested_type.value

            for record in records:
                passage = _passage_to_dict(record)
                if not passage:
                    continue
                overlay = _tags_to_amp_overlay(
                    passage.get("tags") if isinstance(passage.get("tags"), list) else None
                )
                # type filter
                if requested_type is not None and overlay.get("type") != requested_type:
                    continue
                # Generic key matches: walk the remaining filter keys against
                # the passage dict and the parsed AMP overlay/metadata.
                matched = True
                for fk, fv in req.filter.items():
                    if fk == "type":
                        continue
                    if fk in passage and passage[fk] == fv:
                        continue
                    if overlay.get(fk) == fv:
                        continue
                    overlay_meta = overlay.get("metadata")
                    if isinstance(overlay_meta, dict) and overlay_meta.get(fk) == str(fv):
                        # User metadata values are tag-encoded as strings;
                        # compare loosely.
                        continue
                    matched = False
                    break
                if not matched:
                    continue
                resolved_id = passage.get("id")
                if not isinstance(resolved_id, str):
                    continue
                if resolved_id in forgotten:
                    continue

                def _do_filter_delete(rid: str = resolved_id) -> None:
                    client.agents.passages.delete(memory_id=rid, agent_id=agent_id)

                try:
                    await anyio.to_thread.run_sync(_do_filter_delete)
                    forgotten.append(resolved_id)
                except Exception:
                    continue

        return ForgetResponse(
            forgotten_ids=forgotten,
            hard_delete=bool(req.hard_delete),
            stores=[ForgetStoreResult(store=_BACKEND_NAME, count=len(forgotten))],
            pending_approval=False,
            approval_url=None,
        )

    async def merge(self, req: MergeRequest) -> MergeResponse:
        """Collapse duplicate passages into one canonical passage.

        Letta has no native merge primitive. The strategy mirrors the
        mem0 adapter:

        1. ``list`` all passages for the agent and look up the canonical
           + duplicates in-memory.
        2. Apply the requested :class:`MergeStrategy` to produce a new
           content string and tag list.
        3. For ``merge_content`` / ``keep_highest_confidence`` write a
           new passage via ``create`` and delete the originals.
           For ``keep_canonical`` the canonical row is preserved verbatim
           and only the duplicates are dropped.

        spec-gap: ``merge_content`` joins content with ``" | "`` (the
        same compact separator the mem0 adapter picks); v0.2 will
        tighten this once the spec selects a normative separator.
        """
        agent_id = self._require_agent_id()
        client = self._get_client()
        strategy = req.strategy if req.strategy is not None else MergeStrategy.KEEP_CANONICAL

        def _do_list() -> Any:
            return client.agents.passages.list(agent_id=agent_id, limit=1000)

        listed = await anyio.to_thread.run_sync(_do_list)
        records_by_id: dict[str, dict[str, Any]] = {}
        if isinstance(listed, list):
            for rec in listed:
                p = _passage_to_dict(rec)
                rid = p.get("id")
                if isinstance(rid, str):
                    records_by_id[rid] = p

        canonical_record = records_by_id.get(req.canonical)
        duplicate_records: list[tuple[str, dict[str, Any] | None]] = [
            (dup_id, records_by_id.get(dup_id)) for dup_id in req.duplicates
        ]
        canonical_id: str = req.canonical

        if strategy is not MergeStrategy.KEEP_CANONICAL:
            # Both other strategies need to write a new canonical record.
            all_records: list[dict[str, Any]] = []
            if canonical_record is not None:
                all_records.append(canonical_record)
            for _, rec in duplicate_records:
                if rec is not None:
                    all_records.append(rec)

            if all_records:
                merged_content, merged_tags = self._apply_strategy(strategy, all_records)

                def _do_create() -> Any:
                    return client.agents.passages.create(
                        agent_id=agent_id,
                        text=merged_content,
                        tags=merged_tags,
                    )

                create_response = await anyio.to_thread.run_sync(_do_create)
                created_list: list[Any]
                if isinstance(create_response, list):
                    created_list = list(create_response)
                elif create_response is None:
                    created_list = []
                else:
                    created_list = [create_response]
                if created_list:
                    new_dict = _passage_to_dict(created_list[0])
                    if isinstance(new_dict.get("id"), str):
                        canonical_id = new_dict["id"]

                # Drop the original canonical when we wrote a new one.
                if canonical_record is not None and req.canonical != canonical_id:

                    def _drop_old_canonical(old: str = req.canonical) -> None:
                        with contextlib.suppress(Exception):
                            client.agents.passages.delete(memory_id=old, agent_id=agent_id)

                    await anyio.to_thread.run_sync(_drop_old_canonical)

        # Delete the duplicates in every strategy.
        merged_count = 0
        for dup_id, record in duplicate_records:
            if record is None:
                # Letta doesn't know this id; skip without counting (same
                # convention as mem0).
                continue

            def _do_delete(mid: str = dup_id) -> None:
                with contextlib.suppress(Exception):
                    client.agents.passages.delete(memory_id=mid, agent_id=agent_id)

            await anyio.to_thread.run_sync(_do_delete)
            merged_count += 1

        return MergeResponse(
            canonical=canonical_id,
            merged_count=merged_count,
            strategy_used=strategy,
            stores=[_BACKEND_NAME],
        )

    @staticmethod
    def _apply_strategy(
        strategy: MergeStrategy,
        records: list[dict[str, Any]],
    ) -> tuple[str, list[str]]:
        """Produce ``(content, tags)`` for the merged canonical passage."""

        # Build per-record overlays so we can reason about confidence and
        # type without re-parsing tags. Order by created_at ascending so
        # tie-breaking is stable.
        def _sort_key(rec: dict[str, Any]) -> int:
            return _datetime_to_epoch_ms(rec.get("created_at")) or 0

        ordered = sorted(records, key=_sort_key)
        overlays: list[dict[str, Any]] = []
        for rec in ordered:
            overlay = _tags_to_amp_overlay(
                rec.get("tags") if isinstance(rec.get("tags"), list) else None
            )
            overlays.append(overlay)

        # max(confidence) wins on merge_content per spec §3.4.
        max_conf: float | None = None
        for overlay in overlays:
            c = overlay.get("confidence")
            if isinstance(c, (int, float)) and (max_conf is None or c > max_conf):
                max_conf = float(c)

        if strategy is MergeStrategy.KEEP_HIGHEST_CONFIDENCE:
            best_idx = 0
            best_conf = float("-inf")
            for idx, overlay in enumerate(overlays):
                c = overlay.get("confidence")
                if isinstance(c, (int, float)) and float(c) > best_conf:
                    best_conf = float(c)
                    best_idx = idx
            best_record = ordered[best_idx]
            best_overlay = overlays[best_idx]
            content = str(best_record.get("text") or "")
            type_str = best_overlay.get("type", MemoryType.SEMANTIC.value)
            try:
                mtype = MemoryType(type_str)
            except ValueError:
                mtype = MemoryType.SEMANTIC
            tags = _amp_overlay_to_tags(
                type=mtype,
                confidence=best_overlay.get("confidence"),
                source=best_overlay.get("source"),
                expires_at=best_overlay.get("expires_at"),
                metadata=best_overlay.get("metadata")
                if isinstance(best_overlay.get("metadata"), dict)
                else None,
            )
            return content, tags

        # MERGE_CONTENT — join content with " | " and pick the latest
        # non-None type from the duplicates as the merged type.
        pieces: list[str] = []
        for rec in ordered:
            piece = str(rec.get("text") or "").strip()
            if piece:
                pieces.append(piece)
        # Use the most-recent overlay's type as the merged type.
        last_overlay = overlays[-1] if overlays else {}
        type_str = last_overlay.get("type", MemoryType.SEMANTIC.value)
        try:
            mtype = MemoryType(type_str)
        except ValueError:
            mtype = MemoryType.SEMANTIC
        # Union the user-metadata sub-dicts (last-write-wins).
        union_meta: dict[str, Any] = {}
        for overlay in overlays:
            om = overlay.get("metadata")
            if isinstance(om, dict):
                union_meta.update(om)
        tags = _amp_overlay_to_tags(
            type=mtype,
            confidence=max_conf,
            source=last_overlay.get("source"),
            expires_at=last_overlay.get("expires_at"),
            metadata=union_meta or None,
        )
        return " | ".join(pieces), tags

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        """Apply an expiration policy to a subset of passages.

        Letta does not track per-passage last-recalled-at, so a policy
        carrying ``no_recall_in_days`` is rejected (spec §3.5: "Backends
        that do not track last-recalled-at MUST return an error").

        Actions:

        * ``forget`` — ``agents.passages.delete`` per match.
        * ``archive`` — re-create the passage with the ``amp_archived``
          tag set, then delete the original. (Letta has no in-place
          tag-update primitive.) spec-gap.
        * ``demote`` — re-create with ``confidence * 0.25`` baked into
          the tag list, then delete the original. spec-gap: same
          "no in-place update" caveat.
        """
        policy = req.policy
        action = req.action if req.action is not None else ExpireAction.FORGET

        if policy is not None and policy.no_recall_in_days is not None:
            raise ValueError(
                "letta adapter does not track last-recalled-at; "
                "the `no_recall_in_days` policy is unsupported"
            )

        agent_id = self._require_agent_id()
        client = self._get_client()

        def _do_list() -> Any:
            return client.agents.passages.list(agent_id=agent_id, limit=1000)

        listed = await anyio.to_thread.run_sync(_do_list)
        records: list[dict[str, Any]] = []
        if isinstance(listed, list):
            for raw in listed:
                p = _passage_to_dict(raw)
                if p:
                    records.append(p)

        cutoff_ms: int | None = None
        if policy is not None and policy.older_than_days is not None:
            cutoff_ms = _now_ms() - (policy.older_than_days * 86_400_000)

        type_filter: MemoryType | None = policy.type if policy is not None else None
        confidence_below: float | None = policy.confidence_below if policy is not None else None

        matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for record in records:
            overlay = _tags_to_amp_overlay(
                record.get("tags") if isinstance(record.get("tags"), list) else None
            )

            if type_filter is not None and overlay.get("type") != type_filter.value:
                continue

            if cutoff_ms is not None:
                created_at_ms = _datetime_to_epoch_ms(record.get("created_at"))
                # Policies are ANDed per spec §3.5; skip rows without a
                # timestamp when the policy requires age.
                if created_at_ms is None or created_at_ms >= cutoff_ms:
                    continue

            if confidence_below is not None:
                conf = overlay.get("confidence")
                if not isinstance(conf, (int, float)) or float(conf) >= confidence_below:
                    continue

            matched.append((record, overlay))

        for record, overlay in matched:
            mid = record.get("id")
            if not isinstance(mid, str):
                continue
            content = str(record.get("text") or "")
            type_str = overlay.get("type", MemoryType.SEMANTIC.value)
            try:
                mtype = MemoryType(type_str)
            except ValueError:
                mtype = MemoryType.SEMANTIC

            if action is ExpireAction.FORGET:

                def _do_delete(mid: str = mid) -> None:
                    with contextlib.suppress(Exception):
                        client.agents.passages.delete(memory_id=mid, agent_id=agent_id)

                await anyio.to_thread.run_sync(_do_delete)
            elif action is ExpireAction.ARCHIVE:
                # spec-gap: Letta has no in-place update for passages, so
                # archive = re-create with the archived flag set then
                # delete the original. The passage id therefore changes
                # under archive — callers tracking ids over an archive
                # cycle must re-resolve. Documented in module docstring.
                new_tags = _amp_overlay_to_tags(
                    type=mtype,
                    confidence=overlay.get("confidence"),
                    source=overlay.get("source"),
                    expires_at=overlay.get("expires_at"),
                    metadata=overlay.get("metadata")
                    if isinstance(overlay.get("metadata"), dict)
                    else None,
                    archived=True,
                )

                def _do_archive(
                    mid: str = mid, content: str = content, new_tags: list[str] = new_tags
                ) -> None:
                    with contextlib.suppress(Exception):
                        client.agents.passages.create(
                            agent_id=agent_id, text=content, tags=new_tags
                        )
                        client.agents.passages.delete(memory_id=mid, agent_id=agent_id)

                await anyio.to_thread.run_sync(_do_archive)
            else:  # DEMOTE
                existing_conf = overlay.get("confidence")
                new_conf = (
                    float(existing_conf) * 0.25 if isinstance(existing_conf, (int, float)) else 0.25
                )
                new_tags = _amp_overlay_to_tags(
                    type=mtype,
                    confidence=new_conf,
                    source=overlay.get("source"),
                    expires_at=overlay.get("expires_at"),
                    metadata=overlay.get("metadata")
                    if isinstance(overlay.get("metadata"), dict)
                    else None,
                )

                def _do_demote(
                    mid: str = mid, content: str = content, new_tags: list[str] = new_tags
                ) -> None:
                    with contextlib.suppress(Exception):
                        client.agents.passages.create(
                            agent_id=agent_id, text=content, tags=new_tags
                        )
                        client.agents.passages.delete(memory_id=mid, agent_id=agent_id)

                await anyio.to_thread.run_sync(_do_demote)

        return ExpireResponse(
            matched_count=len(matched),
            action_taken=action,
            stores=[_BACKEND_NAME],
        )

    async def health(self) -> dict[str, Any]:
        """Probe the backend via the SDK's top-level ``health`` call.

        Returns ``{"status": "ok", "backend": "letta"}`` on success, or
        ``{"status": "error", "backend": "letta", "error": "<reason>"}``
        when the probe raises. We use ``client.health()`` (a no-args call
        on the Letta SDK) rather than listing passages so a misconfigured
        agent_id doesn't mask a healthy server.
        """
        try:
            client = self._get_client()
        except Exception as exc:
            return {"status": "error", "backend": _BACKEND_NAME, "error": str(exc)}

        def _probe() -> Any:
            return client.health()

        try:
            await anyio.to_thread.run_sync(_probe)
        except Exception as exc:
            return {"status": "error", "backend": _BACKEND_NAME, "error": str(exc)}
        return {"status": "ok", "backend": _BACKEND_NAME}


__all__ = ["LettaStore"]
