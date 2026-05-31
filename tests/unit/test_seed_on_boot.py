"""Unit tests for ``deploy/seed-on-boot.py``.

These tests cover the embedding-dim invariant that broke a previous
hosted-demo cut: the seeder must produce vectors whose dimension
matches what the real UI will later write, so the sqlite-vec virtual
table schema is consistent between boot-time seeding and runtime
writes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from memorywire.models import MemoryType, RememberRequest
from memorywire.store.sqlite_vec import DEFAULT_EMBEDDING_DIM, SqliteVecStore

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SEED_PATH = _REPO_ROOT / "deploy" / "seed-on-boot.py"


def _load_seed_module():
    """Import ``deploy/seed-on-boot.py`` despite the hyphen in the filename.

    A standard ``import deploy.seed-on-boot`` doesn't work because the
    hyphen isn't a legal identifier; the file also isn't on the Python
    path. importlib.util.spec_from_file_location bypasses both.
    """
    spec = importlib.util.spec_from_file_location("seed_on_boot", _SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_on_boot"] = module
    spec.loader.exec_module(module)
    return module


def test_fake_embedder_dim_matches_sqlite_vec_default() -> None:
    """Bug-3 regression: the seeder's fake embedder must be 384-d.

    A mismatch (e.g. 16-d) creates a 384-d schema (SqliteVecStore
    default) with insert calls that produce the wrong dimension, OR
    a 16-d schema that breaks every subsequent 384-d write from the
    real UI.
    """
    seed_mod = _load_seed_module()
    vec = seed_mod._fake_embedder("hello world")
    assert len(vec) == DEFAULT_EMBEDDING_DIM, (
        f"seed-on-boot fake embedder produced {len(vec)}-d vector; "
        f"SqliteVecStore default is {DEFAULT_EMBEDDING_DIM}-d"
    )
    # Determinism check â€” same input â†’ same output.
    again = seed_mod._fake_embedder("hello world")
    assert vec == again
    # Values bounded to [0, 1] (byte / 255.0).
    assert all(0.0 <= x <= 1.0 for x in vec)


@pytest.mark.anyio
async def test_seed_then_production_remember_succeeds(tmp_path: Path) -> None:
    """End-to-end Bug-3 check: after the seeder writes rows, a default-dim
    SqliteVecStore must be able to call ``remember`` against the same DB
    without dimension errors.

    Before the fix the seeder created the virtual table at 16-d, so any
    production-side ``remember`` (which uses the 384-d default embedder)
    failed at the sqlite-vec insert step.
    """
    seed_mod = _load_seed_module()
    db_path = tmp_path / "demo.db"
    # Force the seed module to use this temp DB and a known agent_id.
    seed_mod.AGENT_ID = "test-demo-agent"

    # Run the seeder's _seed coroutine directly to populate the DB.
    await seed_mod._seed(db_path)
    assert db_path.exists()

    # Now construct a production-style store with a *different* fake
    # 384-d embedder. If the schema is at 384-d (post-fix), this remember
    # succeeds. If at 16-d (pre-fix), the insert raises a dimension
    # mismatch.
    def production_embedder(text: str) -> list[float]:
        # Different bytes than the seeder but same dim; if dims match
        # this works, if not it explodes.
        import hashlib

        digest = hashlib.sha256(("prod:" + text).encode("utf-8")).digest()
        return [b / 255.0 for b in (digest * 12)[:DEFAULT_EMBEDDING_DIM]]

    store = SqliteVecStore(db_path=str(db_path), embedder=production_embedder)
    try:
        resp = await store.remember(
            RememberRequest(
                agent_id="test-demo-agent",
                user_id="prod-user",
                type=MemoryType.SEMANTIC,
                content="A production-side memory written after seeding.",
                metadata={"origin": "production-test"},
                confidence=0.9,
                source="production-test",
                approval_required=False,
            )
        )
        assert resp.id, "expected a memory id back from remember"
    finally:
        store.close()
