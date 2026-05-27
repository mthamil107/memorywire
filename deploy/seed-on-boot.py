#!/usr/bin/env python3
"""Idempotent boot shim for the hosted demo.

Responsibilities
----------------
1. Resolve the target DB path from ``AMP_UI_DB_PATH``.
2. If the file is missing OR the ``memories`` table has no rows for the
   demo agent, seed it with 2 pending approvals + 2 approved memories
   + an audit-log row, mirroring the recipe in
   ``docs/demos/seed_demo_db.py``.
3. ``exec`` into ``python -m amp_ui`` so PID 1 becomes uvicorn and Fly.io's
   SIGTERM propagates cleanly to it.

This script is wired in as the Dockerfile ``CMD`` rather than the real
entrypoint so the demo always has visible content on first boot but
restarts (after volume re-attach) do *not* clobber an existing DB.

Logs to stdout in single-line key=value format so ``fly logs`` is
greppable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# The amp_ui package is installed in the venv; the protocol package is
# too. No sys.path munging needed in the container.
from amp.models import MemoryType, RememberRequest
from amp.store.sqlite_vec import SqliteVecStore

AGENT_ID = os.environ.get("AMP_UI_AGENT_ID", "demo-agent")
USER_ID = "alice@acme.com"


def _log(event: str, **fields: object) -> None:
    """Single-line key=value log entry for `fly logs`."""
    parts = [f"event={event}"]
    for k, v in fields.items():
        if isinstance(v, str) and (" " in v or "=" in v):
            parts.append(f"{k}={json.dumps(v)}")
        else:
            parts.append(f"{k}={v}")
    print("[seed-on-boot] " + " ".join(parts), flush=True)


def _fake_embedder(text: str) -> list[float]:
    """Deterministic 16-dim float vector derived from sha256(text).

    Avoids pulling sentence-transformers into the runtime image. The UI
    never embeds; the seeded rows just need *some* vector so the
    sqlite-vec virtual table is consistent.
    """
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [((digest[i] / 255.0) * 2.0) - 1.0 for i in range(16)]


def _already_seeded(db_path: Path) -> bool:
    """Return True if the demo agent already has memories in this DB.

    We treat "any row for this agent_id" as the signal — fresh volumes
    start empty, restarted volumes carry forward whatever the previous
    instance accumulated.
    """
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:
        _log("seed.check.error", error=str(exc))
        return False
    try:
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE agent_id = ?",
                (AGENT_ID,),
            ).fetchone()
        except sqlite3.OperationalError:
            # Table not created yet — ensure_schema() will run after we
            # construct the store below.
            return False
        return bool(row and int(row[0]) > 0)
    finally:
        conn.close()


async def _seed(db_path: Path) -> None:
    """Write the demo fixture into ``db_path``. Caller guarantees emptiness."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = SqliteVecStore(
        db_path=str(db_path),
        embedder=_fake_embedder,
        embedding_dim=16,
    )
    try:
        # --- Approved historical memories --------------------------------
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

        # --- Pending memories --------------------------------------------
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
        await store.remember(
            RememberRequest(
                agent_id=AGENT_ID,
                user_id=USER_ID,
                type=MemoryType.EPISODIC,
                content=("On 2026-05-27 alice@acme.com reported a billing issue with order #7821."),
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

        _backfill_audit_rows(db_path)
    finally:
        store.close()


def _backfill_audit_rows(db_path: Path) -> None:
    """Insert 5 prior audit entries so /audit is not empty at first paint.

    Three historical approvals + one rejection + one pattern accept,
    spread across the prior 24h so the timeline reads naturally.
    """
    now = int(time.time() * 1000)
    conn = sqlite3.connect(str(db_path))
    try:
        first_memory = conn.execute(
            "SELECT id FROM memories WHERE agent_id = ? AND deleted_at IS NULL "
            "ORDER BY created_at ASC LIMIT 1",
            (AGENT_ID,),
        ).fetchone()
        memory_id = first_memory[0] if first_memory else None

        rows = [
            # (ts_offset_hours, operation, payload, result, approved_by)
            (
                24,
                "remember",
                {"action": "approve", "reason": "verified via crm"},
                {"approved": True},
                "ops@acme.com",
            ),
            (
                18,
                "remember",
                {"action": "approve", "reason": "matches policy"},
                {"approved": True},
                "ops@acme.com",
            ),
            (
                12,
                "forget",
                {"action": "reject", "reason": "low confidence"},
                {"approved": False},
                "ops@acme.com",
            ),
            (
                6,
                "remember",
                {"action": "approve", "reason": "routine update"},
                {"approved": True},
                "alice-reviewer@acme.com",
            ),
            (
                2,
                "pattern.accept",
                {
                    "key": "demo-pattern",
                    "approver": "ops@acme.com",
                    "operation": "remember",
                    "memory_type": "semantic",
                    "keyword": "preference",
                    "decision": "approve",
                },
                {"accepted": True},
                "ops@acme.com",
            ),
        ]
        for hours_ago, op, payload, result, approver in rows:
            ts = now - hours_ago * 60 * 60 * 1000
            conn.execute(
                "INSERT INTO audit_log(ts, operation, agent_id, user_id, memory_id, "
                "payload, result, approved_by, approval_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    op,
                    AGENT_ID,
                    USER_ID if op != "pattern.accept" else None,
                    memory_id if op != "pattern.accept" else None,
                    json.dumps(payload),
                    json.dumps(result),
                    approver,
                    ts,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    raw_path = os.environ.get("AMP_UI_DB_PATH")
    if not raw_path:
        _log("fatal", reason="AMP_UI_DB_PATH not set")
        sys.exit(1)
    db_path = Path(raw_path)

    if _already_seeded(db_path):
        _log("seed.skipped", reason="existing_db", path=str(db_path), agent_id=AGENT_ID)
    else:
        _log("seed.start", path=str(db_path), agent_id=AGENT_ID)
        try:
            asyncio.run(_seed(db_path))
        except Exception as exc:
            # Broad except is intentional: this is a boot shim and must
            # not crash the container — fall through to the UI even if
            # seeding hits a transient SQLite or sqlite-vec import error.
            _log("seed.error", error=str(exc))
            # Fall through to the UI anyway — ensure_schema() will still
            # create the OSS tables, the demo just won't have fixture rows.
        else:
            _log("seed.done", path=str(db_path), agent_id=AGENT_ID)

    # Hand off to the real entrypoint. execvp replaces this process so
    # uvicorn becomes PID 1 and receives Fly's SIGTERM directly.
    _log("exec", argv="python -m amp_ui")
    os.execvp(sys.executable, [sys.executable, "-m", "amp_ui"])


if __name__ == "__main__":
    main()
