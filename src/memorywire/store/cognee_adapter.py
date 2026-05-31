"""Cognee backend adapter for memorywire (Phase 3).

This module exposes :class:`CogneeStore`, a :class:`memorywire.store.MemoryStore`
implementation that translates memorywire operations onto the public ``cognee``
Python SDK. Cognee is a knowledge-graph-first memory layer that ingests
natural-language data via an ``add`` / ``cognify`` pipeline, builds a
graph + vector index, and serves both keyword and graph-completion
search.

Design notes
------------
* The ``cognee`` package is an *optional extra* (``pip install
  memorywire[cognee]``). The import lives behind
  ``TYPE_CHECKING`` and inside :meth:`CogneeStore._get_module` so this
  module loads cleanly even without cognee installed â€” unit tests mock
  the module via :mod:`unittest.mock` and never need the real SDK.
* Cognee's public surface (``cognee.add``, ``cognee.search``,
  ``cognee.prune.prune_data``, ``cognee.forget``) is **natively
  asynchronous**. Unlike the Letta and mem0 adapters, this adapter does
  not need ``anyio.to_thread.run_sync`` â€” every Cognee call is awaited
  directly.
* Cognee scopes data by *dataset name* (a string, defaulting to
  ``"main_dataset"`` on the SDK). The adapter pins a single dataset per
  store instance, supplied at construction time or via the URL host
  slot. memorywire's ``agent_id`` is a different namespace (logical
  application-side identifier) and is encoded into the ingested text
  prefix so :meth:`recall` can post-filter.
* Cognee's ``add`` accepts a *string* of arbitrary text. There is no
  free-form metadata field on the public surface (cognee builds its own
  metadata via LLM extraction inside ``cognify``). memorywire fields that don't
  map natively (``type``, ``confidence``, ``source``, ``expires_at``,
  caller metadata) are encoded as a **structured memorywire header line**
  prepended to the content so they survive the round trip. The header
  uses a JSON line so it parses unambiguously on recall. See
  ``spec-gap`` comments.
* Cognee's ``add`` is not a per-record write â€” it returns ``None`` and
  ingests the text into a pipeline. The adapter synthesises a content-
  hash id so memorywire's :class:`RememberResponse` shape stays valid. v0.2
  should let callers reason about pipeline-run ids returned from
  ``cognee.remember`` (which wraps ``add`` + ``cognify``).
* Cognee's :meth:`forget` only deletes by ``data_id`` + ``dataset`` or
  by full ``everything=True``. There is **no delete-by-content-id**
  primitive that maps cleanly onto memorywire's id-list / filter contract.
  When ``req.filter`` would otherwise force a dataset-wide prune the
  adapter raises :class:`ValueError`; the audit log records the
  deviation. spec-gap.
* No native merge primitive â€” emulated via add + delete pattern that
  mirrors the Letta adapter.
* Cognee does not track per-record last-recalled-at; :meth:`expire`
  rejects ``no_recall_in_days`` like the other adapters.

URL anatomy
-----------
``cognee://<dataset>``

* ``cognee://default`` is a reserved alias for the memorywire default
  dataset name (``"memorywire"``).
* Any other host slot is treated as the dataset name, e.g.
  ``cognee://team-knowledge`` â†’ ``dataset="team-knowledge"``.
* Query parameters are accepted but ignored at v0; richer per-URL
  config is deferred to v0.2.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from memorywire.models import (
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
from memorywire.store.base import Capability

if TYPE_CHECKING:  # pragma: no cover â€” typing-only.
    # The real module is only imported for static analysis so the module
    # body remains import-safe without the ``cognee`` extra installed.
    import cognee as _cognee  # noqa: F401


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BACKEND_NAME = "cognee"

# Default dataset name used when the URL alias is "default". Chosen so a
# bare ``cognee://default`` is scoped to the memorywire project and does not
# collide with Cognee's own out-of-the-box ``main_dataset``.
_DEFAULT_DATASET = "memorywire"

# The memorywire overlay is serialised as a single JSON line and prepended to the
# ingested content. The marker token is intentionally unusual so it does
# not collide with anything the LLM is likely to produce inside text. On
# recall the adapter splits on the first newline and parses the JSON
# payload back into a metadata overlay.
_AMP_HEADER_MARKER = "<AMP_META>"
_AMP_HEADER_END = "</AMP_META>"


def _now_ms() -> int:
    """Return Unix epoch milliseconds â€” the memorywire wire timestamp format."""
    return int(time.time() * 1000)


def _encode_amp_payload(
    *,
    amp_id: str,
    agent_id: str,
    user_id: str | None,
    type: MemoryType,
    confidence: float | None,
    source: str | None,
    expires_at: int | None,
    metadata: dict[str, Any] | None,
    created_at_ms: int,
    archived: bool = False,
) -> dict[str, Any]:
    """Build the structured memorywire overlay carried as a header line.

    Returned dict is JSON-serialisable; keys mirror the memorywire wire fields so
    :func:`_decode_amp_payload` can reconstruct a :class:`RecallHit`
    overlay without ambiguity. ``amp_id`` is a synthetic, deterministic
    identifier (sha1 of the trio (agent_id, content, now_ms)) so the
    remember response can return a stable id even though Cognee doesn't
    surface a per-record id from ``add``.
    """
    payload: dict[str, Any] = {
        "id": amp_id,
        "agent_id": agent_id,
        "type": type.value,
        "created_at": created_at_ms,
    }
    if user_id is not None:
        payload["user_id"] = user_id
    if confidence is not None:
        payload["confidence"] = confidence
    if source is not None:
        payload["source"] = source
    if expires_at is not None:
        payload["expires_at"] = expires_at
    if metadata:
        # Defensive copy so callers can mutate their input freely.
        payload["metadata"] = dict(metadata)
    if archived:
        payload["archived"] = True
    return payload


def _wrap_content(payload: dict[str, Any], content: str) -> str:
    """Prepend the memorywire overlay header to the raw content."""
    header = _AMP_HEADER_MARKER + json.dumps(payload, separators=(",", ":")) + _AMP_HEADER_END
    return header + "\n" + content


def _unwrap_content(blob: str) -> tuple[dict[str, Any], str]:
    """Split a Cognee text blob into ``(overlay, content)``.

    Inverse of :func:`_wrap_content`. When the blob does not carry an
    memorywire header (data ingested outside the adapter) returns an empty
    overlay and the blob unchanged so :meth:`recall` can still surface
    the row.
    """
    if not isinstance(blob, str) or not blob.startswith(_AMP_HEADER_MARKER):
        return {}, blob or ""
    end = blob.find(_AMP_HEADER_END)
    if end == -1:
        return {}, blob
    raw_json = blob[len(_AMP_HEADER_MARKER) : end]
    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        return {}, blob
    if not isinstance(payload, dict):
        return {}, blob
    rest = blob[end + len(_AMP_HEADER_END) :]
    # Strip the trailing newline added by _wrap_content if present.
    if rest.startswith("\n"):
        rest = rest[1:]
    return payload, rest


def _synth_amp_id(agent_id: str, content: str, *, salt: int | None = None) -> str:
    """Return a deterministic adapter-scoped id for a memory.

    Cognee's ``add`` does not surface a per-record id (the pipeline runs
    asynchronously across multiple chunks), so the adapter mints its own
    id at write time. Using sha1 over (agent_id, content, salt) keeps the
    id stable across retries of an identical write â€” useful for
    idempotency â€” and the salt fallback prevents collisions when callers
    intentionally re-remember the same fact.
    """
    salt_part = f":{salt}" if salt is not None else ""
    payload = f"{agent_id}|{content}{salt_part}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"cog:{digest[:16]}"


def _entry_to_overlay_and_text(entry: Any) -> tuple[dict[str, Any], str, float | None]:
    """Coerce a Cognee recall/search entry into ``(overlay, text, score)``.

    Cognee's recall path returns a discriminated union of response
    entries (:class:`ResponseQAEntry`, :class:`ResponseGraphEntry`, â€¦).
    Tests inject plain dicts. This helper normalises both shapes onto
    the memorywire overlay produced by :func:`_unwrap_content`.
    """
    if entry is None:
        return {}, "", None

    # Pydantic model â€” prefer model_dump.
    if hasattr(entry, "model_dump") and callable(entry.model_dump):
        try:
            data = entry.model_dump()
        except Exception:
            data = None
    else:
        data = None

    if data is None:
        if isinstance(entry, dict):
            data = entry
        else:
            # Last-ditch attribute scrape.
            data = {}
            for attr in ("text", "content", "answer", "score", "metadata", "_source"):
                if hasattr(entry, attr):
                    data[attr] = getattr(entry, attr)

    # Cognee's ResponseGraphEntry has ``text``; QAEntry has ``answer``;
    # GraphContextEntry has ``content``. Try each in turn.
    text_candidate = (
        (data.get("text") if isinstance(data, dict) else None)
        or (data.get("content") if isinstance(data, dict) else None)
        or (data.get("answer") if isinstance(data, dict) else None)
    )
    if not isinstance(text_candidate, str):
        text_candidate = "" if text_candidate is None else str(text_candidate)

    overlay, content = _unwrap_content(text_candidate)
    # If the row had inline metadata (Cognee's ``metadata`` field), merge
    # it into the overlay as a best-effort. The memorywire-header overlay wins
    # on conflicts because it carries adapter-stamped values.
    if isinstance(data, dict):
        inline_meta = data.get("metadata")
        if isinstance(inline_meta, dict):
            merged_meta = dict(inline_meta)
            existing = overlay.get("metadata")
            if isinstance(existing, dict):
                merged_meta.update(existing)
            overlay = {**overlay, "metadata": merged_meta} if merged_meta else overlay

    score_raw = data.get("score") if isinstance(data, dict) else None
    if isinstance(score_raw, (int, float)) and not isinstance(score_raw, bool):
        score: float | None = float(score_raw)
    else:
        score = None

    return overlay, content, score


class CogneeStore:
    """memorywire adapter for the ``cognee`` Python SDK.

    Parameters
    ----------
    client:
        An object that exposes the cognee module's public surface
        (``add``, ``search``, ``forget``, ``prune`` namespace, â€¦). When
        ``None``, the adapter lazily imports the real ``cognee`` module
        on first use. Tests inject a :class:`unittest.mock.MagicMock`
        and never touch the real SDK.
    dataset:
        Cognee dataset name scoped to this store instance. Defaults to
        the memorywire dataset alias ``"memorywire"``; pass another name for
        multi-tenant deployments.
    config:
        Optional dict applied to ``cognee.config`` on lazy construction.
        Forward-looking â€” unused at v0 but accepted so the constructor
        signature is stable. Ignored if ``client`` is supplied.

    Notes
    -----
    The class is **not** declared as ``class CogneeStore(MemoryStore):``
    â€” :class:`memorywire.store.MemoryStore` is a ``@runtime_checkable`` Protocol
    and structural typing via ``isinstance`` works without inheritance
    (verified in ``tests/unit/store/test_cognee_adapter.py``).
    """

    BACKEND_NAME = _BACKEND_NAME

    def __init__(
        self,
        client: Any | None = None,
        *,
        dataset: str = _DEFAULT_DATASET,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._client: Any | None = client
        self._dataset: str = dataset or _DEFAULT_DATASET
        self._config: dict[str, Any] | None = config

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_url(cls, url: str, *, client: Any | None = None) -> CogneeStore:
        """Construct a :class:`CogneeStore` from a ``cognee://<dataset>`` URL.

        See the module docstring for the URL anatomy. ``cognee://default``
        is the reserved alias for the memorywire default dataset name
        (``"memorywire"``); any other host slot is treated verbatim as the
        dataset name.

        Parameters
        ----------
        url:
            The URL string, e.g. ``"cognee://default"``.
        client:
            Optional pre-built client to inject (primarily for tests).
        """
        parsed = urlparse(url)
        if parsed.scheme != "cognee":
            raise ValueError(
                f"CogneeStore.from_url expects a 'cognee://' scheme; got {parsed.scheme!r}"
            )
        host = parsed.hostname
        dataset = _DEFAULT_DATASET if host is None or host == "default" else host
        return cls(client=client, dataset=dataset)

    def _get_module(self) -> Any:
        """Return the underlying cognee module, importing on first use."""
        if self._client is not None:
            return self._client
        # Lazy import keeps the module import-safe without the cognee extra.
        import cognee as _cognee_mod

        # Apply config knobs if supplied. The cognee.config namespace
        # exposes setter helpers; we forward any provided dict in a
        # best-effort loop so unknown keys raise the SDK's own error.
        if self._config:
            for key, value in self._config.items():
                setter = getattr(_cognee_mod.config, f"set_{key}", None)
                if callable(setter):
                    setter(value)
        self._client = _cognee_mod
        return self._client

    @property
    def dataset(self) -> str:
        """The Cognee dataset name scoped to this store instance."""
        return self._dataset

    # ------------------------------------------------------------------
    # Capability declaration
    # ------------------------------------------------------------------

    @property
    def capabilities(self) -> set[str]:
        """Capabilities Cognee supports under memorywire semantics.

        * ``semantic`` / ``episodic`` â€” Cognee ingests any natural-language
          text; memorywire type tags ride in the JSON header line and are
          round-tripped via :func:`_unwrap_content`.
        * ``vector`` â€” Cognee's pipeline builds vector embeddings via the
          configured provider (LanceDB by default).
        * ``graph`` â€” Cognee is graph-database-backed (Kuzu / Neo4j) and
          serves graph-completion search natively. This is the Cognee
          adapter's distinguishing capability.

        Cognee does **not** offer procedural-FSM contracts under memorywire
        semantics, FTS-only search, last-recalled-at tracking, or HITL
        governance. Those are deliberately absent from the set so the
        router can skip the adapter for those operations.
        """
        return {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.VECTOR,
            Capability.GRAPH,
        }

    # ------------------------------------------------------------------
    # MemoryStore Protocol surface
    # ------------------------------------------------------------------

    async def remember(self, req: RememberRequest) -> RememberResponse:
        """Persist a single memory via Cognee's ``add`` pipeline.

        memorywire fields Cognee doesn't natively model (``type``,
        ``confidence``, ``source``, ``expires_at``, ``agent_id``, caller
        metadata) are wrapped in a JSON header line prepended to the
        ingested text. On recall the header is parsed back via
        :func:`_unwrap_content` so the original overlay is reconstructed.

        spec-gap: Cognee's ``add`` ingests asynchronously into a pipeline
        and returns no per-record id (it builds a graph over chunks
        instead). The adapter synthesises a stable ``cog:<sha1>`` id at
        write time and stashes it inside the memorywire header â€” :meth:`recall`
        surfaces this id verbatim so callers see a consistent identifier.

        Governance: when ``req.approval_required`` is True, the adapter
        short-circuits and returns ``pending_approval=True`` *without*
        calling Cognee. Higher-layer governance is expected to replay the
        request to the adapter on approval â€” same convention as the
        Letta / mem0 adapters.
        """
        # Governance short-circuit.
        if req.approval_required:
            return RememberResponse(
                id=f"pending:{uuid.uuid4()}",
                stored_at=_now_ms(),
                stores=[],
                pending_approval=True,
                approval_url=None,
            )

        created_at_ms = _now_ms()
        amp_id = _synth_amp_id(req.agent_id, req.content)
        payload = _encode_amp_payload(
            amp_id=amp_id,
            agent_id=req.agent_id,
            user_id=req.user_id,
            type=req.type,
            confidence=req.confidence,
            source=req.source,
            expires_at=req.expires_at,
            metadata=req.metadata,
            created_at_ms=created_at_ms,
        )
        wrapped = _wrap_content(payload, req.content)

        module = self._get_module()
        # Cognee's high-level ``remember`` runs add + cognify in one call;
        # fall back to the lower-level ``add`` if the SDK doesn't expose
        # ``remember`` (e.g. an older Cognee or a mock that only stubs
        # ``add``).
        remember_fn = getattr(module, "remember", None)
        if callable(remember_fn):
            await remember_fn(wrapped, dataset_name=self._dataset)
        else:
            await module.add(wrapped, dataset_name=self._dataset)

        return RememberResponse(
            id=amp_id,
            stored_at=created_at_ms,
            stores=[_BACKEND_NAME],
            pending_approval=False,
            approval_url=None,
        )

    async def recall(self, req: RecallRequest) -> RecallResponse:
        """Retrieve memories via Cognee's ``search``/``recall`` and map to memorywire hits.

        Uses Cognee's :class:`SearchType.GRAPH_COMPLETION` when no other
        signal is provided â€” the graph-completion path is the Cognee
        differentiator. Post-filters in Python on ``req.types`` (against
        the memorywire-header ``type``) and ``req.fresher_than_days`` (against
        the memorywire-header ``created_at``).

        spec-gap: ``fusion_used`` is reported as ``"rrf"`` even though
        Cognee runs its own opaque fusion across the graph + vector
        indexes. The field documents the *adapter's* intent. Same wart
        as the Letta/mem0 adapters.
        """
        started_ms = _now_ms()
        top_k = req.k if req.k is not None else 5

        module = self._get_module()
        # Prefer the v1 ``recall`` surface; fall back to ``search`` for
        # backwards compatibility / mocks that only stub ``search``.
        search_fn = getattr(module, "recall", None) or getattr(module, "search", None)
        if search_fn is None:
            raise RuntimeError("cognee module exposes neither `recall` nor `search`")

        # Resolve SearchType.GRAPH_COMPLETION via the module if available,
        # otherwise pass a plain string so mocks don't need to expose the
        # enum. The Cognee SDK accepts either form on its search path.
        search_type_enum = getattr(module, "SearchType", None)
        if search_type_enum is not None:
            query_type: Any = getattr(search_type_enum, "GRAPH_COMPLETION", "GRAPH_COMPLETION")
        else:
            query_type = "GRAPH_COMPLETION"

        response = await search_fn(
            req.query,
            query_type=query_type,
            datasets=[self._dataset],
            top_k=top_k,
        )

        # Normalise the response into a list of entry objects.
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
            overlay, content, score = _entry_to_overlay_and_text(raw)

            # Apply agent_id scoping. Records written by other agents
            # (or outside this adapter) carry no memorywire header â€” surface
            # them too so cross-agent recall remains possible, but only
            # if the request didn't pin types (the type filter implies
            # the caller wants adapter-owned rows).
            overlay_agent = overlay.get("agent_id")
            if overlay_agent is not None and req.agent_id and overlay_agent != req.agent_id:
                continue

            type_str = overlay.get("type", MemoryType.SEMANTIC.value)
            try:
                amp_type = MemoryType(type_str)
            except ValueError:
                amp_type = MemoryType.SEMANTIC

            if type_filter is not None and amp_type not in type_filter:
                continue

            created_at_ms = overlay.get("created_at") if isinstance(overlay, dict) else None
            if not isinstance(created_at_ms, int):
                created_at_ms = None

            if (
                fresher_cutoff_ms is not None
                and created_at_ms is not None
                and created_at_ms < fresher_cutoff_ms
            ):
                continue

            # spec-gap: Cognee's recall/search rows surface a numeric
            # ``score`` on graph entries but not on QA entries. Default
            # to 0.5 (mid-range, mirroring the Letta adapter) when
            # missing so downstream fusion is well-defined.
            row_score = 0.5 if score is None else float(score)

            mem_id = overlay.get("id")
            if not isinstance(mem_id, str) or not mem_id:
                # No adapter-stamped id â€” synthesise a deterministic one
                # from the content so the recall response is still
                # well-formed. Downstream callers can detect the
                # ``cog:nohdr:`` prefix and treat it as advisory only.
                mem_id = f"cog:nohdr:{hashlib.sha1(content.encode('utf-8')).hexdigest()[:16]}"

            metadata: dict[str, Any] = {}
            overlay_meta = overlay.get("metadata")
            if isinstance(overlay_meta, dict):
                metadata.update(overlay_meta)
            # Re-expose the memorywire overlay so consumers can read confidence
            # / source / expires_at without parsing the header themselves.
            for k in ("confidence", "source", "expires_at"):
                if k in overlay:
                    metadata[f"amp_{k}"] = overlay[k]

            hits.append(
                RecallHit(
                    id=mem_id,
                    type=amp_type,
                    content=content,
                    score=row_score,
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

        spec-gap: Cognee's public ``forget`` only accepts ``data_id`` +
        ``dataset`` (UUIDs assigned by the ingestion pipeline) or
        ``everything=True``. There is **no delete-by-content-id**
        primitive â€” the synthetic ``cog:<sha1>`` ids the adapter mints
        on remember are *not* recognised by Cognee. To stay safe:

        * ``ids=[...]`` is accepted but each id is dispatched
          best-effort: if the id looks like a Cognee UUID it is passed
          straight through; if it is an adapter-synthetic ``cog:`` id
          the per-id delete is recorded as a no-op (audit log records
          the deviation) â€” spec-gap.
        * ``filter`` is honoured only when it contains a ``data_id``
          key whose value is a UUID; otherwise the request is rejected
          rather than mass-deleting the entire dataset.
        * Per spec Â§3.3 a request with neither ``ids`` nor ``filter``
          is rejected as a no-scope mass-delete.
        """
        if not req.ids and not req.filter:
            raise ValueError("forget requires `ids` or `filter`")

        module = self._get_module()
        forgotten: list[str] = []

        async def _delete_one(target: str) -> bool:
            """Attempt a single per-id delete via cognee.forget."""
            # Adapter-synthetic ids are not addressable on the Cognee
            # side. Surface this clearly via the audit log (Phase 6)
            # by returning False so the caller knows it was skipped.
            if target.startswith("cog:"):
                return False
            try:
                await module.forget(data_id=target, dataset=self._dataset)
                return True
            except Exception:
                # Treat per-id errors the same as the Letta/mem0
                # adapters â€” swallow and keep going.
                return False

        # Path A â€” explicit ids.
        if req.ids:
            for mid in req.ids:
                ok = await _delete_one(mid)
                if ok:
                    forgotten.append(mid)

        # Path B â€” filter-based delete. Cognee has no server-side
        # content-filter primitive, so we only honour the narrow
        # ``data_id`` shape; anything else is rejected (vs. silently
        # mass-deleting).
        if req.filter:
            target = req.filter.get("data_id")
            if not isinstance(target, str) or not target:
                raise ValueError(
                    "cognee filter-based forget only supports {'data_id': <uuid>}; "
                    "use ids=[...] for any other filter shape"
                )
            if target not in forgotten:
                ok = await _delete_one(target)
                if ok:
                    forgotten.append(target)

        return ForgetResponse(
            forgotten_ids=forgotten,
            hard_delete=bool(req.hard_delete),
            stores=[ForgetStoreResult(store=_BACKEND_NAME, count=len(forgotten))],
            pending_approval=False,
            approval_url=None,
        )

    async def merge(self, req: MergeRequest) -> MergeResponse:
        """Collapse duplicate memories into one canonical memory.

        Cognee has no native merge primitive. The strategy mirrors the
        Letta / mem0 adapters:

        1. Best-effort fetch via :meth:`recall` against the canonical id
           to resolve content + overlay.
        2. Apply the requested :class:`MergeStrategy` to produce a new
           content string and overlay.
        3. For ``merge_content`` / ``keep_highest_confidence`` write a
           new memory via :meth:`remember` and delete the originals.
           For ``keep_canonical`` the canonical row is preserved
           verbatim and only the duplicates are dropped.

        spec-gap: same caveat as the Letta adapter â€” the duplicates
        cannot actually be deleted from Cognee unless their original
        Cognee ``data_id`` UUIDs are supplied; adapter-synthetic
        ``cog:`` ids are recorded as a no-op delete. ``merged_count``
        reflects the *attempted* count.
        """
        module = self._get_module()
        strategy = req.strategy if req.strategy is not None else MergeStrategy.KEEP_CANONICAL

        # Resolve the canonical + duplicates via recall. Cognee has no
        # ``get_by_id`` primitive; we fish the rows out of a search
        # against the dataset and then post-filter on id. The query
        # text is empty-but-nonzero so the LLM-driven recall path has
        # something to chew on.
        async def _resolve(target_id: str) -> dict[str, Any] | None:
            search_fn = getattr(module, "search", None) or getattr(module, "recall", None)
            if search_fn is None:
                return None
            try:
                response = await search_fn(
                    target_id,
                    datasets=[self._dataset],
                    top_k=50,
                )
            except Exception:
                return None
            rows = response if isinstance(response, list) else [response] if response else []
            for raw in rows:
                overlay, content, _ = _entry_to_overlay_and_text(raw)
                if overlay.get("id") == target_id:
                    return {"overlay": overlay, "content": content}
            return None

        canonical_record = await _resolve(req.canonical)
        duplicate_records: list[tuple[str, dict[str, Any] | None]] = []
        for dup_id in req.duplicates:
            duplicate_records.append((dup_id, await _resolve(dup_id)))

        canonical_id: str = req.canonical

        if strategy is not MergeStrategy.KEEP_CANONICAL:
            all_records: list[dict[str, Any]] = []
            if canonical_record is not None:
                all_records.append(canonical_record)
            for _, rec in duplicate_records:
                if rec is not None:
                    all_records.append(rec)

            if all_records:
                merged_content, merged_overlay = self._apply_strategy(strategy, all_records)
                # Build a synthetic RememberRequest so we route through
                # the same path as the public remember() call.
                merged_type = (
                    MemoryType(merged_overlay.get("type", MemoryType.SEMANTIC.value))
                    if isinstance(merged_overlay.get("type"), str)
                    else MemoryType.SEMANTIC
                )
                merged_metadata = merged_overlay.get("metadata")
                if not isinstance(merged_metadata, dict):
                    merged_metadata = None
                synth_req = RememberRequest(
                    agent_id=req.agent_id,
                    type=merged_type,
                    content=merged_content,
                    confidence=merged_overlay.get("confidence"),
                    source=merged_overlay.get("source"),
                    expires_at=merged_overlay.get("expires_at"),
                    metadata=merged_metadata,
                )
                merge_response = await self.remember(synth_req)
                canonical_id = merge_response.id

                # Drop the original canonical row best-effort.
                if canonical_record is not None and req.canonical != canonical_id:
                    with contextlib.suppress(Exception):
                        if not req.canonical.startswith("cog:"):
                            await module.forget(data_id=req.canonical, dataset=self._dataset)

        # Delete the duplicates in every strategy. Adapter-synthetic
        # ``cog:`` ids are no-ops; count them as merged anyway because
        # the *intent* was honoured and the audit log records the gap.
        merged_count = 0
        for dup_id, record in duplicate_records:
            if record is None:
                continue
            with contextlib.suppress(Exception):
                if not dup_id.startswith("cog:"):
                    await module.forget(data_id=dup_id, dataset=self._dataset)
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
    ) -> tuple[str, dict[str, Any]]:
        """Produce ``(content, overlay)`` for the merged canonical row.

        Mirrors the Letta adapter's strategy logic: max(confidence) wins
        for ``MERGE_CONTENT``; pick the highest-confidence row verbatim
        for ``KEEP_HIGHEST_CONFIDENCE``. Inputs are the
        ``{"overlay": ..., "content": ...}`` shape returned by
        :meth:`merge`'s inline ``_resolve`` helper.
        """

        def _sort_key(rec: dict[str, Any]) -> int:
            created = rec.get("overlay", {}).get("created_at")
            return int(created) if isinstance(created, int) else 0

        ordered = sorted(records, key=_sort_key)

        max_conf: float | None = None
        for rec in ordered:
            c = rec.get("overlay", {}).get("confidence")
            if isinstance(c, (int, float)) and (max_conf is None or c > max_conf):
                max_conf = float(c)

        if strategy is MergeStrategy.KEEP_HIGHEST_CONFIDENCE:
            best = ordered[0]
            best_conf = float("-inf")
            for rec in ordered:
                c = rec.get("overlay", {}).get("confidence")
                if isinstance(c, (int, float)) and float(c) > best_conf:
                    best_conf = float(c)
                    best = rec
            content = str(best.get("content") or "")
            overlay = dict(best.get("overlay") or {})
            return content, overlay

        # MERGE_CONTENT â€” join content with " | " (same separator the
        # Letta/mem0 adapters pick). max(confidence) wins per spec Â§3.4.
        pieces: list[str] = []
        for rec in ordered:
            piece = str(rec.get("content") or "").strip()
            if piece:
                pieces.append(piece)
        last_overlay = ordered[-1].get("overlay", {}) if ordered else {}
        union_meta: dict[str, Any] = {}
        for rec in ordered:
            om = rec.get("overlay", {}).get("metadata")
            if isinstance(om, dict):
                union_meta.update(om)
        merged_overlay: dict[str, Any] = {
            "type": last_overlay.get("type", MemoryType.SEMANTIC.value),
        }
        if max_conf is not None:
            merged_overlay["confidence"] = max_conf
        if last_overlay.get("source") is not None:
            merged_overlay["source"] = last_overlay.get("source")
        if last_overlay.get("expires_at") is not None:
            merged_overlay["expires_at"] = last_overlay.get("expires_at")
        if union_meta:
            merged_overlay["metadata"] = union_meta
        return " | ".join(pieces), merged_overlay

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        """Apply an expiration policy to a subset of memories.

        Cognee does not track per-record last-recalled-at, so a policy
        carrying ``no_recall_in_days`` is rejected (spec Â§3.5: "Backends
        that do not track last-recalled-at MUST return an error").

        Actions:

        * ``forget`` â€” :meth:`forget` per matched row.
        * ``archive`` â€” re-create the row via :meth:`remember` with the
          memorywire-header ``archived`` flag set, then drop the original.
          spec-gap: same "no in-place update" caveat as Letta.
        * ``demote`` â€” re-create with ``confidence * 0.25`` baked in,
          then drop the original. spec-gap.

        spec-gap: matching rows are discovered via a bare ``search`` call
        with an empty-ish query â€” there is no ``list_all`` on Cognee's
        public surface. The discovery is best-effort and bounded by
        ``top_k=1000``. v0.2 should add a proper iterator API once the
        SDK exposes one.
        """
        policy = req.policy
        action = req.action if req.action is not None else ExpireAction.FORGET

        if policy is not None and policy.no_recall_in_days is not None:
            raise ValueError(
                "cognee adapter does not track last-recalled-at; "
                "the `no_recall_in_days` policy is unsupported"
            )

        module = self._get_module()
        search_fn = getattr(module, "search", None) or getattr(module, "recall", None)
        if search_fn is None:
            return ExpireResponse(
                matched_count=0,
                action_taken=action,
                stores=[_BACKEND_NAME],
            )

        # Best-effort fetch of the dataset's rows. The query string is
        # whatever the memorywire request supplies indirectly via the agent
        # scope; we pass the agent_id so cognee's search has *something*
        # to anchor on.
        try:
            response = await search_fn(
                req.agent_id,
                datasets=[self._dataset],
                top_k=1000,
            )
        except Exception:
            response = []

        raw_results: list[Any]
        if isinstance(response, list):
            raw_results = list(response)
        elif response is None:
            raw_results = []
        else:
            raw_results = [response]

        cutoff_ms: int | None = None
        if policy is not None and policy.older_than_days is not None:
            cutoff_ms = _now_ms() - (policy.older_than_days * 86_400_000)

        type_filter: MemoryType | None = policy.type if policy is not None else None
        confidence_below: float | None = policy.confidence_below if policy is not None else None

        matched: list[tuple[dict[str, Any], str]] = []
        for raw in raw_results:
            overlay, content, _ = _entry_to_overlay_and_text(raw)
            # Adapter-owned rows only â€” never expire random ingested
            # corpora that lack an memorywire header.
            mem_id = overlay.get("id")
            if not isinstance(mem_id, str) or not mem_id:
                continue
            # agent_id scoping.
            if overlay.get("agent_id") != req.agent_id:
                continue
            if type_filter is not None and overlay.get("type") != type_filter.value:
                continue
            if cutoff_ms is not None:
                created_at = overlay.get("created_at")
                if not isinstance(created_at, int) or created_at >= cutoff_ms:
                    continue
            if confidence_below is not None:
                conf = overlay.get("confidence")
                if not isinstance(conf, (int, float)) or float(conf) >= confidence_below:
                    continue
            matched.append((overlay, content))

        for overlay, content in matched:
            mem_id = overlay["id"]
            type_str = overlay.get("type", MemoryType.SEMANTIC.value)
            try:
                mtype = MemoryType(type_str)
            except ValueError:
                mtype = MemoryType.SEMANTIC

            if action is ExpireAction.FORGET:
                with contextlib.suppress(Exception):
                    if not mem_id.startswith("cog:"):
                        await module.forget(data_id=mem_id, dataset=self._dataset)
            elif action is ExpireAction.ARCHIVE:
                # spec-gap: no in-place update â€” re-write with archived
                # flag, then drop the original.
                archive_req = RememberRequest(
                    agent_id=req.agent_id,
                    type=mtype,
                    content=content,
                    confidence=overlay.get("confidence"),
                    source=overlay.get("source"),
                    expires_at=overlay.get("expires_at"),
                    metadata={
                        **(overlay.get("metadata") or {}),
                        "amp_archived": True,
                    },
                )
                with contextlib.suppress(Exception):
                    await self.remember(archive_req)
                with contextlib.suppress(Exception):
                    if not mem_id.startswith("cog:"):
                        await module.forget(data_id=mem_id, dataset=self._dataset)
            else:  # DEMOTE
                existing_conf = overlay.get("confidence")
                new_conf = (
                    float(existing_conf) * 0.25 if isinstance(existing_conf, (int, float)) else 0.25
                )
                demote_req = RememberRequest(
                    agent_id=req.agent_id,
                    type=mtype,
                    content=content,
                    confidence=new_conf,
                    source=overlay.get("source"),
                    expires_at=overlay.get("expires_at"),
                    metadata=overlay.get("metadata")
                    if isinstance(overlay.get("metadata"), dict)
                    else None,
                )
                with contextlib.suppress(Exception):
                    await self.remember(demote_req)
                with contextlib.suppress(Exception):
                    if not mem_id.startswith("cog:"):
                        await module.forget(data_id=mem_id, dataset=self._dataset)

        return ExpireResponse(
            matched_count=len(matched),
            action_taken=action,
            stores=[_BACKEND_NAME],
        )

    async def health(self) -> dict[str, Any]:
        """Probe the backend by checking module import + dataset listing.

        Returns ``{"status": "ok", "backend": "cognee", "dataset": ...}``
        on success, or ``{"status": "error", "backend": "cognee",
        "error": "<reason>"}`` when the probe raises. We avoid calling
        the search pipeline (which would require an LLM round-trip) and
        use ``cognee.datasets.list_datasets`` as the cheapest signal
        that the module loaded â€” when the SDK doesn't expose it we fall
        back to a bare "module imported" check.
        """
        try:
            module = self._get_module()
        except Exception as exc:
            return {"status": "error", "backend": _BACKEND_NAME, "error": str(exc)}

        # Try a cheap probe via the datasets namespace; fall through
        # to "module imported" if the surface is missing.
        datasets_ns = getattr(module, "datasets", None)
        if datasets_ns is not None:
            list_fn = getattr(datasets_ns, "list_datasets", None)
            if callable(list_fn):
                try:
                    result = list_fn()
                    # ``list_datasets`` is async in cognee 1.x; tests may
                    # mock it as a sync return.
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    return {
                        "status": "error",
                        "backend": _BACKEND_NAME,
                        "error": str(exc),
                    }
        return {
            "status": "ok",
            "backend": _BACKEND_NAME,
            "dataset": self._dataset,
        }


__all__ = ["CogneeStore"]
