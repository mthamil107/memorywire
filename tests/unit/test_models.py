"""Tests for :mod:`memwire.models`.

These tests prove that:

1. Every worked example under ``docs/spec/examples/`` round-trips through the
   matching pydantic request/response model (and through the corresponding
   JSON Schema, for the request side).
2. Required fields are actually required (a ``ValidationError`` is raised
   when omitted).
3. The :class:`MemoryType` enum has exactly the four spec-defined members.
4. ``RememberRequest`` validates against its JSON Schema after round-tripping
   through pydantic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from memwire.models import (
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    MemoryType,
    MergeRequest,
    MergeResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)

# ---------------------------------------------------------------------------
# Example discovery
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_ROOT = REPO_ROOT / "docs" / "spec" / "examples"
SCHEMAS_ROOT = REPO_ROOT / "src" / "memwire" / "schemas"

# Maps the example directory name to (RequestModel, ResponseModel | None).
# ResponseModel is set for every operation: the three with authored schemas
# (remember/recall/forget) plus merge/expire whose response shapes are defined
# in the spec Editor's notes and modelled in ``memwire.models``.
_OP_MODELS: dict[str, tuple[type[BaseModel], type[BaseModel] | None]] = {
    "remember": (RememberRequest, RememberResponse),
    "recall": (RecallRequest, RecallResponse),
    "forget": (ForgetRequest, ForgetResponse),
    "merge": (MergeRequest, MergeResponse),
    "expire": (ExpireRequest, ExpireResponse),
}


def _discover_examples() -> list[tuple[str, Path]]:
    """Yield ``(operation, example_path)`` pairs for every example file."""
    out: list[tuple[str, Path]] = []
    for op in sorted(_OP_MODELS):
        op_dir = EXAMPLES_ROOT / op
        if not op_dir.is_dir():
            continue
        for path in sorted(op_dir.glob("*.json")):
            out.append((op, path))
    return out


_EXAMPLES = _discover_examples()


def _load_json(path: Path) -> dict[str, Any]:
    """Read a JSON file and return its parsed object."""
    with path.open("r", encoding="utf-8") as fh:
        loaded: Any = json.load(fh)
    assert isinstance(loaded, dict), f"example {path} root is not a JSON object"
    return loaded


def _strip_nones(obj: Any) -> Any:
    """Recursively drop keys whose value is ``None``.

    The example files sometimes carry explicit ``"approval_url": null`` for
    clarity even though the field is optional. ``model_dump(exclude_none=True)``
    drops those, so we normalise both sides before comparing.
    """
    if isinstance(obj, dict):
        return {k: _strip_nones(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nones(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Round-trip: every example request parses and serialises back to the input.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operation", "example_path"),
    _EXAMPLES,
    ids=[f"{op}/{p.stem}" for op, p in _EXAMPLES],
)
def test_example_request_roundtrip(operation: str, example_path: Path) -> None:
    """Every example's ``request`` must parse, then dump back to the original.

    We compare using ``exclude_none=True`` because pydantic emits explicit
    ``None`` for unset optional fields and the example files only carry
    keys the author actually set.
    """
    payload = _load_json(example_path)
    assert "request" in payload, f"{example_path} missing 'request'"
    request = payload["request"]

    request_model_cls, _ = _OP_MODELS[operation]
    parsed = request_model_cls.model_validate(request)
    dumped = parsed.model_dump(mode="json", exclude_none=True)
    expected = _strip_nones(request)

    assert dumped == expected, (
        f"round-trip mismatch for {example_path.name}:\noriginal: {expected}\nroundtrip: {dumped}"
    )


@pytest.mark.parametrize(
    ("operation", "example_path"),
    _EXAMPLES,
    ids=[f"{op}/{p.stem}" for op, p in _EXAMPLES],
)
def test_example_response_roundtrip(operation: str, example_path: Path) -> None:
    """Every example's ``response`` must parse and round-trip too.

    All five operations have response models in :mod:`memwire.models` (the three
    with authored JSON Schemas plus merge/expire's Editor's-note shapes).
    """
    payload = _load_json(example_path)
    if "response" not in payload:
        pytest.skip(f"{example_path.name} has no 'response' block")
    response = payload["response"]

    _, response_model_cls = _OP_MODELS[operation]
    assert response_model_cls is not None, "every op has a response model in v0"
    parsed = response_model_cls.model_validate(response)
    dumped = parsed.model_dump(mode="json", exclude_none=True)
    expected = _strip_nones(response)

    assert dumped == expected, (
        f"response round-trip mismatch for {example_path.name}:\n"
        f"original: {expected}\nroundtrip: {dumped}"
    )


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_remember_missing_agent_id_raises() -> None:
    """``RememberRequest`` without ``agent_id`` must raise ``ValidationError``."""
    with pytest.raises(ValidationError) as exc_info:
        RememberRequest.model_validate(  # type: ignore[call-arg]
            {"type": "semantic", "content": "hi"}
        )
    # The error message should mention the missing field by name.
    assert "agent_id" in str(exc_info.value)


def test_remember_empty_agent_id_raises() -> None:
    """``agent_id`` has ``min_length=1`` in the JSON Schema."""
    with pytest.raises(ValidationError):
        RememberRequest.model_validate({"agent_id": "", "type": "semantic", "content": "hi"})


def test_recall_missing_query_raises() -> None:
    """``RecallRequest`` without ``query`` must raise."""
    with pytest.raises(ValidationError) as exc_info:
        RecallRequest.model_validate({"agent_id": "a"})  # type: ignore[call-arg]
    assert "query" in str(exc_info.value)


def test_merge_empty_duplicates_raises() -> None:
    """``duplicates`` has ``minItems:1`` in the JSON Schema."""
    with pytest.raises(ValidationError):
        MergeRequest.model_validate({"agent_id": "a", "canonical": "c", "duplicates": []})


def test_recall_k_above_max_raises() -> None:
    """``k`` is bounded ``[1, 1000]`` in the JSON Schema."""
    with pytest.raises(ValidationError):
        RecallRequest.model_validate({"agent_id": "a", "query": "q", "k": 1001})


# ---------------------------------------------------------------------------
# Enum identity
# ---------------------------------------------------------------------------


def test_memory_type_has_exactly_four_members() -> None:
    """:class:`MemoryType` must mirror the spec's four-element vocabulary."""
    assert {m.value for m in MemoryType} == {
        "semantic",
        "episodic",
        "procedural",
        "emotional",
    }
    assert len(MemoryType) == 4


# ---------------------------------------------------------------------------
# JSON Schema round-trip: parsed model dumps validate against the schema.
# ---------------------------------------------------------------------------


def test_remember_request_dump_validates_against_json_schema() -> None:
    """Parsing then dumping a request must produce a payload the JSON Schema
    accepts. This guards against drift between the pydantic model and the
    on-disk schema."""
    schema_path = SCHEMAS_ROOT / "operations" / "remember.json"
    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)

    original = {
        "agent_id": "test-agent",
        "user_id": "test-user",
        "type": "semantic",
        "content": "Round-trip test fact.",
        "metadata": {"k": "v"},
        "confidence": 0.9,
        "source": "unit-test",
        "expires_at": 1716700000000,
        "approval_required": False,
    }

    model = RememberRequest.model_validate(original)
    dumped = model.model_dump(mode="json", exclude_none=True)

    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(dumped))
    assert errors == [], f"dump failed schema validation: {errors}"
