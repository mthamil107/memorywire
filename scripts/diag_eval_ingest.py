"""Diagnostic for the eval harness ingest+recall pipeline.

Runs one LongMemEval question and one LoCoMo question through a
fresh Memory(sqlite-vec) backend in isolation, mirroring the exact
ingest+recall pattern the harnesses use, then prints what landed,
what recall returned, and whether the gold answer surfaces.

Two outcomes:

* If the gold answer surfaces in the top-k content for a *freshly
  created* DB, then the harness's recall logic is OK and the low
  benchmark score is real.
* If the gold answer does NOT surface even from a fresh DB, the
  embedder or recall filter is the problem.

Either way, the diagnostic also reports per-question memory_count
to confirm rows actually landed in the store.
"""

from __future__ import annotations

# Offline mode MUST be set before any HF/transformers import.
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import asyncio
import contextlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from amp import Memory, MemoryType  # noqa: E402
from scripts.run_locomo import _load_locomo_from_disk  # noqa: E402
from scripts.run_longmemeval import _load_longmemeval_from_disk  # noqa: E402


LME_CACHE = Path("C:/Users/THAMIL/.cache/amp/longmemeval")
LOCOMO_CACHE = Path("C:/Users/THAMIL/.cache/amp/locomo")
DIAG_DIR = _REPO_ROOT / ".diag"


def _print(label: str, value) -> None:
    print(f"{label}: {value}")


async def _diag_lme() -> None:
    print("=" * 78)
    print("LongMemEval diagnostic")
    print("=" * 78)
    questions = _load_longmemeval_from_disk(LME_CACHE)
    print(f"loaded {len(questions)} LongMemEval questions")
    # Pick the first question that has at least one session with content
    # and a real gold answer.
    q = next(
        (
            qq
            for qq in questions
            if qq.sessions
            and any(turn.get("content") for sess in qq.sessions for turn in sess)
            and qq.gold_answer
        ),
        None,
    )
    if q is None:
        print("no usable LME question found; aborting")
        return

    _print("qid", q.qid)
    _print("task_type", q.task_type)
    _print("question", q.question)
    _print("gold_answer", q.gold_answer)
    _print("num sessions", len(q.sessions))
    _print("total turns", sum(len(s) for s in q.sessions))

    db_path = DIAG_DIR / "diag-lme.db"
    if db_path.exists():
        db_path.unlink()
    DIAG_DIR.mkdir(exist_ok=True)

    agent_id = f"diag-lme-{q.qid}"
    mem = Memory(agent_id=agent_id, stores=[f"sqlite-vec://{db_path.as_posix()}"])
    try:
        first_print = True
        n_ingested = 0
        for sess_ix, session in enumerate(q.sessions):
            for turn_ix, turn in enumerate(session):
                if not turn.get("content"):
                    continue
                resp = await mem.remember(
                    turn["content"],
                    type=MemoryType.EPISODIC,
                    metadata={
                        "qid": q.qid,
                        "session_id": sess_ix,
                        "turn_ix": turn_ix,
                        "role": turn.get("role", "user"),
                    },
                )
                n_ingested += 1
                if first_print:
                    print(
                        f"first remember -> id={resp.id} stored_at={resp.stored_at} "
                        f"stores={resp.stores}"
                    )
                    first_print = False
        _print("rows ingested", n_ingested)

        health = await mem.health()
        per_store = health.get("stores", []) if isinstance(health, dict) else []
        for ps in per_store:
            if ps.get("backend") == "sqlite-vec":
                _print("sqlite-vec memory_count", ps.get("memory_count"))

        # Embedder dim sanity
        backend_store = mem.router.stores[0]
        embedding = backend_store._embed(q.question)  # type: ignore[attr-defined]
        _print("embedder dim", len(embedding))
        _print(
            "embedder norm",
            round(sum(x * x for x in embedding) ** 0.5, 6),
        )

        hits = await mem.recall(q.question, k=8)
        _print("hits returned", len(hits))
        gold_lower = q.gold_answer.lower()
        any_match = False
        for ix, h in enumerate(hits):
            content_snip = (h.content or "")[:120].replace("\n", " ")
            contains_gold = gold_lower in (h.content or "").lower()
            if contains_gold:
                any_match = True
            print(
                f"  [{ix}] score={h.score:.4f} type={h.type.value} "
                f"gold_in_content={contains_gold} :: {content_snip!r}"
            )
        _print("gold answer in any hit", any_match)
    finally:
        await mem.close()


async def _diag_locomo() -> None:
    print()
    print("=" * 78)
    print("LoCoMo diagnostic")
    print("=" * 78)
    episodes = _load_locomo_from_disk(LOCOMO_CACHE)
    print(f"loaded {len(episodes)} LoCoMo episodes")
    ep = next((e for e in episodes if e.sessions and e.questions), None)
    if ep is None:
        print("no usable LoCoMo episode found; aborting")
        return
    q = ep.questions[0]
    _print("episode_id", ep.episode_id)
    _print("qid", q["qid"])
    _print("question", q["question"])
    _print("gold_answer", q["gold_answer"])
    _print("num sessions", len(ep.sessions))
    _print("total turns", sum(len(s) for s in ep.sessions))

    db_path = DIAG_DIR / "diag-locomo.db"
    if db_path.exists():
        db_path.unlink()
    DIAG_DIR.mkdir(exist_ok=True)

    agent_id = f"diag-locomo-{ep.episode_id}-{q['qid']}"
    mem = Memory(agent_id=agent_id, stores=[f"sqlite-vec://{db_path.as_posix()}"])
    try:
        first_print = True
        n_ingested = 0
        for sess_ix, session in enumerate(ep.sessions):
            for turn_ix, turn in enumerate(session):
                if not turn.get("content"):
                    continue
                resp = await mem.remember(
                    turn["content"],
                    type=MemoryType.EPISODIC,
                    metadata={
                        "episode_id": ep.episode_id,
                        "session_id": sess_ix,
                        "turn_ix": turn_ix,
                        "role": turn.get("role", "user"),
                    },
                )
                n_ingested += 1
                if first_print:
                    print(
                        f"first remember -> id={resp.id} stored_at={resp.stored_at} "
                        f"stores={resp.stores}"
                    )
                    first_print = False
        _print("rows ingested", n_ingested)

        health = await mem.health()
        per_store = health.get("stores", []) if isinstance(health, dict) else []
        for ps in per_store:
            if ps.get("backend") == "sqlite-vec":
                _print("sqlite-vec memory_count", ps.get("memory_count"))

        backend_store = mem.router.stores[0]
        embedding = backend_store._embed(q["question"])  # type: ignore[attr-defined]
        _print("embedder dim", len(embedding))

        hits = await mem.recall(q["question"], k=8)
        _print("hits returned", len(hits))
        gold_lower = q["gold_answer"].lower()
        any_match = False
        for ix, h in enumerate(hits):
            content_snip = (h.content or "")[:120].replace("\n", " ")
            contains_gold = gold_lower in (h.content or "").lower()
            if contains_gold:
                any_match = True
            print(
                f"  [{ix}] score={h.score:.4f} type={h.type.value} "
                f"gold_in_content={contains_gold} :: {content_snip!r}"
            )
        _print("gold answer in any hit", any_match)
    finally:
        await mem.close()


async def _diag_dirty_db() -> None:
    """Re-run a single LME question against the EXISTING ./lme.db to
    demonstrate the cross-question contamination bug.

    Re-uses one LME question's per-question agent_id and re-ingests into
    the same shared DB. The recall is expected to return rows from OTHER
    agent_ids' worth of ANN candidates, draining the top-k of useful
    content.
    """
    print()
    print("=" * 78)
    print("Dirty-DB diagnostic (against existing lme.db)")
    print("=" * 78)
    shared_db = _REPO_ROOT / "lme.db"
    if not shared_db.exists():
        print("no shared lme.db present; skipping dirty-DB test")
        return
    size_mb = shared_db.stat().st_size / (1024 * 1024)
    _print("shared lme.db size (MB)", round(size_mb, 1))

    questions = _load_longmemeval_from_disk(LME_CACHE)
    q = next(
        (
            qq
            for qq in questions
            if qq.sessions
            and any(turn.get("content") for sess in qq.sessions for turn in sess)
            and qq.gold_answer
        ),
        None,
    )
    if q is None:
        return
    agent_id = f"diag-dirty-{q.qid}"
    mem = Memory(agent_id=agent_id, stores=[f"sqlite-vec://{shared_db.as_posix()}"])
    try:
        n = 0
        for sess_ix, session in enumerate(q.sessions):
            for turn_ix, turn in enumerate(session):
                if not turn.get("content"):
                    continue
                await mem.remember(
                    turn["content"],
                    type=MemoryType.EPISODIC,
                    metadata={"qid": q.qid, "session_id": sess_ix, "turn_ix": turn_ix},
                )
                n += 1
        _print("rows ingested for diag agent", n)
        health = await mem.health()
        per_store = health.get("stores", []) if isinstance(health, dict) else []
        for ps in per_store:
            if ps.get("backend") == "sqlite-vec":
                _print("shared db total memory_count", ps.get("memory_count"))
        hits = await mem.recall(q.question, k=8)
        _print("hits returned (against contaminated DB)", len(hits))
        gold_lower = q.gold_answer.lower()
        any_match = False
        for ix, h in enumerate(hits):
            content_snip = (h.content or "")[:120].replace("\n", " ")
            contains_gold = gold_lower in (h.content or "").lower()
            if contains_gold:
                any_match = True
            print(
                f"  [{ix}] score={h.score:.4f} type={h.type.value} "
                f"gold_in_content={contains_gold} :: {content_snip!r}"
            )
        _print("gold answer in any hit (dirty DB)", any_match)
    finally:
        await mem.close()


async def main() -> int:
    print(f"HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')}")
    print(f"TRANSFORMERS_OFFLINE={os.environ.get('TRANSFORMERS_OFFLINE')}")
    await _diag_lme()
    await _diag_locomo()
    await _diag_dirty_db()
    return 0


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        raise SystemExit(asyncio.run(main()))
