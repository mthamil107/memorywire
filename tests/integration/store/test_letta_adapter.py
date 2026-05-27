"""Integration test for :class:`amp.store.letta_adapter.LettaStore`.

This test exercises the **real** Letta SDK end-to-end:

1. Construct ``LettaStore(base_url=..., token=..., agent_id=...)``.
2. ``remember`` a single semantic fact.
3. ``recall`` against a related query.
4. Assert the round-trip response shapes are honoured.

It is doubly gated:

* ``@pytest.mark.integration`` so default ``pytest -m "not integration"``
  runs skip it.
* ``@pytest.mark.skipif(not LETTA_BASE_URL or not LETTA_AGENT_ID)`` so
  even an explicit ``pytest -m integration`` skips it when the server +
  agent are not configured.

Run with: ``pytest -m integration tests/integration/store/test_letta_adapter.py``.
"""

from __future__ import annotations

import os

import pytest

from amp.models import MemoryType, RecallRequest, RememberRequest


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("LETTA_BASE_URL") or not os.environ.get("LETTA_AGENT_ID"),
    reason="LETTA_BASE_URL and LETTA_AGENT_ID are required for the real Letta backend",
)
async def test_remember_then_recall_against_real_letta() -> None:
    """Round-trip one fact through a real ``LettaStore``."""
    # Imported inside the test so collection works without letta-client installed.
    from amp.store.letta_adapter import LettaStore

    store = LettaStore(
        base_url=os.environ["LETTA_BASE_URL"],
        token=os.environ.get("LETTA_API_KEY"),
        agent_id=os.environ["LETTA_AGENT_ID"],
    )

    write = await store.remember(
        RememberRequest(
            agent_id="amp-itest-agent",
            type=MemoryType.SEMANTIC,
            content="The agent's favourite colour is blue.",
        )
    )
    assert write.stores == ["letta"]
    assert write.pending_approval is False
    # Letta normally returns a real passage id; the adapter only synthesises a
    # ``letta:none:`` id when the server hands back nothing. Either is OK.
    assert isinstance(write.id, str) and write.id

    read = await store.recall(
        RecallRequest(
            agent_id="amp-itest-agent",
            query="what colour does the agent like?",
            k=5,
        )
    )
    assert read.stores_queried == ["letta"]
    assert isinstance(read.results, list)
    for hit in read.results:
        assert hit.source_store == "letta"
        assert hit.content
