"""Pure-function tests for :mod:`amp_ui.diff`."""

from __future__ import annotations

from memwire_ui.diff import diff_memories


def test_no_current_means_everything_added() -> None:
    pending = {
        "id": "abc",
        "content": "hello",
        "confidence": 0.9,
        "created_at": 1,
    }
    diff = diff_memories(pending, None)
    fields = {entry["field"] for entry in diff["added"]}
    # id/created_at are bookkeeping fields and filtered out of the diff.
    assert fields == {"content", "confidence"}
    assert diff["removed"] == []
    assert diff["modified"] == []


def test_identical_rows_produce_no_diff() -> None:
    row = {"content": "hello", "confidence": 0.9, "metadata": {"k": "v"}}
    diff = diff_memories(row, row)
    assert diff == {"added": [], "removed": [], "modified": []}


def test_modified_field_carries_before_and_after() -> None:
    pending = {"content": "v2", "confidence": 0.5}
    current = {"content": "v1", "confidence": 0.9}
    diff = diff_memories(pending, current)
    assert diff["added"] == []
    assert diff["removed"] == []
    modified_by_field = {m["field"]: m for m in diff["modified"]}
    assert modified_by_field["content"]["before"] == "v1"
    assert modified_by_field["content"]["after"] == "v2"
    assert modified_by_field["confidence"]["before"] == 0.9
    assert modified_by_field["confidence"]["after"] == 0.5


def test_added_and_removed_fields_are_distinguished() -> None:
    pending = {"content": "v", "source": "agent-A"}
    current = {"content": "v", "user_id": "alice"}
    diff = diff_memories(pending, current)
    assert diff["added"] == [{"field": "source", "value": "agent-A"}]
    assert diff["removed"] == [{"field": "user_id", "value": "alice"}]
    assert diff["modified"] == []


def test_none_values_are_treated_as_absent() -> None:
    """A None on either side should not show up as added/removed."""
    pending = {"content": "v", "confidence": None}
    current = {"content": "v", "confidence": None}
    diff = diff_memories(pending, current)
    assert diff == {"added": [], "removed": [], "modified": []}


def test_bookkeeping_fields_are_ignored() -> None:
    pending = {"id": "x", "content": "v", "created_at": 1, "updated_at": 2}
    current = {"id": "y", "content": "v", "created_at": 9, "updated_at": 9}
    diff = diff_memories(pending, current)
    assert diff == {"added": [], "removed": [], "modified": []}


def test_both_none_returns_empty_diff() -> None:
    assert diff_memories(None, None) == {"added": [], "removed": [], "modified": []}
