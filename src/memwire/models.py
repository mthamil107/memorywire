"""Pydantic v2 models for the Agent Memory Protocol (memwire) v0.

This module mirrors the JSON Schemas under :mod:`memwire.schemas`. Every operation
request and response that has a JSON Schema has a matching pydantic class here.
The four memory-type schemas under ``schemas/types/`` are exposed as a
discriminated :data:`Memory` union keyed on the ``type`` literal.

Design notes
------------
* All models set ``extra="allow"`` so forward-compatible additional fields
  (per spec section 9: "new optional fields Ã¢â‚¬â€ allowed at any time") do not
  break parsing.
* All models set ``populate_by_name=True`` so callers may use either the
  pydantic field name or the JSON Schema field name when constructing.
* ``use_enum_values=False`` keeps the enum *member* on the instance; the
  serialized form (via ``model_dump``) still emits the underlying string
  because every enum subclasses ``str``.
* Types use ``X | None`` (PEP 604) per Python 3.11+ convention.

The ``MergeResponse`` and ``ExpireResponse`` models do not have authored JSON
Schemas at v0 Ã¢â‚¬â€ see :file:`docs/spec/notes.md` for the rationale. Their fields
follow the Editor's-note shapes in :file:`docs/spec/v0.md` Ã‚Â§3.4 and Ã‚Â§3.5.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Common model configuration
# ---------------------------------------------------------------------------

# All memwire models share the same pydantic config: forward-compat extras, alias
# population, and enum identity (not value) on the instance. Centralising the
# config object keeps every class consistent.
_AMP_MODEL_CONFIG = ConfigDict(
    extra="allow",
    populate_by_name=True,
    use_enum_values=False,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MemoryType(str, Enum):  # noqa: UP042 -- spec contract pins (str, Enum); StrEnum changes __str__
    """The four memory-type tags defined by spec section 2."""

    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"
    EMOTIONAL = "emotional"


class FusionAlgorithm(str, Enum):  # noqa: UP042 -- spec contract pins (str, Enum)
    """Fusion algorithms for the recall operation (spec section 5)."""

    RRF = "rrf"
    MAX = "max"
    WEIGHTED = "weighted"


class MergeStrategy(str, Enum):  # noqa: UP042 -- spec contract pins (str, Enum)
    """Merge strategies for the merge operation (spec section 3.4)."""

    KEEP_CANONICAL = "keep_canonical"
    MERGE_CONTENT = "merge_content"
    KEEP_HIGHEST_CONFIDENCE = "keep_highest_confidence"


class ExpireAction(str, Enum):  # noqa: UP042 -- spec contract pins (str, Enum)
    """Expiry actions for the expire operation (spec section 3.5)."""

    FORGET = "forget"
    ARCHIVE = "archive"
    DEMOTE = "demote"


class GovernanceOperation(str, Enum):  # noqa: UP042 -- spec contract pins (str, Enum)
    """Operations that may be routed through the governance channel
    (spec section 6)."""

    REMEMBER = "remember"
    FORGET = "forget"
    MERGE = "merge"


# ---------------------------------------------------------------------------
# Operation request models
# ---------------------------------------------------------------------------


class RememberRequest(BaseModel):
    """Request payload for the ``remember`` operation.

    Mirrors :file:`src/memwire/schemas/operations/remember.json`.
    """

    model_config = _AMP_MODEL_CONFIG

    agent_id: str = Field(..., min_length=1, max_length=256)
    user_id: str | None = Field(default=None, max_length=256)
    type: MemoryType
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str | None = None
    # Unix epoch ms; optional TTL.
    expires_at: int | None = None
    approval_required: bool | None = None


class RecallRequest(BaseModel):
    """Request payload for the ``recall`` operation.

    Mirrors :file:`src/memwire/schemas/operations/recall.json`.
    """

    model_config = _AMP_MODEL_CONFIG

    agent_id: str
    user_id: str | None = None
    query: str = Field(..., min_length=1)
    k: int | None = Field(default=None, ge=1, le=1000)
    types: list[MemoryType] | None = None
    hops: int | None = Field(default=None, ge=0, le=3)
    fusion: FusionAlgorithm | None = None
    filter: dict[str, Any] | None = None
    fresher_than_days: int | None = Field(default=None, ge=0)


class ForgetRequest(BaseModel):
    """Request payload for the ``forget`` operation.

    Mirrors :file:`src/memwire/schemas/operations/forget.json`.

    Note: spec section 3.3 says servers MUST reject requests where both
    ``ids`` and ``filter`` are absent (no-scope mass-delete protection). That
    rule is policy-level, enforced at the store/router layer, not by the
    request shape itself Ã¢â‚¬â€ both fields remain optional here.
    """

    model_config = _AMP_MODEL_CONFIG

    agent_id: str
    user_id: str | None = None
    ids: list[str] | None = None
    filter: dict[str, Any] | None = None
    hard_delete: bool | None = None
    reason: str | None = None


class MergeRequest(BaseModel):
    """Request payload for the ``merge`` operation.

    Mirrors :file:`src/memwire/schemas/operations/merge.json`.
    """

    model_config = _AMP_MODEL_CONFIG

    agent_id: str
    # "the surviving entity id or name"
    canonical: str
    # The JSON Schema requires minItems:1.
    duplicates: list[str] = Field(..., min_length=1)
    strategy: MergeStrategy | None = None


class ExpirePolicy(BaseModel):
    """Nested policy object inside :class:`ExpireRequest`."""

    model_config = _AMP_MODEL_CONFIG

    older_than_days: int | None = Field(default=None, ge=1)
    type: MemoryType | None = None
    confidence_below: float | None = Field(default=None, ge=0, le=1)
    no_recall_in_days: int | None = Field(default=None, ge=1)


class ExpireRequest(BaseModel):
    """Request payload for the ``expire`` operation.

    Mirrors :file:`src/memwire/schemas/operations/expire.json`.
    """

    model_config = _AMP_MODEL_CONFIG

    agent_id: str
    policy: ExpirePolicy | None = None
    action: ExpireAction | None = None


# ---------------------------------------------------------------------------
# Operation response models
# ---------------------------------------------------------------------------


class RememberResponse(BaseModel):
    """Response payload from the ``remember`` operation.

    Mirrors :file:`src/memwire/schemas/operations/remember.response.json`.
    """

    model_config = _AMP_MODEL_CONFIG

    id: str = Field(..., min_length=1)
    # Unix epoch ms when the memory was stored (or staged for approval).
    stored_at: int
    stores: list[str]
    pending_approval: bool
    approval_url: str | None = None


class RecallHit(BaseModel):
    """One row in a recall response.

    Matches the inner shape of ``results[]`` inside
    :file:`src/memwire/schemas/operations/recall.response.json`.

    ``content`` may be a string (semantic/episodic/emotional) or a dict
    (procedural FSM) Ã¢â‚¬â€ per the response schema's ``["string", "object"]``
    type union.
    """

    model_config = _AMP_MODEL_CONFIG

    id: str = Field(..., min_length=1)
    type: MemoryType
    content: str | dict[str, Any]
    score: float
    metadata: dict[str, Any] | None = None
    # Unix epoch ms.
    created_at: int | None = None
    supporting: list[str] | None = None
    source_store: str | None = None


# Public alias Ã¢â‚¬â€ the spec doc (section 1) names the result shape ``Recall`` for
# clients. ``RecallHit`` is kept as the canonical class name so other modules
# can import either.
Recall = RecallHit


class RecallResponse(BaseModel):
    """Response payload from the ``recall`` operation.

    Mirrors :file:`src/memwire/schemas/operations/recall.response.json`.
    """

    model_config = _AMP_MODEL_CONFIG

    results: list[RecallHit]
    fusion_used: FusionAlgorithm
    stores_queried: list[str]
    latency_ms: int = Field(..., ge=0)


class ForgetStoreResult(BaseModel):
    """Per-store breakdown row inside a :class:`ForgetResponse`.

    Matches the inner shape of ``stores[]`` inside
    :file:`src/memwire/schemas/operations/forget.response.json`.
    """

    # The per-store row in forget.response.json declares
    # ``additionalProperties: false``, so this is the one model in this file
    # that locks down extras. Keeping ``extra="forbid"`` matches the schema.
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=False)

    store: str
    count: int = Field(..., ge=0)
    error: str | None = None


class ForgetResponse(BaseModel):
    """Response payload from the ``forget`` operation.

    Mirrors :file:`src/memwire/schemas/operations/forget.response.json` (the
    response shape is inferred Ã¢â‚¬â€ see Editor's note in spec section 3.3).
    """

    model_config = _AMP_MODEL_CONFIG

    forgotten_ids: list[str]
    hard_delete: bool
    stores: list[ForgetStoreResult]
    pending_approval: bool | None = None
    approval_url: str | None = None


class MergeResponse(BaseModel):
    """Response payload from the ``merge`` operation.

    No JSON Schema exists for this at v0 (see :file:`docs/spec/notes.md`); the
    field set follows the Editor's-note shape in spec section 3.4.
    """

    model_config = _AMP_MODEL_CONFIG

    canonical: str
    merged_count: int = Field(..., ge=0)
    strategy_used: MergeStrategy
    stores: list[str]


class ExpireResponse(BaseModel):
    """Response payload from the ``expire`` operation.

    No JSON Schema exists for this at v0 (see :file:`docs/spec/notes.md`); the
    field set follows the Editor's-note shape in spec section 3.5.
    """

    model_config = _AMP_MODEL_CONFIG

    matched_count: int = Field(..., ge=0)
    action_taken: ExpireAction
    stores: list[str]


# ---------------------------------------------------------------------------
# Memory-record models
# ---------------------------------------------------------------------------


class MemoryRecord(BaseModel):
    """Base class with the fields common to every stored memory record.

    Subclasses pin ``type`` to a single :class:`MemoryType` literal so a
    discriminated union (:data:`Memory`) can route based on the ``type``
    tag.
    """

    model_config = _AMP_MODEL_CONFIG

    id: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1, max_length=256)
    user_id: str | None = Field(default=None, max_length=256)
    type: MemoryType
    # Stored as a string for all types in v0 (procedural memories carry the
    # FSM JSON inside the string Ã¢â‚¬â€ see spec section 7). Procedural records
    # expose ``.fsm()`` for the parsed view.
    content: str
    metadata: dict[str, Any] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str | None = None
    created_at: int
    updated_at: int | None = None
    # Nullable per the type schemas (``["integer", "null"]``).
    expires_at: int | None = None


class SemanticMemory(MemoryRecord):
    """A semantic memory record (general facts / declarative knowledge)."""

    model_config = _AMP_MODEL_CONFIG

    type: Literal[MemoryType.SEMANTIC] = MemoryType.SEMANTIC


class EpisodicMemory(MemoryRecord):
    """An episodic memory record (a specific past event with context)."""

    model_config = _AMP_MODEL_CONFIG

    type: Literal[MemoryType.EPISODIC] = MemoryType.EPISODIC
    # Unix epoch ms when the underlying event actually happened.
    event_time: int | None = None
    location: str | None = None
    participants: list[str] | None = None


class ProceduralMemory(MemoryRecord):
    """A procedural memory record (an FSM-encoded how-to procedure).

    The ``content`` field carries the FSM as a JSON-encoded *string* in v0
    (per spec section 7 Ã¢â‚¬â€ "the FSM JSON is currently carried as a string in
    `content`"). Phase 5 will swap the return type of :meth:`fsm` to a real
    :class:`Procedure` class; at Phase 2 it returns the parsed dict.
    """

    model_config = _AMP_MODEL_CONFIG

    type: Literal[MemoryType.PROCEDURAL] = MemoryType.PROCEDURAL

    def fsm(self) -> dict[str, Any]:
        """Parse ``content`` as JSON and return the FSM definition.

        Returns
        -------
        dict[str, Any]
            The decoded FSM. Phase 5 will swap this for a typed
            ``Procedure`` model; callers should treat the dict shape as the
            stable contract documented in spec section 7.

        Raises
        ------
        ValueError
            If ``content`` is not valid JSON or does not decode to an object.
        """
        # Imported lazily Ã¢â‚¬â€ ``json`` is stdlib so this is essentially free,
        # but importing at call time documents that the parse is on-demand.
        import json

        try:
            decoded = json.loads(self.content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"procedural memory content is not valid JSON: {exc.msg}") from exc
        if not isinstance(decoded, dict):
            raise ValueError(
                "procedural memory content must decode to a JSON object (FSM); "
                f"got {type(decoded).__name__}"
            )
        return decoded


class EmotionalMemory(MemoryRecord):
    """An emotional memory record (affective association)."""

    model_config = _AMP_MODEL_CONFIG

    type: Literal[MemoryType.EMOTIONAL] = MemoryType.EMOTIONAL
    sentiment: Literal["positive", "negative", "neutral", "mixed"] | None = None
    valence: float | None = Field(default=None, ge=-1, le=1)
    arousal: float | None = Field(default=None, ge=0, le=1)
    emotion: str | None = None
    target: str | None = None


# Discriminated union keyed on the ``type`` tag. ``Memory`` is the public name
# clients use to refer to "a memory record of any type". Phase 4 promotes a
# Memory *facade* class to ``memwire.__init__``; this name is the wire-format
# discriminated union and is independent of that runtime facade.
Memory = SemanticMemory | EpisodicMemory | ProceduralMemory | EmotionalMemory


# ---------------------------------------------------------------------------
# Procedural FSM models (spec section 7)
# ---------------------------------------------------------------------------


class ProcedureTransition(BaseModel):
    """One transition row inside a :class:`ProcedureSpec`.

    Matches the ``content.transitions[]`` shape in
    :file:`src/memwire/schemas/types/procedural.json`. Extra keys are allowed
    (``conditions``, ``unless``, ``before``, ``after``, Ã¢â‚¬Â¦) so pytransitions
    adapters can round-trip backend-specific extras.
    """

    model_config = _AMP_MODEL_CONFIG

    trigger: str = Field(..., min_length=1)
    # ``"*"`` is the pytransitions wildcard; the schema permits any non-empty
    # string (see Editor's note in spec section 7).
    source: str = Field(..., min_length=1)
    dest: str = Field(..., min_length=1)
    conditions: list[str] | str | None = None


class ProcedureSpec(BaseModel):
    """An FSM definition as carried inside a procedural memory's content.

    Mirrors the ``content`` object of :file:`src/memwire/schemas/types/procedural.json`.
    """

    model_config = _AMP_MODEL_CONFIG

    name: str = Field(..., min_length=1)
    initial: str = Field(..., min_length=1)
    states: list[str] = Field(..., min_length=1)
    transitions: list[ProcedureTransition]
    current: str = Field(..., min_length=1)
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Governance models (spec section 6)
# ---------------------------------------------------------------------------


class MemoryDiff(BaseModel):
    """Structured diff carried inside a governance review request.

    Mirrors the ``diff`` field shape in spec section 6.
    """

    model_config = _AMP_MODEL_CONFIG

    added: list[dict[str, Any]] | None = None
    removed: list[dict[str, Any]] | None = None
    modified: list[dict[str, Any]] | None = None


class GovernanceReviewRequest(BaseModel):
    """Request payload sent to the governance channel for HITL review.

    Mirrors the schema sketched in spec section 6.

    The ``request`` field is intentionally typed as ``dict[str, Any]`` rather
    than a discriminated union of ``RememberRequest | ForgetRequest |
    MergeRequest`` because the spec doc itself (see Editor's note in section
    6) acknowledges the ``$ref`` is hard-coded and a proper ``oneOf`` /
    ``if-then-else`` form is deferred to v0.2. Phase 6 will tighten this when
    the governance schema is rewritten.

    spec-gap: discriminated-union for ``request`` deferred to v0.2 per spec
    section 6 Editor's note.
    """

    model_config = _AMP_MODEL_CONFIG

    operation: GovernanceOperation
    agent_id: str
    request: dict[str, Any]
    diff: MemoryDiff | None = None
    reasoning: str | None = None


class GovernanceReviewResponse(BaseModel):
    """Response returned by the governance channel after HITL review.

    Mirrors the response example in spec section 6.
    """

    model_config = _AMP_MODEL_CONFIG

    approved: bool
    reviewer: str
    # Unix epoch ms.
    reviewed_at: int
    reason: str | None = None


# ---------------------------------------------------------------------------
# Public re-export surface
# ---------------------------------------------------------------------------

__all__ = [
    "EmotionalMemory",
    "EpisodicMemory",
    "ExpireAction",
    "ExpirePolicy",
    "ExpireRequest",
    "ExpireResponse",
    "ForgetRequest",
    "ForgetResponse",
    "ForgetStoreResult",
    "FusionAlgorithm",
    "GovernanceOperation",
    "GovernanceReviewRequest",
    "GovernanceReviewResponse",
    "Memory",
    "MemoryDiff",
    "MemoryRecord",
    "MemoryType",
    "MergeRequest",
    "MergeResponse",
    "MergeStrategy",
    "ProceduralMemory",
    "ProcedureSpec",
    "ProcedureTransition",
    "Recall",
    "RecallHit",
    "RecallRequest",
    "RecallResponse",
    "RememberRequest",
    "RememberResponse",
    "SemanticMemory",
]
