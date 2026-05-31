"""Smoke harness for the adversarial-fusion experiment.

This test is *not* part of the default unit suite. It is marked
``benchmark`` so default ``pytest -m "not integration and not benchmark"``
skips it; opt in with ``pytest -m benchmark``.

What it checks
--------------
* The adversarial-fusion pipeline (corpus â†’ stores â†’ router â†’ metrics)
  wires end-to-end and produces a per-K curve of the expected shape.
* Qualitative direction under ``fusion=max`` (the algorithm that *is*
  score-sensitive and therefore breaks under adversarial input):
    - recall@5 at K=0 is strictly better than at K=M (more attacker
      budget â†’ worse fused recall).
    - adversarial leak rate is monotonically non-decreasing in K (more
      attacker budget â†’ more attacker rows in the fused top-5).
* Under ``fusion=rrf`` we assert the opposite property â€” RRF should
  remain robust against a single rogue store, so recall@5 doesn't drop
  catastrophically across the swept K. This is the property
  ``docs/THREATS.md`` Â§3.3 claims.

If the script's helpers can't be imported (e.g. amp / pydantic missing
from the test environment) the module is skipped cleanly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The runner imports amp.* â€” skip cleanly if the memwire package isn't installed
# in this environment.
_HAS_AMP = importlib.util.find_spec("amp") is not None

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.skipif(
        not _HAS_AMP,
        reason="amp not importable; install the package to run the adversarial harness.",
    ),
]


@pytest.mark.asyncio
async def test_adversarial_pipeline_max_collapses() -> None:
    """Under ``fusion=max`` more attacker budget must degrade recall.

    Tiny config (N=3 stores, M=10 memories, Q=3 queries, K in {0,2,4})
    so the test stays well under a second. We assert directional
    properties, not numeric thresholds â€” that's what protects against
    a real regression in the router's fusion math without making the
    test fragile to harmless seed changes.
    """
    from memwire.models import FusionAlgorithm
    from scripts.run_adversarial import _sweep_k

    result = await _sweep_k(
        fusion=FusionAlgorithm.MAX,
        n_backends=3,
        n_adversarial=1,
        corpus_size=10,
        n_queries=3,
        attack_budget_step=2,
        seed=42,
    )

    # The sweep should at least contain K=0 and K=M=10.
    assert result.k_attack[0] == 0
    assert result.k_attack[-1] == 10
    assert len(result.recall_at_5) == len(result.k_attack)
    assert len(result.leak) == len(result.k_attack)
    assert len(result.displacement) == len(result.k_attack)

    # Direction: recall at K=0 (no attacker) is strictly better than at
    # K=M (max attacker budget). Under MAX fusion the attacker's score
    # ties or beats the benign rank-0 score, so this MUST drop.
    assert result.recall_at_5[0] > result.recall_at_5[-1], (
        f"recall@5 did not degrade under MAX fusion: "
        f"K=0 -> {result.recall_at_5[0]:.3f}, K=M -> {result.recall_at_5[-1]:.3f}"
    )

    # Adversarial leak rate is monotonically non-decreasing in K.
    # (Non-decreasing rather than strictly-increasing because at small K
    # the attacker may not yet have enough budget to displace tied rows.)
    for i in range(1, len(result.leak)):
        assert result.leak[i] >= result.leak[i - 1] - 1e-9, (
            f"leak rate decreased at K={result.k_attack[i]}: "
            f"prev={result.leak[i - 1]:.3f}, curr={result.leak[i]:.3f}"
        )

    # At K=0 leak must be exactly zero (no attacker rows in play).
    assert result.leak[0] == 0.0
    # By K=M the rogue store is filling top ranks with attackers â€” the
    # leak must be observably non-zero.
    assert result.leak[-1] > 0.0


@pytest.mark.asyncio
async def test_adversarial_pipeline_rrf_robust() -> None:
    """Under ``fusion=rrf`` a 1-of-3 rogue store does NOT collapse recall.

    This is the property ``docs/THREATS.md`` Â§3.3 claims and the
    experiment's defensible-operating-point story rests on. If the
    router's RRF math regresses (e.g. someone accidentally adds the
    item's own score into ``_fusion_contribution``), this test will
    catch it because recall@5 will drop below the floor.
    """
    from memwire.models import FusionAlgorithm
    from scripts.run_adversarial import _sweep_k

    result = await _sweep_k(
        fusion=FusionAlgorithm.RRF,
        n_backends=3,
        n_adversarial=1,
        corpus_size=10,
        n_queries=3,
        attack_budget_step=2,
        seed=42,
    )

    # With 2 benign votes per gold id beating 1 rogue vote per attacker id,
    # recall@5 should stay perfect or very close to it across the sweep.
    # 0.6 is the same floor the recall microbenchmark uses; a regression
    # below that here would mean the router's RRF lost its consensus
    # property.
    for k, r in zip(result.k_attack, result.recall_at_5, strict=True):
        assert r >= 0.6, f"RRF recall@5 collapsed at K={k}: {r:.3f}"

    # And the operating-point classifier should agree.
    assert result.operating_point_k is not None
    assert result.operating_point_k == result.k_attack[-1], (
        f"operating point K={result.operating_point_k} != max K={result.k_attack[-1]}"
    )
