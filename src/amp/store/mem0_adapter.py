"""mem0 backend adapter for AMP (Phase 3).

This module exposes :class:`Mem0Store`, a :class:`amp.store.MemoryStore`
implementation that translates AMP operations onto the public ``mem0``
Python SDK. mem0 is the "self-improving long-term memory" backend popular
with agent frameworks; it ships its own embedding/vector/LLM pipeline and
returns natural-language fact strings extracted from raw messages.

Design notes
------------
* The ``mem0`` package is an *optional extra* (``pip install
  agent-memory-protocol[mem0]``). The import lives behind ``TYPE_CHECKING``
  and inside :meth:`Mem0Store._get_client` so this module loads cleanly even
  without mem0 installed — unit tests use ``unittest.mock`` and never need
  the real SDK.
* mem0's public client is **synchronous**. Every method on this adapter
  awaits ``anyio.to_thread.run_sync`` so the AMP async surface stays honest.
* mem0 v2.x changed the signature of ``search``/``get_all`` to require a
  ``filters`` dict containing ``user_id``/``agent_id``/``run_id`` (instead
  of a top-level ``user_id`` kwarg) and renamed ``limit`` to ``top_k``. The
  adapter targets the v2.x API; older v0.1.x is not supported. See
  ``spec-gap`` comments throughout for divergences from the task contract.
* mem0 has no native ``merge`` primitive and only supports hard delete —
  both are emulated and flagged with ``spec-gap`` comments.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

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
    # The real mem0.Memory type is only imported for static analysis so the
    # module body remains import-safe without the ``mem0`` extra installed.
    from mem0 import Memory as _Mem0Memory  # noqa: F401


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BACKEND_NAME = "mem0"

# AMP fields that mem0 does not understand natively are flattened into
# metadata under these prefixed keys. Kept in one place so the recall path
# can read them back symmetrically.
_AMP_META_TYPE = "amp_type"
_AMP_META_CONFIDENCE = "amp_confidence"
_AMP_META_SOURCE = "amp_source"
_AMP_META_EXPIRES_AT = "amp_expires_at"
_AMP_META_ARCHIVED = "archived"


def _now_ms() -> int:
    """Return Unix epoch milliseconds — the AMP wire timestamp format."""
    return int(time.time() * 1000)


def _to_epoch_ms(value: Any) -> int | None:
    """Best-effort parse of mem0 ``created_at`` into Unix epoch ms.

    mem0 typically returns ISO-8601 strings (e.g. ``"2026-05-26T12:00:00"``)
    or integer epoch seconds. AMP requires Unix epoch *milliseconds*. Unknown
    shapes return ``None`` — the field is optional on :class:`RecallHit`.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # ``bool`` is a subclass of ``int`` in Python; reject explicitly.
        return None
    if isinstance(value, int):
        # Heuristic: 13-digit ints already look like ms; 10-digit are seconds.
        return value if value >= 1_000_000_000_000 else value * 1000
    if isinstance(value, float):
        return int(value * 1000) if value < 1_000_000_000_000 else int(value)
    if isinstance(value, str):
        # Try plain integer first.
        try:
            iv = int(value)
        except ValueError:
            iv = None
        if iv is not None:
            return iv if iv >= 1_000_000_000_000 else iv * 1000
        # Fall back to fromisoformat for ISO-8601 strings.
        from datetime import datetime

        candidate = value.rstrip("Z")
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        return int(dt.timestamp() * 1000)
    return None


class Mem0Store:
    """AMP adapter for the ``mem0`` Python SDK.

    Parameters
    ----------
    client:
        An already-constructed ``mem0.Memory`` (or compatible mock) instance.
        When ``None``, the adapter lazily constructs a default ``Memory()``
        on first use — lazy because mem0's default constructor may attempt
        to reach OpenAI for embeddings/LLM, which we don't want at import
        time or during unit testing.
    config:
        Optional dict forwarded to ``Memory.from_config(config)`` on lazy
        construction. Ignored if ``client`` is supplied.

    Notes
    -----
    The class is **not** declared as ``class Mem0Store(MemoryStore):`` —
    :class:`amp.store.MemoryStore` is a ``@runtime_checkable`` Protocol, and
    direct inheritance would force the more invasive ``ABC`` form. Structural
    typing via ``isinstance`` works either way (tested in
    ``tests/unit/store/test_mem0_adapter.py``).
    """

    BACKEND_NAME = _BACKEND_NAME

    def __init__(
        self,
        client: Any | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._client: Any | None = client
        self._config: dict[str, Any] | None = config

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_url(cls, url: str, *, client: Any | None = None) -> Mem0Store:
        """Construct a :class:`Mem0Store` from a ``mem0://<profile>`` URL.

        URL anatomy: ``mem0://<profile>`` where ``<profile>`` is a named
        configuration. For v0 only ``"default"`` is recognised (no config
        applied — the SDK's own defaults are used). Query parameters are
        accepted but ignored; richer config is deferred to v0.2.

        spec-gap: profile-to-config mapping beyond ``"default"`` is deferred
        to v0.2. Today every profile resolves to "use mem0's own defaults".

        Parameters
        ----------
        url:
            The URL string, e.g. ``"mem0://default"``.
        client:
            Optional pre-built client to inject (primarily for tests).
        """
        parsed = urlparse(url)
        if parsed.scheme != "mem0":
            raise ValueError(
                f"Mem0Store.from_url expects a 'mem0://' scheme; got {parsed.scheme!r}"
            )
        # The host slot carries the profile name in this URL form (e.g.
        # ``mem0://default`` → host == "default"). ``parsed.path`` is empty.
        # We accept any profile name without raising — unknown profiles fall
        # back to default behaviour (spec-gap above).
        return cls(client=client)

    def _get_client(self) -> Any:
        """Return the underlying mem0 client, constructing on first use."""
        if self._client is not None:
            return self._client
        # Lazy import keeps the module import-safe without the mem0 extra.
        from mem0 import Memory

        if self._config is not None:
            self._client = Memory.from_config(self._config)
        else:
            self._client = Memory()
        return self._client

    # ------------------------------------------------------------------
    # Capability declaration
    # ------------------------------------------------------------------

    @property
    def capabilities(self) -> set[str]:
        """Capabilities mem0 supports under AMP semantics.

        * ``semantic`` / ``episodic`` — mem0 stores arbitrary natural-language
          facts; we surface both via the ``amp_type`` metadata tag.
        * ``vector`` — mem0 ships its own vector store under the hood.

        mem0 does **not** offer procedural FSMs (it has a distinct
        ``procedural_memory`` mode that summarizes an agent's run, but that's
        not the AMP procedural-FSM contract — different shape), graph hops,
        FTS, last-recalled-at tracking, or HITL governance. Those are
        deliberately absent from the set so the router can skip mem0 for
        those operations.
        """
        return {Capability.SEMANTIC, Capability.EPISODIC, Capability.VECTOR}

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _principal_id(req: Any) -> str | None:
        """Return ``user_id`` if present, falling back to ``agent_id``.

        mem0 requires at least one of ``user_id``/``agent_id``/``run_id`` for
        every call. We pick the most-specific identifier consistently across
        write and read paths so memories are addressable on recall.
        """
        # Prefer the more specific user_id; fall back to agent_id.
        user_id = getattr(req, "user_id", None)
        if user_id:
            return str(user_id)
        agent_id = getattr(req, "agent_id", None)
        if agent_id:
            return str(agent_id)
        return None

    @staticmethod
    def _build_filters(req: Any) -> dict[str, Any]:
        """Build the ``filters`` dict mem0 v2.x requires.

        Always populates ``user_id`` (preferred) or ``agent_id`` so mem0's
        own validation (``filters must contain at least one of user_id,
        agent_id, run_id``) is satisfied.
        """
        filters: dict[str, Any] = {}
        user_id = getattr(req, "user_id", None)
        if user_id:
            filters["user_id"] = str(user_id)
        agent_id = getattr(req, "agent_id", None)
        if agent_id and "user_id" not in filters:
            filters["agent_id"] = str(agent_id)
        return filters

    @staticmethod
    def _record_matches_filter(record: dict[str, Any], flt: dict[str, Any]) -> bool:
        """Apply a flat AMP filter dict to a mem0 record returned by ``get_all``.

        Used by :meth:`forget` for filter-based deletes, since mem0 doesn't
        expose a server-side filter beyond entity-ids. Keys are matched
        against top-level mem0 fields first (``id``, ``memory``, ``user_id``,
        …), then against the record's nested ``metadata`` dict, with the
        special-case that the AMP ``type`` field maps to the
        ``amp_type`` metadata tag this adapter writes on remember.
        """
        metadata = record.get("metadata") or {}
        for key, expected in flt.items():
            if key == "type":
                actual = metadata.get(_AMP_META_TYPE)
                if isinstance(expected, MemoryType):
                    expected = expected.value
                if actual != expected:
                    return False
                continue
            if key in record:
                if record[key] != expected:
                    return False
                continue
            if metadata.get(key) != expected:
                return False
        return True

    # ------------------------------------------------------------------
    # MemoryStore Protocol surface
    # ------------------------------------------------------------------

    async def remember(self, req: RememberRequest) -> RememberResponse:
        """Persist a single memory via ``mem0.add``.

        AMP fields mem0 doesn't natively support (``type``, ``confidence``,
        ``source``, ``expires_at``) are flattened into the metadata blob
        under ``amp_*`` keys so they survive the round-trip.

        spec-gap: mem0 ``add`` can split one input into multiple memories
        (returns ``{"results": [...]}``). AMP v0 only surfaces the *first*
        memory's id as the canonical id. Multi-memory writes are an open
        question for v0.2.

        Governance: when ``req.approval_required`` is True, the adapter
        short-circuits and returns ``pending_approval=True`` *without*
        calling mem0. Higher-layer governance is expected to replay the
        request to the adapter on approval.
        """
        # Governance short-circuit — never write to the backend when an
        # approval is pending. Higher layers will replay on approve. The
        # synthetic ``pending:`` id is a placeholder because pydantic
        # requires ``id`` to be non-empty (min_length=1); callers gate on
        # ``pending_approval`` rather than parsing the id.
        if req.approval_required:
            return RememberResponse(
                id=f"pending:{uuid.uuid4()}",
                stored_at=_now_ms(),
                stores=[],
                pending_approval=True,
                approval_url=None,
            )

        principal = self._principal_id(req)
        if principal is None:
            # mem0 itself would raise here, but the AMP error is friendlier.
            raise ValueError("mem0 adapter requires either `user_id` or `agent_id` on the request")

        # Merge caller-supplied metadata with the AMP-specific overlay.
        # Caller metadata wins for non-amp keys; amp_* keys are always set
        # by this adapter so a malicious caller can't shadow them.
        combined_metadata: dict[str, Any] = {}
        if req.metadata:
            combined_metadata.update(req.metadata)
        combined_metadata[_AMP_META_TYPE] = req.type.value
        if req.confidence is not None:
            combined_metadata[_AMP_META_CONFIDENCE] = req.confidence
        if req.source is not None:
            combined_metadata[_AMP_META_SOURCE] = req.source
        if req.expires_at is not None:
            combined_metadata[_AMP_META_EXPIRES_AT] = req.expires_at

        client = self._get_client()
        # Pick the entity kwarg consistent with _principal_id (user > agent).
        add_kwargs: dict[str, Any] = {"metadata": combined_metadata}
        if req.user_id:
            add_kwargs["user_id"] = req.user_id
        else:
            add_kwargs["agent_id"] = req.agent_id

        def _do_add() -> Any:
            return client.add(req.content, **add_kwargs)

        response = await anyio.to_thread.run_sync(_do_add)

        # mem0 v1.1+ returns {"results": [{"id": ..., "memory": ..., "event": ...}, ...]}.
        # Older releases returned a bare list. Handle both shapes defensively.
        results: list[dict[str, Any]]
        if isinstance(response, dict):
            results = list(response.get("results") or [])
        elif isinstance(response, list):
            results = list(response)
        else:
            results = []

        # spec-gap: surface the first id only. mem0 may have split content
        # into multiple records; the remaining ids are silently dropped at
        # v0. v0.2 should return all ids and let callers reason about them.
        first_id: str | None = None
        if results:
            candidate = results[0].get("id") if isinstance(results[0], dict) else None
            if isinstance(candidate, str) and candidate:
                first_id = candidate

        # spec-gap: mem0's ``add`` can return zero memories when the LLM
        # decides nothing was worth extracting (``infer=True`` is the
        # default). We synthesise a ``mem0:none:`` id in that case so the
        # AMP response shape stays valid; downstream audit can detect the
        # prefix and skip retrieval.
        if first_id is None:
            first_id = f"mem0:none:{uuid.uuid4()}"

        return RememberResponse(
            id=first_id,
            stored_at=_now_ms(),
            stores=[_BACKEND_NAME],
            pending_approval=False,
            approval_url=None,
        )

    async def recall(self, req: RecallRequest) -> RecallResponse:
        """Retrieve memories via ``mem0.search`` and map to AMP hits.

        Post-filters in Python on ``req.types`` (against ``amp_type``) and
        ``req.fresher_than_days`` (against mem0's ``created_at`` if present;
        skipped silently when the backend omits the field).

        spec-gap: ``fusion_used`` is reported as ``"rrf"`` even though mem0
        runs its own internal fusion — the field documents the *adapter's*
        intent, not a guarantee about what mem0 did internally. Acceptable
        wart.
        """
        started_ms = _now_ms()
        principal = self._principal_id(req)
        if principal is None:
            raise ValueError("mem0 adapter requires either `user_id` or `agent_id` on the request")

        filters = self._build_filters(req)
        # mem0 uses ``top_k`` (default 20); AMP uses ``k`` (default per spec
        # is 5 but pydantic allows None). Pick a sensible default.
        top_k = req.k if req.k is not None else 5

        client = self._get_client()

        def _do_search() -> Any:
            return client.search(req.query, top_k=top_k, filters=filters)

        response = await anyio.to_thread.run_sync(_do_search)

        # Normalise the response into a list of result dicts.
        raw_results: list[dict[str, Any]]
        if isinstance(response, dict):
            raw_results = list(response.get("results") or [])
        elif isinstance(response, list):
            raw_results = list(response)
        else:
            raw_results = []

        type_filter: set[MemoryType] | None = None
        if req.types:
            type_filter = set(req.types)

        # Pre-compute the cut-off for fresher_than_days, if present.
        fresher_cutoff_ms: int | None = None
        if req.fresher_than_days is not None:
            fresher_cutoff_ms = _now_ms() - (req.fresher_than_days * 86_400_000)

        hits: list[RecallHit] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            metadata = raw.get("metadata") or {}

            # Resolve the AMP type from the metadata tag the adapter writes
            # on remember. Records written outside the adapter are assumed
            # semantic — mem0's default mode is declarative-fact extraction.
            type_str = metadata.get(_AMP_META_TYPE) or "semantic"
            try:
                amp_type = MemoryType(type_str)
            except ValueError:
                amp_type = MemoryType.SEMANTIC

            if type_filter is not None and amp_type not in type_filter:
                continue

            created_at_raw = raw.get("created_at") or metadata.get("created_at")
            created_at_ms = _to_epoch_ms(created_at_raw)

            # Drop stale records if a freshness window was requested. When
            # the backend omits ``created_at`` we cannot honour the filter;
            # skipping silently rather than dropping the row matches the
            # spec section-3.5 stance for missing recall-tracking ("backends
            # that don't track X return an error") — but for *recall* we
            # treat it as best-effort. spec-gap: documented in the module
            # docstring.
            if (
                fresher_cutoff_ms is not None
                and created_at_ms is not None
                and created_at_ms < fresher_cutoff_ms
            ):
                continue

            score = raw.get("score")
            if not isinstance(score, (int, float)):
                score = 0.0
            content = raw.get("memory") or raw.get("data") or ""
            mem_id = raw.get("id") or ""
            if not isinstance(mem_id, str) or not mem_id:
                continue

            hits.append(
                RecallHit(
                    id=mem_id,
                    type=amp_type,
                    content=str(content),
                    score=float(score),
                    metadata=dict(metadata) if metadata else None,
                    created_at=created_at_ms,
                    supporting=[],
                    source_store=_BACKEND_NAME,
                )
            )

        latency_ms = max(_now_ms() - started_ms, 0)
        # The adapter declares "rrf" because that's the documented fusion
        # behaviour at the AMP-router layer; mem0's internal pipeline is
        # opaque. See spec-gap in the method docstring.
        fusion_used = req.fusion if req.fusion is not None else FusionAlgorithm.RRF
        return RecallResponse(
            results=hits,
            fusion_used=fusion_used,
            stores_queried=[_BACKEND_NAME],
            latency_ms=latency_ms,
        )

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        """Delete by explicit ids or by a flat filter.

        spec-gap: mem0 only supports **hard delete**. When ``req.hard_delete``
        is False (the AMP default), this adapter still performs a hard delete
        and surfaces ``hard_delete=False`` in the response only because the
        caller asked for soft. Higher-layer audit logging should record the
        deviation. Per spec §3.3 a request with neither ``ids`` nor
        ``filter`` is rejected as a no-scope mass-delete.
        """
        if not req.ids and not req.filter:
            raise ValueError("forget requires `ids` or `filter`")

        client = self._get_client()
        forgotten: list[str] = []

        # Path A — explicit ids.
        if req.ids:
            for mid in req.ids:

                def _do_delete(mid: str = mid) -> None:
                    client.delete(mid)

                try:
                    await anyio.to_thread.run_sync(_do_delete)
                    forgotten.append(mid)
                except Exception:
                    # mem0 raises ``ValueError`` for unknown ids; skip and
                    # continue. The audit log (Phase 6) tracks per-id outcomes.
                    continue

        # Path B — filter-based delete. mem0 has no server-side filter
        # primitive beyond entity-ids, so resolve client-side via get_all.
        if req.filter:
            principal_filters = self._build_filters(req)
            # The filter dict may also specify a user_id/agent_id beyond the
            # request's; merge so callers can scope a delete cross-user.
            for key in ("user_id", "agent_id", "run_id"):
                if key in req.filter:
                    principal_filters[key] = req.filter[key]
            # If we still have no principal we can't query mem0 — raise so
            # the caller doesn't accidentally mass-delete.
            if not principal_filters:
                raise ValueError(
                    "mem0 filter-based forget requires `user_id` or `agent_id` "
                    "either on the request or inside the filter"
                )

            def _do_get_all() -> Any:
                return client.get_all(filters=principal_filters, top_k=1000)

            response = await anyio.to_thread.run_sync(_do_get_all)
            records = (
                response.get("results", []) if isinstance(response, dict) else list(response or [])
            )

            for record in records:
                if not isinstance(record, dict):
                    continue
                if not self._record_matches_filter(record, req.filter):
                    continue
                resolved_id = record.get("id")
                if not isinstance(resolved_id, str):
                    continue
                if resolved_id in forgotten:
                    continue

                def _delete_resolved(rid: str = resolved_id) -> None:
                    client.delete(rid)

                try:
                    await anyio.to_thread.run_sync(_delete_resolved)
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
        """Collapse duplicate records into one canonical record.

        mem0 has no native merge primitive. Strategy:

        1. Fetch each duplicate via ``client.get(id)``; also fetch the
           canonical when its id resolves (canonical may be a *name* rather
           than an id — see spec §3.4 — in which case the lookup is
           best-effort).
        2. Apply the requested ``MergeStrategy`` to produce a new content
           string and confidence.
        3. For ``merge_content`` / ``keep_highest_confidence`` write a new
           memory via ``client.add`` and delete the originals.
           For ``keep_canonical`` the canonical row is preserved verbatim
           and only the duplicates are dropped.

        spec-gap: ``merge_content`` joins content fields with ``" | "``
        rather than ``"\\n"`` (the spec §3.4 Editor's note says "MAY
        concatenate ... with a newline separator" — MAY, not MUST). The
        " | " separator keeps merged content compact for the LLM context
        window. v0.2 will tighten this.
        """
        client = self._get_client()
        strategy = req.strategy if req.strategy is not None else MergeStrategy.KEEP_CANONICAL

        # Fetch all the duplicate records up front so we have content +
        # metadata available for the merge strategies that need them.
        async def _fetch(mid: str) -> dict[str, Any] | None:
            def _do_get() -> Any:
                try:
                    return client.get(mid)
                except Exception:
                    return None

            return await anyio.to_thread.run_sync(_do_get)

        duplicate_records: list[tuple[str, dict[str, Any] | None]] = []
        for dup_id in req.duplicates:
            record = await _fetch(dup_id)
            duplicate_records.append((dup_id, record))

        canonical_record: dict[str, Any] | None = await _fetch(req.canonical)
        canonical_id: str = req.canonical

        if strategy is MergeStrategy.KEEP_CANONICAL:
            # Canonical row stays untouched; just drop the duplicates.
            pass
        else:
            # Both other strategies need to write a new canonical record.
            # Choose content + confidence per strategy.
            all_records: list[dict[str, Any]] = []
            if canonical_record is not None:
                all_records.append(canonical_record)
            for _, rec in duplicate_records:
                if rec is not None:
                    all_records.append(rec)

            if not all_records:
                # Nothing fetched (all ids missing); fall through to delete
                # attempts and return a best-effort response.
                pass
            else:
                merged_content, merged_metadata = self._apply_strategy(strategy, all_records)
                # Pick the principal id to scope the new memory. Prefer any
                # explicit user_id/agent_id from the original metadata.
                principal_kwargs: dict[str, Any] = {}
                for rec in all_records:
                    user_id = rec.get("user_id") or (rec.get("metadata") or {}).get("user_id")
                    if user_id:
                        principal_kwargs["user_id"] = user_id
                        break
                    agent_id = rec.get("agent_id") or (rec.get("metadata") or {}).get("agent_id")
                    if agent_id:
                        principal_kwargs["agent_id"] = agent_id
                        break
                if not principal_kwargs:
                    # Default to the agent_id from the request itself.
                    principal_kwargs["agent_id"] = req.agent_id

                def _do_add() -> Any:
                    return client.add(
                        merged_content,
                        metadata=merged_metadata,
                        **principal_kwargs,
                    )

                add_response = await anyio.to_thread.run_sync(_do_add)
                results: list[Any]
                if isinstance(add_response, dict):
                    results = list(add_response.get("results") or [])
                elif isinstance(add_response, list):
                    results = list(add_response)
                else:
                    results = []
                if (
                    results
                    and isinstance(results[0], dict)
                    and isinstance(results[0].get("id"), str)
                ):
                    canonical_id = results[0]["id"]

                # Original canonical is also dropped for the rewrite cases.
                if canonical_record is not None and req.canonical != canonical_id:

                    def _drop_old_canonical(old: str = req.canonical) -> None:
                        with contextlib.suppress(Exception):
                            client.delete(old)

                    await anyio.to_thread.run_sync(_drop_old_canonical)

        # Delete the duplicates in every strategy.
        merged_count = 0
        for dup_id, record in duplicate_records:
            if record is None:
                # mem0 doesn't know this id; skip without counting.
                continue

            def _do_delete(mid: str = dup_id) -> None:
                with contextlib.suppress(Exception):
                    client.delete(mid)

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
    ) -> tuple[str, dict[str, Any]]:
        """Produce ``(content, metadata)`` for the merged canonical record."""

        # Union all metadata across rows (last-write-wins on conflicts,
        # ordered by created_at ascending if available — falls back to the
        # input order). max(confidence) wins on merge_content per spec §3.4.
        def _sort_key(rec: dict[str, Any]) -> int:
            return _to_epoch_ms(rec.get("created_at")) or 0

        ordered = sorted(records, key=_sort_key)
        union_metadata: dict[str, Any] = {}
        max_confidence: float | None = None
        for rec in ordered:
            rec_meta = rec.get("metadata") or {}
            if isinstance(rec_meta, dict):
                union_metadata.update(rec_meta)
            conf_raw = rec_meta.get(_AMP_META_CONFIDENCE)
            if isinstance(conf_raw, (int, float)) and (
                max_confidence is None or conf_raw > max_confidence
            ):
                max_confidence = float(conf_raw)
        if max_confidence is not None:
            union_metadata[_AMP_META_CONFIDENCE] = max_confidence

        if strategy is MergeStrategy.KEEP_HIGHEST_CONFIDENCE:
            # Whichever row has the highest amp_confidence wins; ties broken
            # by older created_at (already sorted ascending — pick first
            # among the highest).
            best_record = ordered[0]
            best_conf = float("-inf")
            for rec in ordered:
                rec_meta = rec.get("metadata") or {}
                conf = rec_meta.get(_AMP_META_CONFIDENCE)
                if isinstance(conf, (int, float)) and float(conf) > best_conf:
                    best_conf = float(conf)
                    best_record = rec
            content = str(best_record.get("memory") or best_record.get("data") or "")
            return content, union_metadata

        # MERGE_CONTENT (default for the non-keep_canonical branch).
        # spec-gap: " | " separator rather than "\n" — see method docstring.
        pieces: list[str] = []
        for rec in ordered:
            piece = str(rec.get("memory") or rec.get("data") or "").strip()
            if piece:
                pieces.append(piece)
        return " | ".join(pieces), union_metadata

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        """Apply an expiration policy to a subset of memories.

        mem0 doesn't track last-recalled-at, so a policy carrying
        ``no_recall_in_days`` is rejected (spec §3.5: "Backends that do
        not track last-recalled-at MUST return an error").

        Actions:

        * ``forget`` — ``client.delete(id)`` per match.
        * ``archive`` — ``client.update(id, data=existing_content,
          metadata={..., "archived": True})``. spec-gap: mem0's ``update``
          requires a ``data`` (new content) argument; we pass the existing
          content unchanged.
        * ``demote`` — multiplies stored ``amp_confidence`` by 0.25 and
          persists via ``update``.
        """
        policy = req.policy
        action = req.action if req.action is not None else ExpireAction.FORGET

        if policy is not None and policy.no_recall_in_days is not None:
            raise ValueError(
                "mem0 adapter does not track last-recalled-at; "
                "the `no_recall_in_days` policy is unsupported"
            )

        client = self._get_client()
        principal_filters: dict[str, Any] = {"agent_id": req.agent_id}

        def _do_get_all() -> Any:
            return client.get_all(filters=principal_filters, top_k=1000)

        response = await anyio.to_thread.run_sync(_do_get_all)
        records = (
            response.get("results", []) if isinstance(response, dict) else list(response or [])
        )

        # Compute the age cut-off once.
        cutoff_ms: int | None = None
        if policy is not None and policy.older_than_days is not None:
            cutoff_ms = _now_ms() - (policy.older_than_days * 86_400_000)

        type_filter: MemoryType | None = policy.type if policy is not None else None
        confidence_below: float | None = policy.confidence_below if policy is not None else None

        matched: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            metadata = record.get("metadata") or {}

            if type_filter is not None:
                amp_type = metadata.get(_AMP_META_TYPE)
                if amp_type != type_filter.value:
                    continue

            if cutoff_ms is not None:
                created_at_raw = record.get("created_at") or metadata.get("created_at")
                created_at_ms = _to_epoch_ms(created_at_raw)
                # Policies are ANDed (spec §3.5 Editor's note). Skip rows
                # without a timestamp when the policy requires age.
                if created_at_ms is None or created_at_ms >= cutoff_ms:
                    continue

            if confidence_below is not None:
                conf = metadata.get(_AMP_META_CONFIDENCE)
                if not isinstance(conf, (int, float)) or float(conf) >= confidence_below:
                    continue

            matched.append(record)

        # Apply the action.
        for record in matched:
            mid = record.get("id")
            if not isinstance(mid, str):
                continue
            metadata = dict(record.get("metadata") or {})
            content = str(record.get("memory") or record.get("data") or "")

            if action is ExpireAction.FORGET:

                def _do_delete(mid: str = mid) -> None:
                    with contextlib.suppress(Exception):
                        client.delete(mid)

                await anyio.to_thread.run_sync(_do_delete)
            elif action is ExpireAction.ARCHIVE:
                # spec-gap: mem0's ``update`` always rewrites the content;
                # we keep ``data`` unchanged and merely toggle the archived
                # flag in metadata.
                metadata[_AMP_META_ARCHIVED] = True

                def _do_archive(
                    mid: str = mid,
                    content: str = content,
                    meta: dict[str, Any] = metadata,
                ) -> None:
                    with contextlib.suppress(Exception):
                        client.update(mid, data=content, metadata=meta)

                await anyio.to_thread.run_sync(_do_archive)
            else:  # DEMOTE
                # Multiply confidence by 0.25 — the spec §3.5 default
                # server-side score multiplier for demoted rows.
                existing_conf = metadata.get(_AMP_META_CONFIDENCE)
                if isinstance(existing_conf, (int, float)):
                    metadata[_AMP_META_CONFIDENCE] = float(existing_conf) * 0.25
                else:
                    metadata[_AMP_META_CONFIDENCE] = 0.25

                def _do_demote(
                    mid: str = mid,
                    content: str = content,
                    meta: dict[str, Any] = metadata,
                ) -> None:
                    with contextlib.suppress(Exception):
                        client.update(mid, data=content, metadata=meta)

                await anyio.to_thread.run_sync(_do_demote)

        return ExpireResponse(
            matched_count=len(matched),
            action_taken=action,
            stores=[_BACKEND_NAME],
        )

    async def health(self) -> dict[str, Any]:
        """Probe the backend with a tiny ``get_all`` call.

        Returns ``{"status": "ok", "backend": "mem0"}`` on success, or
        ``{"status": "error", "backend": "mem0", "error": "<reason>"}``
        when the probe raises.
        """
        try:
            client = self._get_client()
        except Exception as exc:
            return {"status": "error", "backend": _BACKEND_NAME, "error": str(exc)}

        def _probe() -> Any:
            # ``__health__`` is a sentinel principal that won't collide with
            # real users; mem0 will happily return an empty result for it.
            return client.get_all(filters={"user_id": "__health__"}, top_k=1)

        try:
            await anyio.to_thread.run_sync(_probe)
        except Exception as exc:
            return {"status": "error", "backend": _BACKEND_NAME, "error": str(exc)}
        return {"status": "ok", "backend": _BACKEND_NAME}


__all__ = ["Mem0Store"]
