"""Tests for the Co-memorize Bulk Review screen."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from memwire_ui import services


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
    csrf_client: Any,
) -> None:
    forget_id = seeded_db.remember("kill me", confidence=0.2)
    _make_old(seeded_db, forget_id, days_old=200)

    app = app_for_path(seeded_db.db_path)
    async with csrf_client(app) as client:
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
    csrf_client: Any,
) -> None:
    primary = seeded_db.remember("alpha bravo charlie delta echo foxtrot golf", user_id="u1")
    secondary = seeded_db.remember("alpha bravo charlie delta echo foxtrot hotel", user_id="u1")

    app = app_for_path(seeded_db.db_path)
    async with csrf_client(app) as client:
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


# ---------------------------------------------------------------------------
# Bug-2 regressions: cross-agent scoping on co-memorize apply
# ---------------------------------------------------------------------------


def test_apply_co_memorize_skips_cross_agent_primary(seeded_db: Any) -> None:
    """A forget op targeting another agent's row must be skipped rather than
    silently soft-deleting that agent's data."""
    beta_id = seeded_db.remember("beta-only note", agent_id="beta")

    op = services.CoMemOp(op_type="forget", primary_id=beta_id)
    result = services.apply_co_memorize(seeded_db.db_path, "alpha", [op])

    assert result.applied == 0
    assert result.skipped == 1
    assert len(result.results) == 1
    assert result.results[0].skipped is True
    assert result.results[0].primary_id == beta_id

    # Beta's row must remain live.
    row = seeded_db.conn.execute(
        "SELECT deleted_at FROM memories WHERE id = ?", (beta_id,)
    ).fetchone()
    assert row["deleted_at"] is None


@pytest.mark.anyio
async def test_apply_route_returns_skipped_for_cross_agent(
    seeded_db: Any,
    app_for_path: Any,
    csrf_client: Any,
) -> None:
    """The full HTTP path mirrors the service contract: a POST trying to
    forget another agent's row produces a skipped result, not a 500 or a
    silent destruction."""
    beta_id = seeded_db.remember("beta-private note", agent_id="beta")

    app = app_for_path(seeded_db.db_path, agent_id="alpha")
    async with csrf_client(app) as client:
        response = await client.post(
            "/co-memorize/apply",
            data={"op": [f"forget:{beta_id}:"]},
        )
        assert response.status_code in {200, 303}
        # Whether we get the page back or a redirect, the row must still
        # be live afterwards.
    row = seeded_db.conn.execute(
        "SELECT deleted_at FROM memories WHERE id = ?", (beta_id,)
    ).fetchone()
    assert row["deleted_at"] is None
