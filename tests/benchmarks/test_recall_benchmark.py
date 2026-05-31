"""Smoke harness for the recall microbenchmark.

This test is *not* part of the default unit suite. It is marked
``slow`` and ``benchmark`` so default ``pytest -m "not integration"``
skips it; opt in with ``pytest -m benchmark``.

What it checks
--------------
* The benchmark pipeline (dataset → store → embedder → router → recall)
  still wires end-to-end.
* A small subset (5 queries) hits a loose recall@5 floor (>= 0.6) and an
  ingest p95 floor (< 200 ms). The thresholds are deliberately generous;
  they only catch a true regression, not a normal-jitter slowdown.

If sentence-transformers isn't installed the test is skipped with a
clear message — we don't quietly degrade to the fake embedder here,
because the harness's whole point is to assert real-embedder quality.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Skip the whole module up-front when sentence-transformers isn't installed.
# importlib.util.find_spec returns None without triggering the import side-effects.
_HAS_ST = importlib.util.find_spec("sentence_transformers") is not None

pytestmark = [
    pytest.mark.slow,
    pytest.mark.benchmark,
    pytest.mark.skipif(
        not _HAS_ST,
        reason="sentence-transformers not installed; install with `pip install "
        "'memorywire[sqlite-vec]'` to run recall microbenchmark.",
    ),
]


@pytest.mark.asyncio
async def test_recall_microbenchmark_subset() -> None:
    """Run a 5-query subset of the microbenchmark and assert loose floors."""
    # Local imports so the module loads cleanly when sentence-transformers
    # is absent and the file is collected by pytest with -m benchmark.
    import argparse

    # Importing the runner brings tests/benchmarks/dataset in via its own
    # sys.path tweak — safe to do here.
    from scripts.run_microbench import _run

    args = argparse.Namespace(
        queries=5,
        k=5,
        embedder="real",
        json=False,
        target="single",
    )
    result = await _run(args)

    # The benchmark must have actually executed with the real embedder.
    # If it fell back to fake we want a loud failure, not a quiet pass.
    assert result.fallback_reason is None, (
        f"real embedder failed: {result.fallback_reason} — install/load failed"
    )
    assert result.embedder == "sentence-transformers/all-MiniLM-L6-v2"

    # Loose recall floor: 5 queries, all the first five are paraphrase /
    # exact-match scenarios with a single gold id. recall@5 >= 0.6 catches
    # a true regression (e.g. embedder dim mismatch).
    assert result.recall_at_k_mean >= 0.6, (
        f"recall@5 collapsed below floor: {result.recall_at_k_mean:.3f}"
    )

    # Latency floor: ingest p95 < 200 ms on a modern laptop. We measure
    # CPU-only inference for a 384-d transformer; the actual number is
    # typically 15-30 ms p95. 200 ms is a no-regression sanity floor.
    assert result.ingest_p95_ms < 200.0, (
        f"ingest p95 regressed: {result.ingest_p95_ms:.2f} ms (floor 200 ms)"
    )
