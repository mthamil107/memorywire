"""Integration test for :class:`memwire.store.cognee_adapter.CogneeStore`.

This test exercises the **real** Cognee SDK end-to-end:

1. Construct ``CogneeStore(dataset='amp-itest')``.
2. ``remember`` a single semantic fact.
3. ``recall`` against a related query.
4. Assert the round-trip response shapes are honoured.

It is doubly gated:

* ``@pytest.mark.integration`` so default ``pytest -m "not integration"``
  runs skip it.
* ``@pytest.mark.skipif(not COGNEE_LLM_API_KEY)`` so even an explicit
  ``pytest -m integration`` skips it when the LLM key Cognee needs to
  build its knowledge graph is not configured.

Cognee runs an embedded pipeline (LanceDB vector store + Kuzu graph
DB) so no external service URL is required â€” just an LLM key for the
``cognify`` step.

Run with: ``pytest -m integration tests/integration/store/test_cognee_adapter.py``.
"""

from __future__ import annotations

import os
import time

import pytest

from memwire.models import MemoryType, RecallRequest, RememberRequest


def _cognee_env_ready() -> bool:
    """Return True iff Cognee has enough config to talk to an LLM."""
    # Cognee 1.x reads OPENAI_API_KEY by default; LLM_API_KEY is the
    # explicit override. Either suffices for this integration test.
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(
    not _cognee_env_ready(),
    reason="OPENAI_API_KEY or LLM_API_KEY required for the real Cognee backend",
)
async def test_remember_then_recall_against_real_cognee() -> None:
    """Round-trip one fact through a real ``CogneeStore``."""
    # Imported inside the test so collection works without cognee installed.
    from memwire.store.cognee_adapter import CogneeStore

    # Use a unique dataset per test run to avoid cross-run interference.
    dataset = f"amp-itest-{int(time.time())}"
    store = CogneeStore(dataset=dataset)

    write = await store.remember(
        RememberRequest(
            agent_id="amp-itest-agent",
            type=MemoryType.SEMANTIC,
            content="The agent's favourite colour is blue.",
            confidence=0.95,
            source="integration-test",
        )
    )
    assert write.stores == ["cognee"]
    assert write.pending_approval is False
    assert isinstance(write.id, str) and write.id.startswith("cog:")

    # Cognee's pipeline is asynchronous internally; the high-level
    # ``remember`` blocks until cognify completes by default, but allow a
    # small grace window for the search index to settle.
    await _sleep_briefly()

    read = await store.recall(
        RecallRequest(
            agent_id="amp-itest-agent",
            query="what colour does the agent like?",
            k=5,
        )
    )
    assert read.stores_queried == ["cognee"]
    assert isinstance(read.results, list)
    for hit in read.results:
        assert hit.source_store == "cognee"
        assert hit.content


async def _sleep_briefly() -> None:
    """Yield control briefly to let Cognee's pipeline settle."""
    import anyio

    await anyio.sleep(0.5)
