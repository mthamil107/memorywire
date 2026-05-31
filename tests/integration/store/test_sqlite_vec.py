"""Integration test for :class:`memorywire.store.sqlite_vec.SqliteVecStore`.

Exercises the real ``sentence-transformers/all-MiniLM-L6-v2`` model. Skipped
in default unit-test runs (this module is marked ``integration``) and skipped
explicitly when ``SENTENCE_TRANSFORMERS_DISABLE=1`` is set in the
environment.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from memorywire.models import MemoryType, RecallRequest, RememberRequest

pytestmark = pytest.mark.integration


@pytest.fixture
def real_store() -> Iterator[object]:
    if os.environ.get("SENTENCE_TRANSFORMERS_DISABLE") == "1":
        pytest.skip("SENTENCE_TRANSFORMERS_DISABLE=1 set; skipping real-model integration test")
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except ImportError:
        pytest.skip("sentence-transformers not installed; skipping real-model integration test")

    from memorywire.store.sqlite_vec import SqliteVecStore

    s = SqliteVecStore(":memory:")
    try:
        yield s
    finally:
        s.close()


async def test_semantic_recall_matches_paraphrase(real_store: object) -> None:
    """Ingest 5 short snippets, query a paraphrase, expect a relevant top hit."""
    snippets = [
        "Alice is allergic to peanuts and tree nuts.",
        "Bob enjoys hiking on Saturday mornings.",
        "Carol is studying classical piano.",
        "Dave is a software engineer working on databases.",
        "Eve practices yoga every evening.",
    ]
    for content in snippets:
        await real_store.remember(  # type: ignore[attr-defined]
            RememberRequest(agent_id="int", type=MemoryType.SEMANTIC, content=content)
        )

    read = await real_store.recall(  # type: ignore[attr-defined]
        RecallRequest(agent_id="int", query="what nuts can Alice not eat?", k=3)
    )
    assert read.results, "expected at least one hit"
    top_contents = [str(hit.content).lower() for hit in read.results]
    assert any("alice" in c and ("peanut" in c or "nut" in c) for c in top_contents), (
        f"expected an Alice/peanuts hit in top-3, got: {top_contents}"
    )
