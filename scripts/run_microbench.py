"""AMP v0 recall microbenchmark — one honest number for the launch blog post.

This script ingests a hand-authored 100-fact corpus and runs a 50-query
recall pass, measuring per-call latency and labelled recall@k. It is the
*only* numbers source for the v0 launch; see ``docs/benchmarks.md`` for
the methodology framing. LongMemEval / LoCoMo / BEAM are out of scope
for v0 and arrive in v0.2.

Why a microbenchmark and not LongMemEval?

* LongMemEval requires a gated dataset plus a paid GPT-4 grader.
* LoCoMo similarly requires a grader and hours of model time.
* For a "shape" number — "AMP recalls 50k memories in <N>ms at recall@5
  = <X>" — a hand-authored corpus is honest and reproducible on a
  laptop. v0.2 wires LongMemEval properly with a grader budget.

What this exercises

* The real :class:`amp.api.Memory` facade over the real
  :class:`amp.store.sqlite_vec.SqliteVecStore` adapter (sqlite-vec ANN
  fused with FTS5 keyword via intra-store RRF, per spec §5).
* By default the real ``sentence-transformers/all-MiniLM-L6-v2`` embedder.
  If sentence-transformers isn't installed (or the model can't load),
  falls back to a sha256-derived deterministic 384-d "fake" embedder.
  The script reports which embedder was used; numbers obtained with
  the fake embedder are **not** representative of real recall quality
  and the blog post should note that explicitly.

CLI surface

* ``--queries N`` — limit query count for a smoke run (default: all 50).
* ``--k N`` — top-k passed to :meth:`Memory.recall` (default: 5).
* ``--embedder {real,fake}`` — force the embedder (default: ``real``
  when sentence-transformers loads, else ``fake``).
* ``--json`` — emit structured JSON instead of human-readable text.
* ``--target {single,fusion}`` — ``single`` (default) uses one
  sqlite-vec store; ``fusion`` uses two stores so the router exercises
  inter-store RRF (helps the "AMP improves recall with fusion" story).

Exit codes

* ``0`` on success (regardless of recall@5 floor — the pytest harness
  asserts the floor).
* Non-zero if the dataset, store, or embedder choice errors out.

Usage::

    .venv/Scripts/python.exe scripts/run_microbench.py
    .venv/Scripts/python.exe scripts/run_microbench.py --json
    .venv/Scripts/python.exe scripts/run_microbench.py --target fusion
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import platform
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Make ``tests.benchmarks.dataset`` importable when the script is run
# from anywhere — the repo root is the parent of this script's dir.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from amp import Memory, MemoryType  # noqa: E402
from amp.store.sqlite_vec import SqliteVecStore  # noqa: E402
from tests.benchmarks.dataset import FACTS, QUERIES  # noqa: E402

EmbedderFn = Callable[[str], list[float]]

# Single shared agent_id for every operation in this benchmark.
AGENT_ID = "microbench"
# all-MiniLM-L6-v2 produces 384-d vectors; the fake embedder matches.
EMBED_DIM = 384


# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------


def _fake_embedder(text: str) -> list[float]:
    """Deterministic 384-d embedding derived from sha256.

    Same shape as the one in :file:`examples/01_quickstart.py`. Used as a
    fallback when sentence-transformers can't load (no GPU/CPU torch,
    no model weights, no network). Numbers measured with this embedder
    are **not** representative of real recall quality.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    repeats = (EMBED_DIM // len(digest)) + 1
    blob = (digest * repeats)[:EMBED_DIM]
    return [b / 255.0 for b in blob]


def _load_real_embedder() -> EmbedderFn:
    """Build the real sentence-transformers embedder.

    Raises on any failure (missing package, model download failure,
    torch import errors). The caller catches and falls back if asked.
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def _encode(text: str) -> list[float]:
        vec = model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vec]

    # Warm-up call so the first ingest doesn't pay for one-shot init.
    _encode("warmup")
    return _encode


def _resolve_embedder(choice: str) -> tuple[EmbedderFn, str, str | None]:
    """Resolve the ``--embedder`` flag into a callable plus a label.

    Returns ``(embedder, label, fallback_reason)``. ``fallback_reason`` is
    ``None`` when the requested embedder was used as-is, or a short
    diagnostic string when the real embedder was requested but failed
    and we fell back.
    """
    if choice == "fake":
        return _fake_embedder, "fake-sha256", None
    if choice == "real":
        try:
            return _load_real_embedder(), "sentence-transformers/all-MiniLM-L6-v2", None
        except Exception as exc:
            # Broad on purpose: torch import errors, HuggingFace network
            # failures, model-file corruption, and weight-load crashes
            # all look different and all warrant the same fallback path.
            reason = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:200]
            return _fake_embedder, "fake-sha256", reason
    raise ValueError(f"unknown embedder choice: {choice!r}")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    """Structured result; serialised to JSON for blog-post copy-paste."""

    embedder: str
    fallback_reason: str | None
    target: str
    n_facts: int
    n_queries: int
    k: int
    ingest_p50_ms: float
    ingest_p95_ms: float
    ingest_p99_ms: float
    ingest_mean_ms: float
    recall_p50_ms: float
    recall_p95_ms: float
    recall_p99_ms: float
    recall_mean_ms: float
    recall_at_k_mean: float
    precision_at_k_mean: float
    no_match_correct: int
    no_match_total: int
    failures: list[dict[str, Any]] = field(default_factory=list)
    total_wall_s: float = 0.0
    python_version: str = ""
    platform: str = ""


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """Return the ``pct`` percentile of ``values`` (0 <= pct <= 100)."""
    if not values:
        return 0.0
    s = sorted(values)
    # Nearest-rank method; fine at n=50 / n=100 and avoids interpolation surprises.
    k = max(0, min(len(s) - 1, round(pct / 100.0 * (len(s) - 1))))
    return s[k]


# ---------------------------------------------------------------------------
# Benchmark core
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> BenchmarkResult:
    """Run the benchmark per the parsed CLI args, return the structured result."""
    embedder, embedder_label, fallback_reason = _resolve_embedder(args.embedder)
    queries = QUERIES[: args.queries] if args.queries is not None else QUERIES

    # Build the store(s). "single" gives a one-store router so we still go
    # through the public Memory facade. "fusion" gives two stores so the
    # inter-store RRF path executes.
    stores: list[SqliteVecStore] = [
        SqliteVecStore(":memory:", embedding_dim=EMBED_DIM, embedder=embedder)
    ]
    if args.target == "fusion":
        stores.append(SqliteVecStore(":memory:", embedding_dim=EMBED_DIM, embedder=embedder))

    mem = Memory(agent_id=AGENT_ID, stores=stores)

    wall_start = time.perf_counter()

    try:
        # ---- Ingest ------------------------------------------------------
        ingest_latencies_ms: list[float] = []
        # Map gold fact-id -> store memory id, so we can score recalls.
        gold_to_store_id: dict[str, str] = {}
        for fact in FACTS:
            mtype = MemoryType(fact["type"])
            # Carry the dataset id in metadata so we can score by it without
            # depending on the store-generated uuid.
            t0 = time.perf_counter()
            resp = await mem.remember(
                fact["content"],
                type=mtype,
                user_id=fact["user_id"],
                metadata={"dataset_id": fact["id"]},
            )
            ingest_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            gold_to_store_id[fact["id"]] = resp.id

        # ---- Recall ------------------------------------------------------
        recall_latencies_ms: list[float] = []
        recall_scores: list[float] = []
        precision_scores: list[float] = []
        no_match_total = 0
        no_match_correct = 0
        failures: list[dict[str, Any]] = []

        for q in queries:
            t0 = time.perf_counter()
            hits = await mem.recall(q["query"], k=args.k, user_id=q["user_id"])
            recall_latencies_ms.append((time.perf_counter() - t0) * 1000.0)

            # Resolve store ids back to dataset ids via metadata.
            returned_dataset_ids: list[str] = []
            for hit in hits:
                meta = hit.metadata or {}
                ds_id = meta.get("dataset_id")
                if isinstance(ds_id, str):
                    returned_dataset_ids.append(ds_id)

            gold = set(q["gold_ids"])
            returned_set = set(returned_dataset_ids)

            if not gold:
                # No-match probe: any hit is a false positive. Score 1.0 if
                # we returned nothing, else 0.0. Don't pollute the recall@k
                # mean — track separately so the headline number stays clean.
                no_match_total += 1
                if not hits:
                    no_match_correct += 1
                else:
                    failures.append(
                        {
                            "query": q["query"],
                            "user_id": q["user_id"],
                            "gold_ids": [],
                            "returned_dataset_ids": returned_dataset_ids,
                            "kind": "false_positive_on_no_match_probe",
                        }
                    )
                continue

            hit_count = len(gold & returned_set)
            recall_at_k = hit_count / len(gold)
            precision_at_k = hit_count / args.k if args.k > 0 else 0.0
            recall_scores.append(recall_at_k)
            precision_scores.append(precision_at_k)

            missing = sorted(gold - returned_set)
            if missing:
                failures.append(
                    {
                        "query": q["query"],
                        "user_id": q["user_id"],
                        "gold_ids": sorted(gold),
                        "returned_dataset_ids": returned_dataset_ids,
                        "missing_dataset_ids": missing,
                        "kind": "partial_or_full_miss",
                    }
                )

        wall_s = time.perf_counter() - wall_start

        return BenchmarkResult(
            embedder=embedder_label,
            fallback_reason=fallback_reason,
            target=args.target,
            n_facts=len(FACTS),
            n_queries=len(queries),
            k=args.k,
            ingest_p50_ms=_percentile(ingest_latencies_ms, 50),
            ingest_p95_ms=_percentile(ingest_latencies_ms, 95),
            ingest_p99_ms=_percentile(ingest_latencies_ms, 99),
            ingest_mean_ms=statistics.fmean(ingest_latencies_ms) if ingest_latencies_ms else 0.0,
            recall_p50_ms=_percentile(recall_latencies_ms, 50),
            recall_p95_ms=_percentile(recall_latencies_ms, 95),
            recall_p99_ms=_percentile(recall_latencies_ms, 99),
            recall_mean_ms=statistics.fmean(recall_latencies_ms) if recall_latencies_ms else 0.0,
            recall_at_k_mean=statistics.fmean(recall_scores) if recall_scores else 0.0,
            precision_at_k_mean=statistics.fmean(precision_scores) if precision_scores else 0.0,
            no_match_correct=no_match_correct,
            no_match_total=no_match_total,
            failures=failures,
            total_wall_s=wall_s,
            python_version=platform.python_version(),
            platform=f"{platform.system()} {platform.release()} {platform.machine()}",
        )
    finally:
        await mem.close()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_text(result: BenchmarkResult) -> str:
    """Pretty human-readable report. Each section maps to a blog-post line."""
    lines: list[str] = []
    lines.append("AMP v0 recall microbenchmark")
    lines.append("=" * 70)
    lines.append(f"  embedder           : {result.embedder}")
    if result.fallback_reason:
        lines.append(f"  fallback reason    : {result.fallback_reason}")
    lines.append(f"  target             : {result.target}")
    lines.append(f"  facts ingested     : {result.n_facts}")
    lines.append(f"  queries run        : {result.n_queries}")
    lines.append(f"  k                  : {result.k}")
    lines.append(f"  python             : {result.python_version}")
    lines.append(f"  platform           : {result.platform}")
    lines.append("")
    lines.append("Ingest latency (ms)")
    lines.append(
        f"  p50={result.ingest_p50_ms:7.2f}  "
        f"p95={result.ingest_p95_ms:7.2f}  "
        f"p99={result.ingest_p99_ms:7.2f}  "
        f"mean={result.ingest_mean_ms:7.2f}"
    )
    lines.append("Recall latency (ms)")
    lines.append(
        f"  p50={result.recall_p50_ms:7.2f}  "
        f"p95={result.recall_p95_ms:7.2f}  "
        f"p99={result.recall_p99_ms:7.2f}  "
        f"mean={result.recall_mean_ms:7.2f}"
    )
    lines.append("Quality")
    lines.append(f"  recall@{result.k}   mean = {result.recall_at_k_mean:.3f}")
    lines.append(f"  precision@{result.k} mean = {result.precision_at_k_mean:.3f}")
    lines.append(f"  no-match correct = {result.no_match_correct}/{result.no_match_total}")
    lines.append(f"  total wall time  = {result.total_wall_s:.2f} s")
    if result.failures:
        lines.append("")
        lines.append(f"Per-query failures ({len(result.failures)})")
        for f in result.failures:
            kind = f.get("kind", "?")
            if kind == "false_positive_on_no_match_probe":
                lines.append(
                    f"  [FP] '{f['query']}' (user={f['user_id']}): "
                    f"returned {f['returned_dataset_ids']}"
                )
            else:
                lines.append(
                    f"  [MISS] '{f['query']}' (user={f['user_id']}): "
                    f"missing {f.get('missing_dataset_ids', [])} "
                    f"of {f.get('gold_ids', [])} "
                    f"(returned {f.get('returned_dataset_ids', [])})"
                )
    return "\n".join(lines)


def _format_json(result: BenchmarkResult) -> str:
    return json.dumps(asdict(result), indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser; factored out so tests can introspect it."""
    p = argparse.ArgumentParser(
        prog="run_microbench",
        description="AMP v0 recall microbenchmark.",
    )
    p.add_argument(
        "--queries",
        type=int,
        default=None,
        help="Limit number of queries (default: all 50).",
    )
    p.add_argument(
        "--k",
        type=int,
        default=5,
        help="Top-k for recall (default: 5).",
    )
    p.add_argument(
        "--embedder",
        choices=("real", "fake"),
        default="real",
        help="Embedder to use (default: real; falls back to fake if real fails).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit results as JSON (blog-post copy-paste friendly).",
    )
    p.add_argument(
        "--target",
        choices=("single", "fusion"),
        default="single",
        help="single = one sqlite-vec store; fusion = two stores (router RRF).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    if args.json:
        print(_format_json(result))
    else:
        print(_format_text(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by integration runs
    with contextlib.suppress(BrokenPipeError):
        raise SystemExit(main())
