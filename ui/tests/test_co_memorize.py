"""Tests for the Co-memorize Bulk Review screen."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from amp_ui import services


def _make_old(seeded_db: Any, memory_id: str, days_old: int = 120) -> None:
    age_ms = int(time.time() * 1000) - days_old * 86_400_000
    seeded_db.set_created_at(memory_id, age_ms)


@pytest.mark.anyio
async def test_co_memorize_page_renders(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/co-memorize")
        assert response.status_code == 200
        assert "Co-memorize bulk review" in response.text


def test_forget_candidate_selected_for_old_unrecalled_lowconf(seeded_db: Any) -> None:
    forget_id = seeded_db.remember("dusty unused note", confidence=0.3)
    _make_old(seeded_db, forget_id, days_old=100)
    # Add a row that should NOT match (high confidence).
    keep_id = seeded_db.remember("good note", confidence=0.9)
    _make_old(seeded_db, keep_id, days_old=100)

    candidates = services.co_memorize_candidates(seeded_db.db_path, "default")
    forget_ids = [c.primary_id for c in candidates if c.op_type == "forget"]
    assert forget_id in forget_ids
    assert keep_id not in forget_ids


def test_merge_candidate_pairs_same_user_high_overlap(seeded_db: Any) -> None:
    a = seeded_db.remember("alpha bravo charlie delta echo foxtrot golf", user_id="u1")
    b = seeded_db.remember("alpha bravo charlie delta echo foxtrot hotel", user_id="u1")
    # Unrelated row: same user, low overlap.
    seeded_db.remember("totally different stuff over here", user_id="u1")

    candidates = services.co_memorize_candidates(seeded_db.db_path, "default")
    merge_pairs = [(c.primary_id, c.secondary_id) for c in candidates if c.op_type == "merge"]
    assert (a, b) in merge_pairs


@pytest.mark.anyio
async def test_apply_forgets_selected_rows(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    forget_id = seeded_db.remember("kill me", confidence=0.2)
    _make_old(seeded_db, forget_id, days_old=200)

    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/co-memorize/apply",
            data={"op": [f"forget:{forget_id}:"]},
        )
        assert response.status_code in {200, 303}

    row = seeded_db.conn.execute(
        "SELECT deleted_at FROM memories WHERE id = ?", (forget_id,)
    ).fetchone()
    assert row["deleted_at"] is not None
    assert int(row["deleted_at"]) > 0


@pytest.mark.anyio
async def test_apply_merges_secondary(
    seeded_db: Any,
    app_for_path: Any,
) -> None:
    primary = seeded_db.remember("alpha bravo charlie delta echo foxtrot golf", user_id="u1")
    secondary = seeded_db.remember("alpha bravo charlie delta echo foxtrot hotel", user_id="u1")

    app = app_for_path(seeded_db.db_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/co-memorize/apply",
            data={"op": [f"merge:{primary}:{secondary}"]},
        )
        assert response.status_code in {200, 303}

    primary_row = seeded_db.conn.execute(
        "SELECT deleted_at FROM memories WHERE id = ?", (primary,)
    ).fetchone()
    secondary_row = seeded_db.conn.execute(
        "SELECT deleted_at FROM memories WHERE id = ?", (secondary,)
    ).fetchone()
    # Primary survives, secondary is soft-deleted.
    assert primary_row["deleted_at"] is None
    assert secondary_row["deleted_at"] is not None
