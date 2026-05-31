"""Seed a SQLite database with realistic governance-UI demo data.

This script writes pending and approved memories under a single agent
(``customer-bot``) so the recorder (`record_ui.py`) has a visually rich
flow to drive: pending semantic + pending episodic memories at the top
of the queue, a couple of pre-approved memories that share the same
``entity_name`` so the diff helper has something interesting to surface,
and one prior approve entry in the audit log.

Run from the repo root::

    .venv/Scripts/python.exe docs/demos/seed_demo_db.py

This always rebuilds ``docs/demos/demo-ui.db`` from scratch (deletes the
old file first) so consecutive seedings are deterministic. The embedder
is a hash-based fake so we never need sentence-transformers installed
for the demo.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Make `src/memwire` importable when invoked directly via `python docs/demos/...`.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from memwire.models import MemoryType, RememberRequest  # noqa: E402
from memwire.store.sqlite_vec import SqliteVecStore  # noqa: E402

DB_PATH = REPO_ROOT / "docs" / "demos" / "demo-ui.db"
AGENT_ID = "customer-bot"
USER_ID = "alice@acme.com"


def _fake_embedder(text: str) -> list[float]:
    """Deterministic 16-dim float vector derived from sha256(text).

    Lets us seed without pulling sentence-transformers â€” the demo only
    cares about the SQLite rows, never about ANN recall quality.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # 16 floats in [-1, 1].
    return [((digest[i] / 255.0) * 2.0) - 1.0 for i in range(16)]


async def _seed() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    # Tear down any stray WAL siblings left from a prior crashed run.
    for suffix in ("-wal", "-shm", "-journal"):
        sibling = DB_PATH.with_suffix(DB_PATH.suffix + suffix)
        if sibling.exists():
            sibling.unlink()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    store = SqliteVecStore(
        db_path=str(DB_PATH),
        embedder=_fake_embedder,
        embedding_dim=16,
    )
    try:
        # --- Approved historical memories (no approval_required) ----------
        approved_specs: list[tuple[str, MemoryType, dict[str, object], float]] = [
            (
                "Alice's order history shows 12 purchases over 18 months.",
                MemoryType.SEMANTIC,
                {"entity_name": "alice@acme.com", "source": "crm_sync"},
                0.95,
            ),
            (
                "Alice's plan tier is Pro.",
                MemoryType.SEMANTIC,
                {"entity_name": "alice@acme.com", "source": "billing_sync"},
                0.99,
            ),
        ]
        for content, mem_type, meta, confidence in approved_specs:
            await store.remember(
                RememberRequest(
                    agent_id=AGENT_ID,
                    user_id=USER_ID,
                    type=mem_type,
                    content=content,
                    metadata=meta,
                    confidence=confidence,
                    source=str(meta.get("source")),
                    approval_required=False,
                )
            )

        # --- Pending memories (approval_required=True) --------------------
        # 1) Semantic: introduces a contact preference. Shares the same
        #    entity_name as the approved rows so the diff renders a clear
        #    "modified content" + "added preference" view.
        await store.remember(
            RememberRequest(
                agent_id=AGENT_ID,
                user_id=USER_ID,
                type=MemoryType.SEMANTIC,
                content="Customer alice@acme.com prefers email over phone.",
                metadata={
                    "entity_name": "alice@acme.com",
                    "channel_preference": "email",
                    "source": "chat_session_4421",
                },
                confidence=0.92,
                source="chat_session_4421",
                approval_required=True,
            )
        )

        # 2) Episodic: a billing incident reported during a chat.
        await store.remember(
            RememberRequest(
                agent_id=AGENT_ID,
                user_id=USER_ID,
                type=MemoryType.EPISODIC,
                content=(
                    "On 2026-05-27 alice@acme.com reported a billing issue "
                    "with order #7821."
                ),
                metadata={
                    "entity_name": "alice@acme.com",
                    "incident_id": "INC-7821",
                    "source": "chat_session_4421",
                },
                confidence=0.88,
                source="chat_session_4421",
                approval_required=True,
            )
        )

        # --- Backfill one historical approval in the audit log so the ---
        # /audit page is not empty before the demo even starts.
        _backfill_historical_approval(DB_PATH, AGENT_ID, USER_ID)
    finally:
        store.close()

    _print_summary(DB_PATH, AGENT_ID)


def _backfill_historical_approval(db_path: Path, agent_id: str, user_id: str) -> None:
    """Insert a synthetic prior-approve row so /audit is never bare."""
    now = int(time.time() * 1000)
    # 2 hours ago, so the demo's new approval lands above it in DESC ts order.
    ts = now - 2 * 60 * 60 * 1000
    conn = sqlite3.connect(str(db_path))
    try:
        # Use a known existing memory id (the first approved one above) so the
        # `memory` column points to a real row.
        row = conn.execute(
            "SELECT id FROM memories WHERE agent_id = ? AND deleted_at IS NULL "
            "ORDER BY created_at ASC LIMIT 1",
            (agent_id,),
        ).fetchone()
        memory_id = row[0] if row else None
        conn.execute(
            "INSERT INTO audit_log(ts, operation, agent_id, user_id, memory_id, "
            "payload, result, approved_by, approval_at) "
            "VALUES (?, 'remember', ?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                agent_id,
                user_id,
                memory_id,
                json.dumps({"action": "approve", "reason": "verified via crm"}),
                json.dumps({"approved": True}),
                "ops@acme.com",
                ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _print_summary(db_path: Path, agent_id: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE agent_id = ?", (agent_id,)
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE agent_id = ? AND deleted_at = -1",
            (agent_id,),
        ).fetchone()[0]
        approved = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE agent_id = ? AND deleted_at IS NULL",
            (agent_id,),
        ).fetchone()[0]
        audit_rows = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    finally:
        conn.close()
    print(f"[seed] db_path={db_path}")
    print(f"[seed] agent_id={agent_id}")
    print(f"[seed] memories={total} (pending={pending}, approved={approved})")
    print(f"[seed] audit_log_rows={audit_rows}")


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
