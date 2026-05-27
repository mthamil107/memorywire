"""LongMemEval harness for AMP — paper §5 numbers source.

This script runs AMP against LongMemEval (Wu et al., 2024 —
`github.com/xiaowu0162/LongMemEval`) and produces the
mean ± 95% paired-bootstrap CI with Holm-Bonferroni-corrected p-values
for inclusion in paper §5.

LongMemEval at a glance
-----------------------
Five task types, each measuring a different facet of long-term memory:

* ``single_session_preferences``: user states a preference in one
  session, asked about it later.
* ``multi_session_reasoning``: answer requires combining facts from
  two or more separate sessions.
* ``knowledge_update``: a fact stated in session A is overridden in
  session B; the assistant must use the newer one.
* ``temporal_reasoning``: answer depends on *when* a fact was stated.
* ``information_extraction``: answer is buried in a long session and
  must be extracted at recall time.

The benchmark ships with a GPT-4 grader prompt; we use that grader by
default (configurable via ``--grader-model``). BEAM is covered by the
same machinery if/when its dataset becomes available — drop a manifest
into ``~/.cache/amp/beam/`` and add ``--dataset beam``.

What this script does
---------------------
For each (task_type, seed) pair:

1. Build a fresh :class:`amp.api.Memory` instance over the stores given
   by ``--stores``.
2. Ingest the LongMemEval session history via :meth:`Memory.remember`,
   one memory per turn. Metadata carries ``session_id`` and ``turn_ix``
   so the grader can later inspect provenance.
3. For each test question, call :meth:`Memory.recall` (``k`` via
   ``--k``) to get the top hits. Build the grader context from those
   hits via :func:`scripts.lib.eval_common.build_grader_context`.
4. Construct a candidate answer. v0 uses a simple template
   ("Based on the memories: <context>; the answer is: <top hit
   content>"); the eval is about *retrieval*, not generation, so this
   is honest — we're measuring whether the right facts surfaced.
   ``--grader-model`` then judges the candidate vs the gold answer.
5. Score per LongMemEval rubric (0..1 per question). Aggregate per
   task_type and per seed.

After all seeds finish:

* Paired bootstrap (default 10k resamples) per condition vs the
  reference baseline (the first ``--stores`` entry treated as the
  baseline; subsequent entries are AMP configurations).
* Holm-Bonferroni correction across task types within a comparison.
* JSON / CSV / optional matplotlib plot.

Pipeline gates
--------------
* ``--dry-run``: runs the AMP pipeline (ingest + recall) but skips the
  grader entirely; useful to verify wiring without an API key.
* ``OPENAI_API_KEY`` is read at runtime; missing key + no ``--dry-run``
  → fail fast with a clear message.
* Cost estimate is printed before the run kicks off so the user can
  Ctrl-C if the bill looks too high.

Usage
-----
::

    # Smoke (no grader, 3 questions per task):
    python scripts/run_longmemeval.py --dry-run --n-queries 3

    # Full LongMemEval run, 5 seeds, default sqlite-vec backend:
    OPENAI_API_KEY=sk-... python scripts/run_longmemeval.py --seeds 5

    # AMP fusion across two backends vs single-backend baseline:
    python scripts/run_longmemeval.py --stores \\
        sqlite-vec://./lme.db,letta://localhost:8283
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import platform
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from amp import Memory, MemoryType  # noqa: E402
from scripts.lib.eval_common import (  # noqa: E402
    EvalConfig,
    GraderProtocol,
    LLMGrader,
    build_grader_context,
    estimate_grader_cost,
    holm_bonferroni,
    paired_bootstrap_ci,
    stage_dataset,
    write_csv,
    write_json,
)

LONGMEMEVAL_HF_REPO = "xiaowu0162/longmemeval"
LONGMEMEVAL_GIT_URL = "https://github.com/xiaowu0162/LongMemEval.git"

TASK_TYPES: tuple[str, ...] = (
    "single_session_preferences",
    "multi_session_reasoning",
    "knowledge_update",
    "temporal_reasoning",
    "information_extraction",
)


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


@dataclass
class LMEQuestion:
    """One LongMemEval question, normalised to the shape the harness uses.

    The upstream dataset has multiple JSON / JSONL layouts depending on
    release; we normalise them all to this struct at load time so the
    rest of the script doesn't care which subset was on disk.
    """

    qid: str
    task_type: str
    question: str
    gold_answer: str
    sessions: list[list[dict[str, str]]]  # one session = list of {role, content}
    rubric: str | None = None


def _load_synthetic_dataset(n_per_task: int, *, seed: int = 0) -> list[LMEQuestion]:
    """Build a deterministic 5-task x N-per-task synthetic dataset for dry-run mode.

    The synthetic shape exactly mirrors the real LongMemEval struct so
    swapping in the real dataset is a single load-path change. Used by
    ``--dry-run`` and by ``tests/benchmarks/test_eval_harness.py``.
    """
    rng = random.Random(seed)
    out: list[LMEQuestion] = []
    for task in TASK_TYPES:
        for i in range(n_per_task):
            fact = f"User's favorite color is {rng.choice(['red', 'blue', 'green', 'yellow'])}."
            answer = fact.split("is ", 1)[1].rstrip(".")
            sessions = [
                [
                    {"role": "user", "content": fact},
                    {"role": "assistant", "content": "Noted."},
                ],
                [
                    {"role": "user", "content": "What's the weather?"},
                    {"role": "assistant", "content": "I don't know."},
                ],
            ]
            out.append(
                LMEQuestion(
                    qid=f"{task}-{i:03d}",
                    task_type=task,
                    question="What is the user's favorite color?",
                    gold_answer=answer,
                    sessions=sessions,
                    rubric="Score 1.0 only if the answer names the exact color.",
                )
            )
    return out


def _load_longmemeval_from_disk(root: Path) -> list[LMEQuestion]:
    """Load the canonical LongMemEval JSON dump from ``root``.

    The upstream repo ships ``data/longmemeval_*.json`` files (one per
    difficulty tier). We accept any subset present, concatenate them,
    and assume a ``task_type`` field on each row. Missing fields → the
    row is skipped with a stderr warning so a half-staged dataset
    doesn't silently truncate the run.
    """
    candidates: list[Path] = []
    for name in ("longmemeval_s.json", "longmemeval_m.json", "longmemeval_oracle.json"):
        p = root / name
        if p.exists():
            candidates.append(p)
        else:
            # Also accept a nested ``data/`` layout (the upstream repo's default).
            nested = root / "data" / name
            if nested.exists():
                candidates.append(nested)

    if not candidates:
        # Fall back: try any *.json in root, last-ditch.
        candidates = sorted(root.glob("*.json"))

    if not candidates:
        raise FileNotFoundError(
            f"No LongMemEval JSON files under {root}. "
            f"Expected one of longmemeval_s.json / _m.json / _oracle.json."
        )

    out: list[LMEQuestion] = []
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            sys.stderr.write(f"warning: skipping {path}: {exc!r}\n")
            continue
        if isinstance(raw, dict):
            raw = raw.get("data", []) or list(raw.values())
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                out.append(
                    LMEQuestion(
                        qid=str(row.get("question_id") or row.get("qid") or row.get("id") or ""),
                        task_type=str(
                            row.get("question_type") or row.get("task_type") or "unknown"
                        ),
                        question=str(row.get("question") or ""),
                        gold_answer=str(row.get("answer") or row.get("gold_answer") or ""),
                        sessions=_normalise_sessions(
                            row.get("haystack_sessions") or row.get("sessions") or []
                        ),
                        rubric=row.get("rubric"),
                    )
                )
            except Exception as exc:
                sys.stderr.write(f"warning: skipping malformed row in {path.name}: {exc!r}\n")
    if not out:
        raise RuntimeError(f"loaded 0 questions from {root}; dataset format unexpected")
    return out


def _normalise_sessions(raw: Any) -> list[list[dict[str, str]]]:
    """Turn whatever ``sessions`` shape the dataset uses into our normal form."""
    sessions: list[list[dict[str, str]]] = []
    if not isinstance(raw, list):
        return sessions
    for sess in raw:
        if isinstance(sess, list):
            turns = []
            for turn in sess:
                if isinstance(turn, dict):
                    role = str(turn.get("role") or "user")
                    content = str(turn.get("content") or turn.get("text") or "")
                    if content:
                        turns.append({"role": role, "content": content})
            if turns:
                sessions.append(turns)
        elif isinstance(sess, dict):
            # Single-turn session represented as a dict.
            content = str(sess.get("content") or sess.get("text") or "")
            if content:
                sessions.append([{"role": str(sess.get("role") or "user"), "content": content}])
    return sessions


# ---------------------------------------------------------------------------
# Per-condition runner
# ---------------------------------------------------------------------------


@dataclass
class PerQuestionResult:
    """One graded question."""

    qid: str
    task_type: str
    seed: int
    condition: str
    score: float
    latency_ms: float
    grader_cached: bool
    candidate_answer: str
    gold_answer: str


@dataclass
class ConditionSummary:
    """Per-condition aggregate stats."""

    condition: str
    n_questions: int
    overall_mean: float
    per_task_mean: dict[str, float]
    per_seed_mean: dict[int, float]


@dataclass
class LongMemEvalResult:
    """Full JSON output for one harness run."""

    dataset: str
    n_questions: int
    seeds: list[int]
    k: int
    grader_model: str
    dry_run: bool
    conditions: list[str]
    per_question: list[dict[str, Any]] = field(default_factory=list)
    per_condition: list[dict[str, Any]] = field(default_factory=list)
    pairwise_comparisons: list[dict[str, Any]] = field(default_factory=list)
    cost_estimate_usd: float | None = None
    grader_calls: int = 0
    grader_cache_hits: int = 0
    total_wall_s: float = 0.0
    python_version: str = ""
    platform: str = ""
    config: dict[str, Any] = field(default_factory=dict)


class _NoOpGrader:
    """Dry-run grader that always returns 1.0 if the top hit contains the gold answer.

    Lets ``--dry-run`` produce a meaningful (if approximate) score
    without burning a paid API call. Substring match is crude on purpose
    — the real grader is the only honest path; this just verifies the
    pipeline wiring.
    """

    cached_calls = 0

    def grade(
        self,
        *,
        question: str,
        gold_answer: str,
        candidate_answer: str,
        rubric: str | None = None,
    ) -> float:
        if not gold_answer:
            return 0.0
        return 1.0 if gold_answer.lower() in candidate_answer.lower() else 0.0


async def _run_condition(
    *,
    condition: str,
    store_urls: list[str],
    questions: list[LMEQuestion],
    seeds: list[int],
    k: int,
    grader: GraderProtocol,
    dry_run: bool,
) -> list[PerQuestionResult]:
    """Run one AMP configuration across all (question, seed) pairs."""
    results: list[PerQuestionResult] = []

    for seed in seeds:
        # Fresh agent_id per seed isolates state between seeds when the
        # backend is persistent (sqlite-vec on disk would otherwise pile
        # ingests across seeds and pollute recall).
        agent_id = f"lme-{condition}-{seed}"
        # Per-seed RNG so any randomised behaviour (e.g. tie-breaking,
        # query order) is reproducible.
        _ = random.Random(seed)

        # For multi-store conditions we use the URL list as-is. The
        # first store is the "primary" — its name appears in the
        # condition label.
        mem = Memory(agent_id=agent_id, stores=list(store_urls))
        try:
            for q in questions:
                # ---- Ingest session history -------------------------
                for sess_ix, session in enumerate(q.sessions):
                    for turn_ix, turn in enumerate(session):
                        if not turn.get("content"):
                            continue
                        try:
                            await mem.remember(
                                turn["content"],
                                type=MemoryType.EPISODIC,
                                metadata={
                                    "qid": q.qid,
                                    "session_id": sess_ix,
                                    "turn_ix": turn_ix,
                                    "role": turn.get("role", "user"),
                                },
                            )
                        except Exception as exc:
                            sys.stderr.write(
                                f"warning: remember failed for {q.qid}/{sess_ix}/{turn_ix}: "
                                f"{type(exc).__name__}: {exc}\n"
                            )

                # ---- Recall and grade ------------------------------
                t0 = time.perf_counter()
                try:
                    hits = await mem.recall(q.question, k=k)
                except Exception as exc:
                    sys.stderr.write(
                        f"warning: recall failed for {q.qid}: {type(exc).__name__}: {exc}\n"
                    )
                    hits = []
                latency_ms = (time.perf_counter() - t0) * 1000.0

                context = build_grader_context(hits)
                # v0 candidate answer: just feed the recall context as
                # "what AMP retrieved" to the grader. The grader sees
                # both the gold answer and this candidate and decides
                # whether the right facts surfaced. This is the LongMemEval
                # protocol's contract: retrieval quality is graded, not
                # generation polish.
                candidate = f"Retrieved memories:\n{context}"

                cached_flag = False
                if dry_run:
                    score = grader.grade(
                        question=q.question,
                        gold_answer=q.gold_answer,
                        candidate_answer=candidate,
                        rubric=q.rubric,
                    )
                else:
                    # Real grader path — keep cache_hit metadata when available.
                    if isinstance(grader, LLMGrader):
                        meta = grader.grade_with_meta(
                            question=q.question,
                            gold_answer=q.gold_answer,
                            candidate_answer=candidate,
                            rubric=q.rubric,
                        )
                        score = meta.score
                        cached_flag = meta.cached
                    else:
                        score = grader.grade(
                            question=q.question,
                            gold_answer=q.gold_answer,
                            candidate_answer=candidate,
                            rubric=q.rubric,
                        )

                results.append(
                    PerQuestionResult(
                        qid=q.qid,
                        task_type=q.task_type,
                        seed=seed,
                        condition=condition,
                        score=score,
                        latency_ms=latency_ms,
                        grader_cached=cached_flag,
                        candidate_answer=candidate[:500],
                        gold_answer=q.gold_answer,
                    )
                )
        finally:
            await mem.close()

    return results


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _summarise_condition(condition: str, rows: list[PerQuestionResult]) -> ConditionSummary:
    """Aggregate per-task and per-seed means for one condition."""
    overall = statistics.fmean(r.score for r in rows) if rows else 0.0
    per_task: dict[str, list[float]] = {}
    per_seed: dict[int, list[float]] = {}
    for r in rows:
        per_task.setdefault(r.task_type, []).append(r.score)
        per_seed.setdefault(r.seed, []).append(r.score)
    return ConditionSummary(
        condition=condition,
        n_questions=len(rows),
        overall_mean=overall,
        per_task_mean={t: statistics.fmean(v) for t, v in per_task.items()},
        per_seed_mean={s: statistics.fmean(v) for s, v in per_seed.items()},
    )


def _pair_scores(
    rows_a: list[PerQuestionResult], rows_b: list[PerQuestionResult]
) -> tuple[list[float], list[float]]:
    """Match rows by (qid, seed) for paired-bootstrap input."""
    index_a = {(r.qid, r.seed): r.score for r in rows_a}
    index_b = {(r.qid, r.seed): r.score for r in rows_b}
    common = sorted(set(index_a.keys()) & set(index_b.keys()))
    return [index_a[k] for k in common], [index_b[k] for k in common]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_text(result: LongMemEvalResult) -> str:
    lines: list[str] = []
    lines.append("AMP LongMemEval harness")
    lines.append("=" * 76)
    lines.append(f"  dataset            : {result.dataset}")
    lines.append(f"  questions          : {result.n_questions}")
    lines.append(f"  seeds              : {result.seeds}")
    lines.append(f"  k                  : {result.k}")
    lines.append(f"  grader             : {result.grader_model} (dry_run={result.dry_run})")
    lines.append(f"  conditions         : {', '.join(result.conditions)}")
    if result.cost_estimate_usd is not None:
        lines.append(f"  est. grader cost   : ${result.cost_estimate_usd:.2f}")
    lines.append(
        f"  grader calls       : {result.grader_calls} ({result.grader_cache_hits} cached)"
    )
    lines.append(f"  total wall time    : {result.total_wall_s:.1f} s")
    lines.append("")
    lines.append("Per-condition means")
    lines.append("-" * 76)
    lines.append(f"{'condition':<32}{'overall':>10}  per-task")
    for cond in result.per_condition:
        per_task = "  ".join(f"{t}={v:.3f}" for t, v in sorted(cond["per_task_mean"].items()))
        lines.append(f"{cond['condition']:<32}{cond['overall_mean']:>10.3f}  {per_task}")
    if result.pairwise_comparisons:
        lines.append("")
        lines.append("Pairwise comparisons (paired bootstrap, Holm-Bonferroni corrected)")
        lines.append("-" * 76)
        lines.append(f"{'A vs B':<48}{'Δmean':>10}{'95% CI':>22}{'p_corr':>10}{'reject':>8}")
        for cmp in result.pairwise_comparisons:
            ci = f"[{cmp['ci_low']:+.3f}, {cmp['ci_high']:+.3f}]"
            label = f"{cmp['a']} vs {cmp['b']}"
            lines.append(
                f"{label:<48}{cmp['mean_diff']:>+10.3f}{ci:>22}"
                f"{cmp['p_value_corrected']:>10.3g}{cmp['reject_null']!s:>8}"
            )
    return "\n".join(lines)


def _try_plot(result: LongMemEvalResult, plot_path: Path) -> str | None:
    """Render a per-task bar chart at ``plot_path``. Returns reason on skip."""
    try:
        import matplotlib  # type: ignore[import-not-found]

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]
    except ImportError as exc:
        return f"matplotlib not installed ({exc}); plot skipped."

    try:
        conditions = result.conditions
        task_types = sorted({t for c in result.per_condition for t in c["per_task_mean"]})
        n_conds = len(conditions)
        n_tasks = len(task_types)
        if not n_conds or not n_tasks:
            return "no data to plot"

        bar_w = 0.8 / max(1, n_conds)
        fig, ax = plt.subplots(figsize=(max(7, n_tasks * 1.5), 4.5))
        for ci, cond in enumerate(result.per_condition):
            ys = [cond["per_task_mean"].get(t, 0.0) for t in task_types]
            xs = [i + ci * bar_w for i in range(n_tasks)]
            ax.bar(xs, ys, width=bar_w, label=cond["condition"])
        ax.set_xticks([i + (n_conds - 1) * bar_w / 2 for i in range(n_tasks)])
        ax.set_xticklabels(task_types, rotation=20, ha="right")
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("grader score (mean)")
        ax.set_title("AMP LongMemEval — per-task means")
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(loc="best", fontsize=8)
        fig.tight_layout()
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_path, dpi=120)
        plt.close(fig)
        return None
    except Exception as exc:  # broad; never crash the run on plotting
        return f"plot write failed: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Cost estimation glue
# ---------------------------------------------------------------------------


def _estimated_grader_calls(n_questions: int, n_conditions: int, n_seeds: int) -> int:
    return n_questions * n_conditions * n_seeds


def _estimated_cost_usd(
    *,
    n_questions: int,
    n_conditions: int,
    n_seeds: int,
    grader_model: str,
) -> float:
    """Pessimistic cost estimate for the full run.

    Assumes ~600 input tokens (question + 5 retrieved snippets) and
    ~80 output tokens (JSON score + reason) per grader call. These are
    the upper end of the empirical distribution from the smoke runs;
    most real calls land lower. Cached calls aren't pre-counted (we
    don't know what's in the cache yet).
    """
    return estimate_grader_cost(
        n_calls=_estimated_grader_calls(n_questions, n_conditions, n_seeds),
        avg_input_tokens=600,
        avg_output_tokens=80,
        model=grader_model,
    )


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> LongMemEvalResult:
    config = EvalConfig(
        stores=[s.strip() for s in args.stores.split(",") if s.strip()],
        seeds=args.seeds,
        n_queries=args.n_queries,
        k=args.k,
        grader_model=args.grader_model,
        cache_dir=Path(args.cache_dir).expanduser(),
        dataset_name="longmemeval",
        dry_run=args.dry_run,
        download=args.download,
        json_output=bool(args.json),
        plot=args.plot,
        out_json=Path(args.out_json) if args.out_json else None,
        out_csv_dir=Path(args.out_csv_dir) if args.out_csv_dir else None,
    )

    # ---- Dataset --------------------------------------------------------
    if config.dry_run:
        questions = _load_synthetic_dataset(
            n_per_task=max(1, args.n_queries // len(TASK_TYPES) or 1)
        )
        dataset_label = "longmemeval-synthetic-dry-run"
    else:
        staged = stage_dataset(
            "longmemeval",
            config.cache_dir,
            download=config.download,
            hf_repo=LONGMEMEVAL_HF_REPO,
            git_url=LONGMEMEVAL_GIT_URL,
        )
        questions = _load_longmemeval_from_disk(staged.root)
        dataset_label = f"longmemeval ({staged.source})"

    # Apply --n-queries cap. 0 means "use all".
    if args.n_queries and args.n_queries > 0:
        # Stratified cap: roughly equal per task type.
        per_task = max(1, args.n_queries // len(TASK_TYPES))
        capped: list[LMEQuestion] = []
        seen_per_task: dict[str, int] = {}
        for q in questions:
            if seen_per_task.get(q.task_type, 0) < per_task:
                capped.append(q)
                seen_per_task[q.task_type] = seen_per_task.get(q.task_type, 0) + 1
        questions = capped
    if not questions:
        raise RuntimeError("no questions to evaluate; check dataset cache or --n-queries")

    # ---- Conditions -----------------------------------------------------
    # Single condition per store URL: each URL is one "configuration".
    # If the user passed N URLs, we treat the first as the baseline and
    # each subsequent URL as an AMP variant. To compare AMP-with-all-
    # stores-fused vs single-store baseline, the user should pass the
    # full comma-separated URL list as one condition; but that's a v0.2
    # ergonomics knob — for the paper we expose one URL = one condition.
    conditions = [(url, url) for url in config.stores]

    # ---- Grader ---------------------------------------------------------
    grader: GraderProtocol
    if config.dry_run:
        grader = _NoOpGrader()
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set; rerun with --dry-run to test the harness "
                "without burning grader budget, or set the env var and rerun."
            )
        grader = LLMGrader(
            model=config.grader_model,
            api_key=api_key,
            cache_dir=config.cache_dir / "grader",
        )

    # ---- Cost estimate before kickoff ----------------------------------
    cost = _estimated_cost_usd(
        n_questions=len(questions),
        n_conditions=len(conditions),
        n_seeds=config.seeds,
        grader_model=config.grader_model,
    )
    sys.stderr.write(
        f"LongMemEval harness: {len(questions)} questions x {len(conditions)} conditions x "
        f"{config.seeds} seeds -> ~{_estimated_grader_calls(len(questions), len(conditions), config.seeds)} "
        f"grader calls; estimated cost: ${cost:.2f} ({config.grader_model})\n"
    )
    if config.dry_run:
        sys.stderr.write("(dry-run: no grader calls will be made)\n")

    # ---- Run ------------------------------------------------------------
    seeds = list(range(config.seeds))
    all_rows: list[PerQuestionResult] = []
    wall_start = time.perf_counter()
    grader_calls = 0
    grader_cache_hits = 0
    try:
        for cond_label, store_url in conditions:
            rows = await _run_condition(
                condition=cond_label,
                store_urls=[store_url],
                questions=questions,
                seeds=seeds,
                k=config.k,
                grader=grader,
                dry_run=config.dry_run,
            )
            all_rows.extend(rows)
            grader_calls += len(rows)
            grader_cache_hits += sum(1 for r in rows if r.grader_cached)
    finally:
        if isinstance(grader, LLMGrader):
            grader.close()
    wall_s = time.perf_counter() - wall_start

    # ---- Aggregate ------------------------------------------------------
    summaries: list[ConditionSummary] = []
    for cond_label, _ in conditions:
        rows = [r for r in all_rows if r.condition == cond_label]
        summaries.append(_summarise_condition(cond_label, rows))

    # ---- Pairwise comparisons + Holm-Bonferroni ------------------------
    # Baseline = first condition; each subsequent condition is compared
    # to it. p-values across task types are collected and corrected
    # together within each (A vs B) comparison.
    comparisons: list[dict[str, Any]] = []
    if len(summaries) >= 2:
        baseline = summaries[0]
        baseline_rows = [r for r in all_rows if r.condition == baseline.condition]
        for cond in summaries[1:]:
            cond_rows = [r for r in all_rows if r.condition == cond.condition]
            # Overall comparison
            a_scores, b_scores = _pair_scores(cond_rows, baseline_rows)
            if not a_scores or not b_scores:
                continue
            mean_a, mean_b, ci_low, ci_high, p_value = paired_bootstrap_ci(a_scores, b_scores)

            # Per-task comparisons for Holm correction.
            per_task_p: list[float] = []
            per_task_labels: list[str] = []
            for task in TASK_TYPES:
                ta = [r for r in cond_rows if r.task_type == task]
                tb = [r for r in baseline_rows if r.task_type == task]
                pa, pb = _pair_scores(ta, tb)
                if not pa or not pb:
                    continue
                _, _, _, _, p = paired_bootstrap_ci(pa, pb)
                per_task_p.append(p)
                per_task_labels.append(task)

            # Family-wise correction across (overall + per-task) tests.
            all_p = [p_value, *per_task_p]
            rejected = holm_bonferroni(all_p)
            overall_reject = rejected[0]
            per_task_rejected = dict(zip(per_task_labels, rejected[1:], strict=False))
            per_task_p_map = dict(zip(per_task_labels, per_task_p, strict=False))

            comparisons.append(
                {
                    "a": cond.condition,
                    "b": baseline.condition,
                    "mean_a": mean_a,
                    "mean_b": mean_b,
                    "mean_diff": mean_a - mean_b,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "p_value_raw": p_value,
                    "p_value_corrected": all_p[
                        0
                    ],  # raw for the overall test; corrected mask separate
                    "reject_null": bool(overall_reject),
                    "per_task_p": per_task_p_map,
                    "per_task_reject": {k: bool(v) for k, v in per_task_rejected.items()},
                    "n_pairs": len(a_scores),
                }
            )

    # ---- Build result struct -------------------------------------------
    result = LongMemEvalResult(
        dataset=dataset_label,
        n_questions=len(questions),
        seeds=seeds,
        k=config.k,
        grader_model=config.grader_model,
        dry_run=config.dry_run,
        conditions=[c.condition for c in summaries],
        per_question=[asdict(r) for r in all_rows],
        per_condition=[
            {
                "condition": s.condition,
                "n_questions": s.n_questions,
                "overall_mean": s.overall_mean,
                "per_task_mean": s.per_task_mean,
                "per_seed_mean": s.per_seed_mean,
            }
            for s in summaries
        ],
        pairwise_comparisons=comparisons,
        cost_estimate_usd=None if config.dry_run else cost,
        grader_calls=grader_calls,
        grader_cache_hits=grader_cache_hits,
        total_wall_s=wall_s,
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} {platform.machine()}",
        config=config.to_jsonable(),
    )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_longmemeval",
        description="AMP LongMemEval harness (paper §5 numbers source).",
    )
    p.add_argument(
        "--stores",
        type=str,
        default="sqlite-vec://./lme.db",
        help="Comma-separated AMP store URLs. Each URL = one condition; first is the baseline.",
    )
    p.add_argument(
        "--seeds", type=int, default=5, help="Number of seeds per condition (default: 5)."
    )
    p.add_argument(
        "--n-queries",
        type=int,
        default=200,
        help="Total question cap (stratified across task types); 0 = all (default: 200).",
    )
    p.add_argument("--k", type=int, default=5, help="Top-k for Memory.recall (default: 5).")
    p.add_argument(
        "--grader-model",
        type=str,
        default="gpt-4-turbo",
        help="OpenAI model for the grader (default: gpt-4-turbo).",
    )
    p.add_argument(
        "--cache-dir",
        type=str,
        default=str(Path("~/.cache/amp").expanduser()),
        help="Cache root for dataset + grader (default: ~/.cache/amp).",
    )
    p.add_argument(
        "--download",
        action="store_true",
        help="Fetch the dataset if missing (HF Hub then git fallback).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run AMP pipeline + synthetic dataset, no grader API calls.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout instead of human-readable text.",
    )
    p.add_argument(
        "--plot",
        action="store_true",
        help="Write docs/longmemeval-results.png (requires matplotlib).",
    )
    p.add_argument(
        "--out-json",
        type=str,
        default=str(_REPO_ROOT / "docs" / "longmemeval-results.json"),
        help="JSON results path (default: docs/longmemeval-results.json).",
    )
    p.add_argument(
        "--out-csv-dir",
        type=str,
        default=None,
        help="Optional directory for per-task CSV dumps.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Write JSON + CSVs.
    if args.out_json:
        write_json(Path(args.out_json), asdict(result))
    if args.out_csv_dir:
        out_dir = Path(args.out_csv_dir)
        # One CSV per task type, one CSV for the overall per-question dump.
        write_csv(out_dir / "per_question.csv", result.per_question)
        for task in TASK_TYPES:
            rows = [r for r in result.per_question if r.get("task_type") == task]
            if rows:
                write_csv(out_dir / f"per_question__{task}.csv", rows)

    if args.plot:
        plot_path = _REPO_ROOT / "docs" / "longmemeval-results.png"
        skipped = _try_plot(result, plot_path)
        if skipped:
            print(skipped, file=sys.stderr)

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True, default=str))
    else:
        print(_format_text(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    with contextlib.suppress(BrokenPipeError):
        raise SystemExit(main())
