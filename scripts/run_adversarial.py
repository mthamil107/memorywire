"""Adversarial fusion experiment — 1-of-N poisoned backend vs MemoryRouter.

This is the experiment promised by ``docs/THREATS.md`` §3.3:
how much does a single malicious child store pollute the fused
top-k that :class:`amp.router.MemoryRouter` returns? Where does
the RRF defense break down?

Methodology
-----------
* Build a synthetic corpus of ``M`` memories with deterministic ids.
* Hand-build ``Q`` queries; each query's "gold set" is a small, fixed
  subset of memory ids that a correctly behaving store should return.
* Wire ``N`` :class:`StubStore` children into a real
  :class:`amp.router.MemoryRouter`. ``N - n_adversarial`` of them are
  *benign* — they return the gold rows for each query in their correct
  order, with some random noise tail to fill out per-store k. One (or
  more, configurable) backend is *adversarial* — it injects ``K``
  attacker-controlled rows at the top ranks, then optionally a benign
  tail (so the rogue store still looks "normal" past rank K).
* For each ``K`` in ``0, S, 2S, ..., M``, run all ``Q`` queries through
  ``router.recall(k=5)`` and measure:
    - **recall@5** against the gold set (per-query mean).
    - **leak rate** — fraction of returned rows whose id is one of the
      attacker's injected rows.
    - **displacement rate** — fraction of gold ids that *should* be in
      top-5 (in the un-poisoned baseline) but were pushed out by
      attacker rows.
* Plot or tabulate curves of those metrics vs ``K``.

Limitations / honest framing
----------------------------
* Synthetic: uniform-difficulty queries, no LLM grader, no real
  embedder. The benign backends are *perfect* — they always return
  the gold set in the right order. Real-world per-store recall is
  noisier; this number is therefore an *upper bound* on AMP's
  resilience under one specific attack shape.
* Adversary has full knowledge: it knows the per-store ``k * 4``
  over-fetch and can fill exactly that many top slots.
* 1-of-N case only by default; ``--n-adversarial`` lets you sweep
  ``n_adversarial > 1`` to verify the "RRF holds only as long as
  the majority is honest" claim.
* Three fusion modes (``rrf`` / ``max`` / ``weighted``) covered. The
  weighted variant uses equal weights here (it would be lower with
  attacker-down-weighted weights — that's a deployment knob, not a
  protocol property).
* Latency, FTS5, real ANN — all out of scope. This experiment
  measures *fusion math under adversarial input*, not end-to-end
  recall.

CLI surface
-----------
* ``--n-backends N``           total stores in the router (default 3)
* ``--n-adversarial K``        how many backends are malicious (default 1)
* ``--corpus-size M``          memories in the gold corpus (default 50)
* ``--queries Q``              queries per K value (default 20)
* ``--attack-budget-step S``   sample K = 0, S, 2S, ... up to M (default 5)
* ``--target ALGO``            ``rrf`` / ``max`` / ``weighted`` (default ``rrf``)
* ``--seed N``                 RNG seed (default 1337)
* ``--json``                   emit JSON instead of text
* ``--plot``                   write ``docs/adversarial-results.png`` if
                               matplotlib is installed (silently skipped
                               otherwise; the run still emits JSON / text)
* ``--out-json PATH``          also write the JSON to this path

Usage::

    .venv/Scripts/python.exe scripts/run_adversarial.py
    .venv/Scripts/python.exe scripts/run_adversarial.py --json
    .venv/Scripts/python.exe scripts/run_adversarial.py --target max --json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Make ``amp.*`` importable when the script is run from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from amp.models import (  # noqa: E402
    ExpireAction,
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    ForgetStoreResult,
    FusionAlgorithm,
    MemoryType,
    MergeRequest,
    MergeResponse,
    MergeStrategy,
    RecallHit,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)
from amp.router import MemoryRouter  # noqa: E402
from amp.store.base import Capability  # noqa: E402

# ---------------------------------------------------------------------------
# Stub stores — benign and adversarial. Both satisfy the :class:`MemoryStore`
# Protocol structurally; they implement just enough surface for the router's
# recall fan-out + fusion path.
# ---------------------------------------------------------------------------


class _BaseStubStore:
    """Common no-op surface so the router can treat us like any backend.

    Only ``recall`` is non-trivial — adversarial-fusion is a recall-side
    experiment, so the other ops are stubbed to satisfy the Protocol.
    """

    BACKEND_NAME = "stub"

    def __init__(self, *, backend_name: str) -> None:
        self.BACKEND_NAME = backend_name

    @property
    def capabilities(self) -> set[str]:
        return {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.PROCEDURAL,
            Capability.EMOTIONAL,
        }

    async def remember(self, req: RememberRequest) -> RememberResponse:
        return RememberResponse(
            id=f"{self.BACKEND_NAME}-noop",
            stored_at=0,
            stores=[self.BACKEND_NAME],
            pending_approval=False,
            approval_url=None,
        )

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        return ForgetResponse(
            forgotten_ids=[],
            hard_delete=bool(req.hard_delete),
            stores=[ForgetStoreResult(store=self.BACKEND_NAME, count=0)],
            pending_approval=False,
            approval_url=None,
        )

    async def merge(self, req: MergeRequest) -> MergeResponse:
        return MergeResponse(
            canonical=req.canonical,
            merged_count=0,
            strategy_used=req.strategy
            if req.strategy is not None
            else MergeStrategy.KEEP_CANONICAL,
            stores=[self.BACKEND_NAME],
        )

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        return ExpireResponse(
            matched_count=0,
            action_taken=req.action if req.action is not None else ExpireAction.FORGET,
            stores=[self.BACKEND_NAME],
        )

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "backend": self.BACKEND_NAME}


class BenignStore(_BaseStubStore):
    """A benign backend with a fixed per-query gold ranking.

    The benchmark seeds it with ``per_query_results`` — a map from
    ``query`` string to a ranked list of memory ids. On ``recall`` it
    looks up the query and returns the prefix of length ``req.k``.

    "Fixed" because we want the benign signal stable so the *only*
    independent variable is the adversary's behaviour.
    """

    def __init__(
        self,
        *,
        backend_name: str,
        per_query_results: dict[str, list[str]],
    ) -> None:
        super().__init__(backend_name=backend_name)
        self._per_query_results = per_query_results

    async def recall(self, req: RecallRequest) -> RecallResponse:
        ranked_ids = self._per_query_results.get(req.query, [])
        k = req.k or 5
        ranked = ranked_ids[:k]
        # Synthesize per-rank decreasing scores so MAX/WEIGHTED fusion still
        # has a meaningful gradient. RRF ignores scores by construction.
        hits = [
            RecallHit(
                id=mid,
                type=MemoryType.SEMANTIC,
                content=f"benign-content-{mid}",
                score=1.0 - rank * 0.01,
                metadata=None,
                created_at=0,
                supporting=[],
                source_store=self.BACKEND_NAME,
            )
            for rank, mid in enumerate(ranked)
        ]
        return RecallResponse(
            results=hits,
            fusion_used=req.fusion if req.fusion is not None else FusionAlgorithm.RRF,
            stores_queried=[self.BACKEND_NAME],
            latency_ms=1,
        )


class AdversarialStore(_BaseStubStore):
    """A malicious backend that injects ``K`` attacker rows at the top.

    Parameters
    ----------
    attack_budget:
        Number of attacker ids the store places at ranks ``0..K-1``.
    attacker_ids:
        Pool of fabricated ids to draw from. The store fills the top
        ranks from the front of this list deterministically.
    benign_tail:
        Optional per-query map from query → ranked benign-id list. When
        present, the store appends the benign tail *after* the attacker
        block so the rogue store looks "mostly benign" past rank K.
        When absent the store returns only attacker rows.
    top_score:
        Score it stamps on its rank-0 row. Used to give ``fusion=max``
        and ``fusion=weighted`` an honest worst-case (attacker confidently
        claims it has the perfect answer).
    """

    def __init__(
        self,
        *,
        backend_name: str,
        attack_budget: int,
        attacker_ids: list[str],
        benign_tail: dict[str, list[str]] | None = None,
        top_score: float = 1.0,
    ) -> None:
        super().__init__(backend_name=backend_name)
        self._attack_budget = max(0, int(attack_budget))
        self._attacker_ids = list(attacker_ids)
        self._benign_tail = benign_tail or {}
        self._top_score = top_score

    async def recall(self, req: RecallRequest) -> RecallResponse:
        k = req.k or 5
        attacker_block = self._attacker_ids[: self._attack_budget][:k]

        results: list[RecallHit] = []
        for rank, mid in enumerate(attacker_block):
            results.append(
                RecallHit(
                    id=mid,
                    type=MemoryType.SEMANTIC,
                    content=f"adversarial-content-{mid}",
                    # Linear ramp from top_score down; floors at 0.0 so a
                    # huge K can't underflow.
                    score=max(self._top_score - rank * 0.001, 0.0),
                    metadata={"adversarial": True},
                    created_at=0,
                    supporting=[],
                    source_store=self.BACKEND_NAME,
                )
            )

        remaining = max(0, k - len(results))
        if remaining > 0 and self._benign_tail:
            for rank_offset, mid in enumerate(self._benign_tail.get(req.query, [])[:remaining]):
                results.append(
                    RecallHit(
                        id=mid,
                        type=MemoryType.SEMANTIC,
                        content=f"benign-tail-{mid}",
                        score=0.5 - rank_offset * 0.01,
                        metadata=None,
                        created_at=0,
                        supporting=[],
                        source_store=self.BACKEND_NAME,
                    )
                )

        return RecallResponse(
            results=results,
            fusion_used=req.fusion if req.fusion is not None else FusionAlgorithm.RRF,
            stores_queried=[self.BACKEND_NAME],
            latency_ms=1,
        )


# ---------------------------------------------------------------------------
# Synthetic dataset construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuerySpec:
    """One synthetic query plus its expected gold ids."""

    query: str
    gold_ids: tuple[str, ...]


def _build_corpus(
    corpus_size: int,
    n_queries: int,
    *,
    rng: random.Random,
    gold_per_query: int = 2,
) -> tuple[list[str], list[QuerySpec]]:
    """Return ``(memory_ids, queries)`` for the experiment.

    * ``memory_ids`` — ``corpus_size`` deterministic ids ``m000..m{M-1}``.
    * ``queries`` — ``n_queries`` ``QuerySpec`` rows. Each query is given
      ``gold_per_query`` distinct gold ids drawn without replacement from
      the corpus, plus a "distractor" tail (the rest of the per-query
      ranked list) sampled from the remaining ids.
    """
    memory_ids = [f"m{i:03d}" for i in range(corpus_size)]
    queries: list[QuerySpec] = []
    for q in range(n_queries):
        gold = tuple(rng.sample(memory_ids, k=gold_per_query))
        queries.append(QuerySpec(query=f"q{q:03d}", gold_ids=gold))
    return memory_ids, queries


def _build_benign_per_query(
    queries: list[QuerySpec],
    memory_ids: list[str],
    *,
    rng: random.Random,
    per_store_k: int,
) -> dict[str, list[str]]:
    """Build the benign per-query ranked id list a benign store returns.

    The gold ids occupy the top ranks (in the order they appear in
    ``query.gold_ids``); distractors fill the rest of the list up to
    ``per_store_k`` so the router's k*4 over-fetch sees a full list.

    Each call to this function uses an independent random.shuffle, so
    distinct benign stores will see *different* distractor orderings —
    realistic for backends with different embedders / indexes. Gold ids
    always sit at the top to model "benign stores agree on the correct
    answer", which is the assumption the experiment is testing the
    router under.
    """
    out: dict[str, list[str]] = {}
    for q in queries:
        gold_list = list(q.gold_ids)
        pool = [mid for mid in memory_ids if mid not in gold_list]
        rng.shuffle(pool)
        ranked = gold_list + pool[: max(0, per_store_k - len(gold_list))]
        out[q.query] = ranked
    return out


def _build_attacker_ids(corpus_size: int, *, max_budget: int) -> list[str]:
    """Generate a pool of attacker-controlled, fabricated memory ids.

    They are *disjoint* from the gold corpus (different prefix) so the
    leak/displacement metrics are unambiguous: if an ``a***`` id appears
    in the top-5, it is attacker output by construction.
    """
    # Make sure we have enough to fill the largest attack budget tested.
    n = max(max_budget, corpus_size) + 16
    return [f"a{i:04d}" for i in range(n)]


# ---------------------------------------------------------------------------
# Per-K experiment runner
# ---------------------------------------------------------------------------


@dataclass
class PerKResult:
    """Metrics at one attack-budget value."""

    k_attack: int
    recall_at_5: float
    leak: float
    displacement: float


@dataclass
class AdversarialResult:
    """Aggregate result for one full sweep (JSON-serialisable)."""

    fusion: str
    n_backends: int
    n_adversarial: int
    corpus_size: int
    n_queries: int
    attack_budget_step: int
    seed: int
    k_attack: list[int] = field(default_factory=list)
    recall_at_5: list[float] = field(default_factory=list)
    leak: list[float] = field(default_factory=list)
    displacement: list[float] = field(default_factory=list)
    # Operating-point: the largest K where recall@5 stays >= 0.6.
    operating_point_k: int | None = None
    operating_point_recall: float | None = None


async def _run_one_query(
    router: MemoryRouter,
    q: QuerySpec,
    attacker_id_set: set[str],
    baseline_top5_gold: set[str],
    *,
    fusion: FusionAlgorithm,
) -> tuple[float, float, float]:
    """Run one query, return ``(recall, leak, displacement)``.

    * ``recall`` — fraction of ``q.gold_ids`` in the fused top-5.
    * ``leak`` — fraction of fused top-5 whose id is in ``attacker_id_set``.
    * ``displacement`` — fraction of ids in ``baseline_top5_gold`` that
      are *missing* from the fused top-5 (i.e. that the attacker pushed out).
      Returns 0.0 when the baseline gold set in top-5 was empty.
    """
    req = RecallRequest(agent_id="adv", query=q.query, k=5, fusion=fusion)
    resp = await router.recall(req)
    returned_ids = [hit.id for hit in resp.results]
    returned_set = set(returned_ids)
    gold_set = set(q.gold_ids)

    recall = len(gold_set & returned_set) / len(gold_set) if gold_set else 0.0

    leak = (
        sum(1 for mid in returned_ids if mid in attacker_id_set) / len(returned_ids)
        if returned_ids
        else 0.0
    )

    if baseline_top5_gold:
        displaced = baseline_top5_gold - returned_set
        displacement = len(displaced) / len(baseline_top5_gold)
    else:
        displacement = 0.0

    return recall, leak, displacement


async def _sweep_k(
    *,
    fusion: FusionAlgorithm,
    n_backends: int,
    n_adversarial: int,
    corpus_size: int,
    n_queries: int,
    attack_budget_step: int,
    seed: int,
) -> AdversarialResult:
    """Sweep attack budget K, return one :class:`AdversarialResult`."""
    if n_adversarial >= n_backends:
        raise ValueError(
            f"n_adversarial ({n_adversarial}) must be < n_backends ({n_backends}); "
            "at least one benign backend is required for the experiment to be meaningful."
        )

    rng = random.Random(seed)
    memory_ids, queries = _build_corpus(corpus_size, n_queries, rng=rng)
    # Router over-fetches k*4 per store (router.py:350). recall(k=5) → 20.
    # Build benign lists long enough that the router sees a saturated tail.
    per_store_k = max(corpus_size, 20)
    n_benign = n_backends - n_adversarial
    # Each benign store gets its OWN distractor permutation — realistic
    # for distinct backends with distinct embedders / indexes. Gold ids
    # remain at the top across all benign stores (benign stores agree on
    # the correct answer; only distractor tail differs).
    benign_per_query_per_store: list[dict[str, list[str]]] = [
        _build_benign_per_query(
            queries,
            memory_ids,
            rng=random.Random(seed + 101 + i),
            per_store_k=per_store_k,
        )
        for i in range(n_benign)
    ]
    # The rogue store, if it returns a benign tail, uses yet another
    # distractor permutation so it looks like an independent backend.
    rogue_benign_tail = _build_benign_per_query(
        queries,
        memory_ids,
        rng=random.Random(seed + 999),
        per_store_k=per_store_k,
    )
    attacker_ids = _build_attacker_ids(corpus_size, max_budget=corpus_size)
    attacker_id_set = set(attacker_ids)

    # Baseline (K=0) top-5 ids per query — anything in this set that gets
    # ejected at K>0 counts as "displaced".
    baseline_top5_per_query: dict[str, set[str]] = {}

    result = AdversarialResult(
        fusion=fusion.value,
        n_backends=n_backends,
        n_adversarial=n_adversarial,
        corpus_size=corpus_size,
        n_queries=n_queries,
        attack_budget_step=attack_budget_step,
        seed=seed,
    )

    # Sweep K = 0, S, 2S, ..., M (always include the endpoints).
    k_values: list[int] = []
    k = 0
    while k <= corpus_size:
        k_values.append(k)
        k += max(1, attack_budget_step)
    if k_values[-1] != corpus_size:
        k_values.append(corpus_size)

    for k_attack in k_values:
        # Wire fresh stores per K so state is clean. Cheap — these are
        # in-memory stubs.
        stores: list[Any] = []
        for i in range(n_benign):
            stores.append(
                BenignStore(
                    backend_name=f"benign-{i}",
                    per_query_results=benign_per_query_per_store[i],
                )
            )
        for i in range(n_adversarial):
            stores.append(
                AdversarialStore(
                    backend_name=f"adversarial-{i}",
                    attack_budget=k_attack,
                    attacker_ids=attacker_ids,
                    benign_tail=rogue_benign_tail,
                    top_score=1.0,
                )
            )

        # Equal weights for `weighted` — operator hasn't down-weighted
        # the malicious backend yet (that's the v0.2 mitigation).
        router = MemoryRouter(
            stores,
            default_fusion=fusion,
            weights={s.BACKEND_NAME: 1.0 for s in stores},
        )

        recalls: list[float] = []
        leaks: list[float] = []
        displacements: list[float] = []
        for q in queries:
            if k_attack == 0:
                # On the first pass, the router top-5 with no attacker is
                # our baseline for "displacement" at later K. Compute it
                # by issuing the query and capturing the gold ids in top-5.
                req = RecallRequest(agent_id="adv", query=q.query, k=5, fusion=fusion)
                resp = await router.recall(req)
                gold_in_baseline = {
                    mid for mid in (h.id for h in resp.results) if mid in q.gold_ids
                }
                baseline_top5_per_query[q.query] = gold_in_baseline

            recall, leak, displacement = await _run_one_query(
                router,
                q,
                attacker_id_set,
                baseline_top5_per_query.get(q.query, set()),
                fusion=fusion,
            )
            recalls.append(recall)
            leaks.append(leak)
            displacements.append(displacement)

        result.k_attack.append(k_attack)
        result.recall_at_5.append(statistics.fmean(recalls))
        result.leak.append(statistics.fmean(leaks))
        result.displacement.append(statistics.fmean(displacements))

    # Operating-point: largest K where recall@5 >= 0.6.
    op_k: int | None = None
    op_r: float | None = None
    for k_attack, recall in zip(result.k_attack, result.recall_at_5, strict=True):
        if recall >= 0.6:
            op_k = k_attack
            op_r = recall
    result.operating_point_k = op_k
    result.operating_point_recall = op_r
    return result


# ---------------------------------------------------------------------------
# Reporting / plotting
# ---------------------------------------------------------------------------


def _format_text(result: AdversarialResult) -> str:
    """Pretty human-readable report."""
    lines: list[str] = []
    lines.append("AMP adversarial-fusion experiment")
    lines.append("=" * 72)
    lines.append(f"  fusion             : {result.fusion}")
    lines.append(f"  backends           : {result.n_backends} ({result.n_adversarial} adversarial)")
    lines.append(f"  corpus size        : {result.corpus_size}")
    lines.append(f"  queries / K        : {result.n_queries}")
    lines.append(f"  attack-budget step : {result.attack_budget_step}")
    lines.append(f"  seed               : {result.seed}")
    lines.append("")
    lines.append(f"{'K':>4}  {'recall@5':>10}  {'leak':>8}  {'displacement':>14}")
    lines.append("-" * 44)
    for k, r, l_, d in zip(
        result.k_attack, result.recall_at_5, result.leak, result.displacement, strict=True
    ):
        lines.append(f"{k:>4}  {r:>10.3f}  {l_:>8.3f}  {d:>14.3f}")
    lines.append("")
    if result.operating_point_k is not None:
        lines.append(
            f"Operating point: largest K with recall@5 >= 0.6 is K={result.operating_point_k} "
            f"(recall@5={result.operating_point_recall:.3f})."
        )
    else:
        lines.append(
            "Operating point: no K in the sweep produced recall@5 >= 0.6 (catastrophic failure)."
        )
    return "\n".join(lines)


def _format_json(result: AdversarialResult) -> str:
    return json.dumps(asdict(result), indent=2, sort_keys=True)


def _try_plot(result: AdversarialResult, plot_path: Path) -> str | None:
    """Render a 3-line PNG plot at ``plot_path``; return None on success.

    Returns a human-readable reason string when matplotlib isn't
    installed or the write fails. The caller continues either way so
    the script still produces JSON / text output on bare environments.
    """
    try:
        import matplotlib  # type: ignore[import-not-found]

        matplotlib.use("Agg")  # headless, no display required
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]
    except ImportError as exc:
        return f"matplotlib not installed ({exc}); skipped plot."

    try:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(result.k_attack, result.recall_at_5, marker="o", label="recall@5")
        ax.plot(result.k_attack, result.leak, marker="s", label="adversarial leak rate")
        ax.plot(result.k_attack, result.displacement, marker="^", label="gold displacement rate")
        ax.set_xlabel("attacker budget K (injected top-rank rows)")
        ax.set_ylabel("rate")
        ax.set_ylim(-0.02, 1.02)
        ax.set_title(
            f"AMP adversarial fusion ({result.fusion}, "
            f"{result.n_adversarial}/{result.n_backends} malicious)"
        )
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best")
        fig.tight_layout()
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_path, dpi=120)
        plt.close(fig)
        return None
    except Exception as exc:  # broad on purpose; we never want plotting to crash the run
        return f"plot write failed: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser; factored out so tests can introspect it."""
    p = argparse.ArgumentParser(
        prog="run_adversarial",
        description="Adversarial-fusion experiment for AMP's MemoryRouter (THREATS §3.3).",
    )
    p.add_argument("--n-backends", type=int, default=3, help="Total stores (default: 3).")
    p.add_argument(
        "--n-adversarial",
        type=int,
        default=1,
        help="Adversarial backends (default: 1; must be < --n-backends).",
    )
    p.add_argument("--corpus-size", type=int, default=50, help="Memory corpus size (default: 50).")
    p.add_argument("--queries", type=int, default=20, help="Queries per K value (default: 20).")
    p.add_argument(
        "--attack-budget-step",
        type=int,
        default=5,
        help="K sample step (default: 5). Sweeps K=0, S, 2S, ..., M.",
    )
    p.add_argument(
        "--target",
        choices=("rrf", "max", "weighted"),
        default="rrf",
        help="Fusion algorithm under test (default: rrf).",
    )
    p.add_argument("--seed", type=int, default=1337, help="RNG seed (default: 1337).")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    p.add_argument(
        "--plot",
        action="store_true",
        help="Write docs/adversarial-results.png (silently skipped if matplotlib missing).",
    )
    p.add_argument(
        "--out-json",
        type=str,
        default=None,
        help="Optional path to also write JSON output (in addition to stdout).",
    )
    return p


_TARGET_TO_FUSION: dict[str, FusionAlgorithm] = {
    "rrf": FusionAlgorithm.RRF,
    "max": FusionAlgorithm.MAX,
    "weighted": FusionAlgorithm.WEIGHTED,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)
    fusion = _TARGET_TO_FUSION[args.target]
    try:
        result = asyncio.run(
            _sweep_k(
                fusion=fusion,
                n_backends=args.n_backends,
                n_adversarial=args.n_adversarial,
                corpus_size=args.corpus_size,
                n_queries=args.queries,
                attack_budget_step=args.attack_budget_step,
                seed=args.seed,
            )
        )
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.plot:
        plot_path = _REPO_ROOT / "docs" / "adversarial-results.png"
        skipped = _try_plot(result, plot_path)
        if skipped:
            # Diagnostic on stderr so JSON stdout stays machine-readable.
            print(skipped, file=sys.stderr)

    json_blob = _format_json(result)
    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_blob, encoding="utf-8")

    if args.json:
        print(json_blob)
    else:
        print(_format_text(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by integration runs
    with contextlib.suppress(BrokenPipeError):
        raise SystemExit(main())
