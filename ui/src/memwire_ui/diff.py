"""Diff helper for the pending-approvals screen.

The UI surfaces every pending memory (``deleted_at = -1``) alongside a
structured diff against the closest live memory (matched on
``metadata.entity_name`` first, then on a content prefix). The diff is a
pure function of two input dicts so it is easy to unit-test.

The result shape mirrors :class:`memwire.models.MemoryDiff`:

* ``added``    â€” keys present in the pending row but not in the current row.
* ``removed``  â€” keys present in the current row but not in the pending row.
* ``modified`` â€” keys present in both with different values; each entry
  carries both ``before`` and ``after`` so the UI can render them side by
  side.

If no live counterpart exists the diff degrades gracefully: every pending
field surfaces under ``added`` and ``removed``/``modified`` stay empty.
"""

from __future__ import annotations

from typing import Any

# Fields that are bookkeeping noise for human reviewers â€” they change every
# write and never carry semantic meaning. Excluded from the diff to keep the
# rendered output focused on what actually changes between memories.
_IGNORED_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "rowid",
        "created_at",
        "updated_at",
        "deleted_at",
        "last_recalled_at",
    }
)


def _normalize(row: dict[str, Any] | None) -> dict[str, Any]:
    """Drop ignored keys + ``None`` values to keep the diff dense.

    A ``None`` value in either side is treated as "field absent" so the diff
    does not flag every nullable column on every row.
    """
    if not row:
        return {}
    return {k: v for k, v in row.items() if k not in _IGNORED_FIELDS and v is not None}


def diff_memories(
    pending: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Compute a structured diff between a pending row and its current state.

    Parameters
    ----------
    pending:
        The row awaiting approval (``deleted_at = -1``). May be ``None`` if
        the row vanished between query and render â€” the diff then degrades
        to "everything was removed".
    current:
        The live counterpart, or ``None`` if no match was found. When
        ``None`` every pending field appears under ``added``.

    Returns
    -------
    dict[str, list[dict[str, Any]]]
        A dict with three keys: ``added``, ``removed``, ``modified``. Each
        list entry is itself a dict carrying the field name and value(s).
        The shape lines up with :class:`memwire.models.MemoryDiff`.
    """
    p = _normalize(pending)
    c = _normalize(current)

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []

    for key in sorted(p.keys() | c.keys()):
        in_pending = key in p
        in_current = key in c
        if in_pending and not in_current:
            added.append({"field": key, "value": p[key]})
        elif in_current and not in_pending:
            removed.append({"field": key, "value": c[key]})
        elif p[key] != c[key]:
            modified.append({"field": key, "before": c[key], "after": p[key]})

    return {"added": added, "removed": removed, "modified": modified}


__all__ = ["diff_memories"]
