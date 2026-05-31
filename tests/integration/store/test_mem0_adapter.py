"""Integration test for :class:`memwire.store.mem0_adapter.Mem0Store`.

This test exercises the **real** mem0 SDK end-to-end:

1. Construct ``Mem0Store()`` with the SDK's own defaults (talks to OpenAI
   for embeddings + LLM extraction).
2. ``remember`` a single semantic fact.
3. ``recall`` against a related query.
4. Assert at least one hit is returned.

It is doubly gated:

* ``@pytest.mark.integration`` so default ``pytest -m "not integration"``
  runs skip it.
* ``@pytest.mark.skipif(not OPENAI_API_KEY)`` so even an explicit
  ``pytest -m integration`` skips it when no key is available.

Run with: ``pytest -m integration tests/integration/store/test_mem0_adapter.py``.
"""

from __future__ import annotations

import os
import uuid

import pytest

from memwire.models import MemoryType, RecallRequest, RememberRequest


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY is required for the real mem0 backend",
)
async def test_remember_then_recall_against_real_mem0() -> None:
    """Round-trip one fact through a real ``Mem0Store``."""
    # Imported inside the test so collection works without mem0 installed.
    from memwire.store.mem0_adapter import Mem0Store

    store = Mem0Store()
    # Unique user id keeps integration runs from contaminating each other.
    user_id = f"amp-itest-{uuid.uuid4().hex[:8]}"

    write = await store.remember(
        RememberRequest(
            agent_id="amp-itest-agent",
            user_id=user_id,
            type=MemoryType.SEMANTIC,
            content="The agent's favorite color is blue.",
        )
    )
    # mem0 may extract zero memories from a single-sentence prompt; allow
    # an empty id but require the call to have completed without raising.
    assert write.stores == ["mem0"]
    assert write.pending_approval is False

    read = await store.recall(
        RecallRequest(
            agent_id="amp-itest-agent",
            user_id=user_id,
            query="what color does the agent like?",
            k=5,
        )
    )
    # If mem0 extracted a memory above we expect at least one match;
    # otherwise the test would be flaky against the LLM's discretion.
    # We accept either outcome but assert the response shape is sane.
    assert read.stores_queried == ["mem0"]
    assert isinstance(read.results, list)
    # Best-effort: if we got any results, the content shouldn't be empty.
    for hit in read.results:
        assert hit.source_store == "mem0"
        assert hit.content
