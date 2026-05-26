"""Tests for the Memory Health dashboard."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from amp_ui import services

from amp.models import MemoryType


@pytest.mark.anyio
async def test_health_dashboard_renders_with_metrics(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    seeded_db.remember("fact one", type=MemoryType.SEMANTIC)
    seeded_db.remember("episode one", type=MemoryType.EPISODIC, user_id="u1")

    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health-dashboard")
        assert response.status_code == 200
        text = response.text
        assert "Total memories" in text
        assert "Staleness" in text
        assert "Drift pairs" in text
        assert "Type coverage" in text


def test_health_metrics_counts_correctly(seeded_db: Any) -> None:
    seeded_db.remember("a", type=MemoryType.SEMANTIC)
    seeded_db.remember("b", type=MemoryType.SEMANTIC)
    seeded_db.remember("c", type=MemoryType.EPISODIC)

    metrics = services.health_metrics(seeded_db.db_path, "default")
    assert metrics.total == 3
    assert metrics.coverage_by_type["semantic"] == 2
    assert metrics.coverage_by_type["episodic"] == 1


def test_staleness_pct_uses_last_recalled_at(seeded_db: Any) -> None:
    fresh = seeded_db.remember("recent")
    stale = seeded_db.remember("forgotten")
    # Mark one as freshly recalled, leave the other with NULL last_recalled_at.
    import time as t

    seeded_db.set_last_recalled_at(fresh, int(t.time() * 1000))

    metrics = services.health_metrics(seeded_db.db_path, "default")
    assert metrics.total == 2
    # The never-recalled row is stale; the freshly-recalled row is not.
    assert metrics.stale_count == 1
    assert metrics.stale_pct == 50.0
    # Existence check that fresh path actually wrote.
    assert stale is not None


def test_drift_pairs_detected_for_overlapping_content(seeded_db: Any) -> None:
    """Two same-user memories with near-identical content count as one pair."""
    seeded_db.remember("alpha bravo charlie delta echo foxtrot golf", user_id="u1")
    seeded_db.remember("alpha bravo charlie delta echo foxtrot hotel", user_id="u1")
    seeded_db.remember("totally unrelated content", user_id="u1")

    metrics = services.health_metrics(seeded_db.db_path, "default")
    assert metrics.drift_pairs == 1
