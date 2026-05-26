"""Tests for the Approval Patterns screen."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from amp_ui import services


def _seed_consistent_approvals(seeded_db: Any, n: int) -> list[str]:
    """Seed ``n`` remember-approval audit rows that share an (approver, type,
    keyword) cluster."""
    memory_ids: list[str] = []
    for i in range(n):
        mid = seeded_db.remember(f"coffee preference reminder {i}")
        memory_ids.append(mid)
        seeded_db.seed_audit(
            operation="remember",
            agent_id="default",
            memory_id=mid,
            approved_by="alice",
            payload={"action": "approve"},
            result={"approved": True},
        )
    return memory_ids


def test_pattern_recommendation_appears_at_threshold(seeded_db: Any) -> None:
    _seed_consistent_approvals(seeded_db, n=5)
    recos = services.pattern_recommendations(seeded_db.db_path, "default", threshold=5)
    assert len(recos) >= 1
    target = recos[0]
    assert target.approver == "alice"
    assert target.operation == "remember"
    assert target.count >= 5
    assert target.accepted is False


def test_pattern_below_threshold_is_hidden(seeded_db: Any) -> None:
    _seed_consistent_approvals(seeded_db, n=3)
    recos = services.pattern_recommendations(seeded_db.db_path, "default", threshold=5)
    assert recos == []


@pytest.mark.anyio
async def test_accept_pattern_inserts_row(
    seeded_db: Any,
    app_for_path: Any,
    csrf_client: Any,
) -> None:
    _seed_consistent_approvals(seeded_db, n=6)
    recos = services.pattern_recommendations(seeded_db.db_path, "default", threshold=5)
    key = recos[0].key

    app = app_for_path(seeded_db.db_path)
    async with csrf_client(app) as client:
        response = await client.post(f"/patterns/{key}/auto-allow", data={"reviewer": "alice"})
        assert response.status_code in {200, 303}

    rows = seeded_db.conn.execute(
        "SELECT key, approver, decision FROM approval_patterns WHERE key = ?", (key,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["approver"] == "alice"
    assert rows[0]["decision"] == "approve"


def test_accept_pattern_is_idempotent(seeded_db: Any) -> None:
    _seed_consistent_approvals(seeded_db, n=6)
    recos = services.pattern_recommendations(seeded_db.db_path, "default", threshold=5)
    key = recos[0].key
    first = services.accept_pattern(seeded_db.db_path, key, agent_id="default", reviewer="alice")
    second = services.accept_pattern(seeded_db.db_path, key, agent_id="default", reviewer="alice")
    assert first is True
    assert second is False  # Already accepted; refuses to double-insert.


@pytest.mark.anyio
async def test_patterns_page_renders(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/patterns")
        assert response.status_code == 200
        assert "Approval patterns" in response.text
