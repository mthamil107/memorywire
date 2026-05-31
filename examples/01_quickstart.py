"""memorywire quickstart â€” end-to-end demo using the :class:`memorywire.Memory` facade.

This script ingests 50 short facts, runs a few recalls, deletes one user's
records by filter, and prints final aggregate stats. It exists primarily
as an executable spec example: every printed section maps to one of the
public operations.

Embedding note
--------------
The default :class:`memorywire.store.sqlite_vec.SqliteVecStore` lazy-loads
``sentence-transformers/all-MiniLM-L6-v2`` on first embed call. To keep
this example runnable anywhere â€” CI, a fresh laptop, a Docker image
without ML wheels â€” we inject a tiny deterministic fake embedder
(sha256-derived 384-d vectors). The embedder is *not* representative of
real recall quality; it exists to make the storage layer exercise its
ANN path without pulling sentence-transformers.

Usage::

    .venv/Scripts/python.exe examples/01_quickstart.py
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import tempfile

from memorywire import Memory, MemoryType
from memorywire.store.sqlite_vec import SqliteVecStore

# ---------------------------------------------------------------------------
# Fake embedder â€” sha256-derived 384-d deterministic vector
# ---------------------------------------------------------------------------


def fake_embedder(text: str) -> list[float]:
    """Deterministic 384-d embedding derived from sha256.

    Repeats the 32-byte digest until we have at least 384 values, then
    truncates and normalises each byte to the [0, 1] range. Pure-stdlib so
    the quickstart runs with no extra installs.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Repeat to reach 384 bytes (sha256 yields 32; ceil(384/32) = 12 reps).
    repeats = (384 // len(digest)) + 1
    blob = (digest * repeats)[:384]
    return [b / 255.0 for b in blob]


# ---------------------------------------------------------------------------
# Seed data â€” 50 small facts
# ---------------------------------------------------------------------------

# Each entry is (content, user_id) so we can demonstrate per-user filtering.
SEED_FACTS: list[tuple[str, str]] = [
    ("Alice loves dark roast coffee.", "alice"),
    ("Alice is allergic to peanuts.", "alice"),
    ("Alice lives in Brooklyn.", "alice"),
    ("Alice prefers Linux over macOS.", "alice"),
    ("Alice plays piano on Sundays.", "alice"),
    ("Alice once climbed Mount Rainier.", "alice"),
    ("Alice's favourite colour is teal.", "alice"),
    ("Alice tends to read science-fiction.", "alice"),
    ("Alice runs five kilometres every morning.", "alice"),
    ("Alice tutors high-school students remotely.", "alice"),
    ("Bob is an avid kayaker.", "bob"),
    ("Bob lives in Seattle near Lake Union.", "bob"),
    ("Bob prefers tea over coffee.", "bob"),
    ("Bob speaks French and Portuguese.", "bob"),
    ("Bob collects vintage typewriters.", "bob"),
    ("Bob recently adopted a tabby cat named Pixel.", "bob"),
    ("Bob hosts a weekly trivia night at home.", "bob"),
    ("Bob's birthday is on March 14th.", "bob"),
    ("Bob commutes by bicycle year-round.", "bob"),
    ("Bob volunteers at the local food bank.", "bob"),
    ("Carla studies microbiology at university.", "carla"),
    ("Carla is fluent in Italian.", "carla"),
    ("Carla's research focuses on gut microbiomes.", "carla"),
    ("Carla enjoys long-distance cycling tours.", "carla"),
    ("Carla once met her favourite author at a book fair.", "carla"),
    ("Carla bakes sourdough on Saturdays.", "carla"),
    ("Carla lives with two roommates in Cambridge.", "carla"),
    ("Carla won a poetry contest in high school.", "carla"),
    ("Carla travels to Italy every other summer.", "carla"),
    ("Carla plays the cello in a chamber group.", "carla"),
    ("Paris hosted the 2024 Summer Olympics.", "world"),
    ("Mount Everest sits on the Nepal-China border.", "world"),
    ("The Pacific Ocean is the largest body of water on Earth.", "world"),
    ("Iceland runs almost entirely on renewable electricity.", "world"),
    ("The Amazon rainforest spans nine countries.", "world"),
    ("Cherry blossoms peak in Kyoto in early April.", "world"),
    ("Tokyo is the world's most populous metropolitan area.", "world"),
    ("Helsinki has a Sibelius monument in a downtown park.", "world"),
    ("Lisbon's trams are painted yellow.", "world"),
    ("Vienna's coffeehouse culture is UNESCO-listed.", "world"),
    ("Daniel prefers vegetarian meals.", "daniel"),
    ("Daniel uses a mechanical keyboard with linear switches.", "daniel"),
    ("Daniel once shipped a side-project that hit the Hacker News front page.", "daniel"),
    ("Daniel meditates for ten minutes every morning.", "daniel"),
    ("Daniel's go-to ice cream flavour is pistachio.", "daniel"),
    ("Daniel keeps a hand-written journal.", "daniel"),
    ("Daniel works remotely from a co-working space.", "daniel"),
    ("Daniel attended a Rust meetup last week.", "daniel"),
    ("Daniel is learning to play the harmonica.", "daniel"),
    ("Daniel's favourite hike is the Lost Coast Trail.", "daniel"),
]


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _section(title: str) -> None:
    """Print a clearly-delimited section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the full quickstart end-to-end."""
    # Use a temp file path so the demo also exercises the on-disk path.
    # An in-memory db works just as well â€” toggle the line below if needed.
    tmp_dir = tempfile.mkdtemp(prefix="amp-quickstart-")
    db_path = os.path.join(tmp_dir, "quickstart.db")

    store = SqliteVecStore(db_path, embedder=fake_embedder)
    mem = Memory(agent_id="quickstart", stores=[store])

    try:
        # ---- Section 1: ingest -------------------------------------------
        _section(f"1. Ingesting {len(SEED_FACTS)} memories")
        for content, user_id in SEED_FACTS:
            await mem.remember(content, type=MemoryType.SEMANTIC, user_id=user_id)
        print(f"  -> stored {len(SEED_FACTS)} semantic memories.")

        # ---- Section 2: recall -------------------------------------------
        _section("2. Recall: top 5 hits for 'coffee'")
        hits = await mem.recall("coffee", k=5)
        for rank, hit in enumerate(hits, start=1):
            print(f"  [{rank}] score={hit.score:.4f}  {hit.content}")

        # ---- Section 3: forget by filter ---------------------------------
        _section("3. Forget: drop everything tagged user_id=bob")
        forget_resp = await mem.forget(filter={"user_id": "bob"})
        print(f"  -> forgot {len(forget_resp.forgotten_ids)} memories belonging to Bob.")

        # ---- Section 4: health -------------------------------------------
        _section("4. Health: aggregate router status + remaining count")
        health = await mem.health()
        print(f"  router status: {health['status']}")
        for store_row in health["stores"]:
            backend = store_row.get("backend", "?")
            count = store_row.get("memory_count", "?")
            status = store_row.get("status", "?")
            print(f"    backend={backend} status={status} memory_count={count}")

    finally:
        # Cleanup: close the store, remove the temp dir.
        await mem.close()
        with contextlib.suppress(OSError):
            if os.path.exists(db_path):
                os.remove(db_path)
            os.rmdir(tmp_dir)


if __name__ == "__main__":
    asyncio.run(main())
