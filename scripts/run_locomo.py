"""LoCoMo harness for memorywire â€” paper Â§5 long-conversation numbers.

This script runs memorywire against LoCoMo (Maharana et al., 2024 â€”
`github.com/snap-research/locomo`). LoCoMo measures long-term
conversational memory: pairs of conversational episodes spanning many
sessions, with a GPT-4 grader judging answer quality and a BLEU
overlap score for reference.

Per-question isolation invariant
--------------------------------
For each (seed, episode_id, qid) tuple we construct a *fresh*
:class:`memorywire.api.Memory` with a unique ``agent_id`` of the form
``f"locomo-{condition}-{seed}-{episode_id}-{qid}"``. Question N's
recall therefore never sees question N-1's ingested turns. The episode
session history is re-ingested per question into the fresh
agent-scoped slice; this is correctness-critical (an episode's QA
rows share the same session history but each question must see only
that history, not the answers leaked through previous questions'
ingest paths) and trades a small ingest cost for honest numbers.

Shape vs LongMemEval
--------------------
* LongMemEval is question-answer over a static history; LoCoMo is
  multi-session conversational with explicit episode pairs.
* LoCoMo uses BLEU *and* a grader; we report both. BLEU is cheap and
  reference-anchored; the grader adds semantic credit but costs money.
* Both share the same statistics rig: 5 seeds, 10k-resample paired
  bootstrap, Holm-Bonferroni correction across comparisons.

BEAM
----
BEAM (Lin et al., 2024) lands here too once its dataset is public â€”
the loader + grader plumbing is dataset-agnostic. Drop the manifest
into ``~/.cache/amp/beam/`` and reuse this harness with
``--dataset beam``.

CLI surface mirrors ``run_longmemeval.py``; flags should feel identical
across the two so a reader of the paper can map flag-for-flag between
the two reproductions.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from memorywire import Memory, MemoryType  # noqa: E402
from scripts.lib.eval_common import (  # noqa: E402
    EvalConfig,
    GraderProtocol,
    LLMGrader,
    build_grader_context,
    cleanup_question_dbs,
    estimate_grader_cost,
    holm_bonferroni,
    paired_bootstrap_ci,
    per_question_store_urls,
    stage_dataset,
    write_csv,
    write_json,
)

LOCOMO_HF_REPO = "snap-research/locomo"
LOCOMO_GIT_URL = "https://github.com/snap-research/locomo.git"


# ---------------------------------------------------------------------------
# Dataset normalisation
# ---------------------------------------------------------------------------


@dataclass
class LoCoMoEpisode:
    """One LoCoMo episode-pair, normalised."""

    episode_id: str
    sessions: list[list[dict[str, str]]]  # ordered conversational sessions
    questions: list[dict[str, Any]]  # each: {qid, question, gold_answer, ...}


def _load_synthetic_locomo(n_episodes: int, *, seed: int = 0) -> list[LoCoMoEpisode]:
    """Deterministic LoCoMo-shaped dataset for ``--dry-run``."""
    rng = random.Random(seed)
    out: list[LoCoMoEpisode] = []
    for i in range(n_episodes):
        topic = rng.choice(["sailing", "baking", "gardening", "cycling"])
        sessions = [
            [
                {"role": "user", "content": f"I really enjoy {topic} on weekends."},
                {"role": "assistant", "content": "That sounds great!"},
            ],
            [
                {"role": "user", "content": "What did I tell you I enjoy?"},
                {"role": "assistant", "content": "(to be answered)"},
            ],
        ]
        questions = [
            {
                "qid": f"ep{i:03d}-q0",
                "question": "What hobby does the user enjoy on weekends?",
                "gold_answer": topic,
                "category": "single-hop",
            }
        ]
        out.append(LoCoMoEpisode(episode_id=f"ep{i:03d}", sessions=sessions, questions=questions))
    return out


def _load_locomo_from_disk(root: Path) -> list[LoCoMoEpisode]:
    """Load the LoCoMo JSON dump from ``root``.

    The upstream repo distributes ``locomo10.json`` (~10 conversational
    episodes); we accept that and any sibling JSON files. Each episode
    is expected to have ``conversation`` (sessions) and ``qa`` (a list
    of question/answer pairs) fields.
    """
    candidates: list[Path] = []
    for name in ("locomo10.json", "locomo.json", "data.json"):
        for path in (root / name, root / "data" / name):
            if path.exists():
                candidates.append(path)
    if not candidates:
        candidates = sorted(root.glob("*.json"))

    if not candidates:
        raise FileNotFoundError(
            f"No LoCoMo JSON files under {root}. Expected locomo10.json or similar."
        )

    out: list[LoCoMoEpisode] = []
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            sys.stderr.write(f"warning: skipping {path}: {exc!r}\n")
            continue
        episodes = raw if isinstance(raw, list) else raw.get("episodes") or raw.get("data") or []
        for ep_ix, ep in enumerate(episodes):
            if not isinstance(ep, dict):
                continue
            try:
                ep_id = str(ep.get("sample_id") or ep.get("id") or f"ep{ep_ix:03d}")
                sessions = _normalise_locomo_sessions(
                    ep.get("conversation") or ep.get("sessions") or []
                )
                qa_rows = ep.get("qa") or ep.get("questions") or []
                questions: list[dict[str, Any]] = []
                for q_ix, q in enumerate(qa_rows):
                    if not isinstance(q, dict):
                        continue
                    questions.append(
                        {
                            "qid": str(q.get("qid") or q.get("id") or f"{ep_id}-q{q_ix}"),
                            "question": str(q.get("question") or ""),
                            "gold_answer": str(q.get("answer") or q.get("gold_answer") or ""),
                            "category": str(q.get("category") or q.get("type") or "general"),
                        }
                    )
                if sessions and questions:
                    out.append(
                        LoCoMoEpisode(episode_id=ep_id, sessions=sessions, questions=questions)
                    )
            except Exception as exc:
                sys.stderr.write(f"warning: skipping malformed episode in {path.name}: {exc!r}\n")
    if not out:
        raise RuntimeError(f"loaded 0 episodes from {root}")
    return out


def _normalise_locomo_sessions(raw: Any) -> list[list[dict[str, str]]]:
    """LoCoMo stores sessions as either a list-of-lists or a dict keyed by
    ``session_N``. Accept both.
    """
    sessions: list[list[dict[str, str]]] = []
    if isinstance(raw, dict):
        # Sort by session number embedded in the key (session_1, session_2, ...)
        def _key(k: str) -> int:
            try:
                return int(k.rsplit("_", 1)[-1])
            except (ValueError, IndexError):
                return 0

        items = sorted(raw.items(), key=lambda kv: _key(kv[0]))
        for _, sess in items:
            if isinstance(sess, list):
                sessions.append(_turns_from_list(sess))
    elif isinstance(raw, list):
        for sess in raw:
            if isinstance(sess, list):
                sessions.append(_turns_from_list(sess))
            elif isinstance(sess, dict) and "dia" in sess:
                # Some LoCoMo dumps wrap session turns in {"dia": [...]}.
                sessions.append(_turns_from_list(sess["dia"]))
    return sessions


def _turns_from_list(turns: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for t in turns:
        if not isinstance(t, dict):
            continue
        role = str(t.get("role") or t.get("speaker") or "user")
        content = str(t.get("content") or t.get("text") or t.get("utterance") or "")
        if content:
            out.append({"role": role, "content": content})
    return out


# ---------------------------------------------------------------------------
# BLEU (sentence-level BLEU-4 with smoothing; no nltk dependency)
# ---------------------------------------------------------------------------


def _ngrams(tokens: list[str], n: int) -> dict[tuple[str, ...], int]:
    counts: dict[tuple[str, ...], int] = {}
    for i in range(len(tokens) - n + 1):
        ngram = tuple(tokens[i : i + n])
        counts[ngram] = counts.get(ngram, 0) + 1
    return counts


def _bleu4(candidate: str, reference: str) -> float:
    """Sentence-level BLEU-4 with add-one (Lin-Chin) smoothing.

    Returns a float in [0, 1]. Used as a cheap reference-anchored
    metric on LoCoMo â€” the grader is the headline number; BLEU is the
    "is the candidate even close to the reference text?" sanity check.
    """
    cand_tokens = candidate.lower().split()
    ref_tokens = reference.lower().split()
    if not cand_tokens or not ref_tokens:
        return 0.0

    weights = [0.25, 0.25, 0.25, 0.25]
    log_precisions: list[float] = []
    for n, _w in enumerate(weights, start=1):
        cand_counts = _ngrams(cand_tokens, n)
        ref_counts = _ngrams(ref_tokens, n)
        if not cand_counts:
            log_precisions.append(math.log(1e-9))
            continue
        clipped = 0
        for ngram, ccount in cand_counts.items():
            clipped += min(ccount, ref_counts.get(ngram, 0))
        total = sum(cand_counts.values())
        # add-one smoothing â€” sufficient for short LoCoMo answers
        p = (clipped + 1) / (total + 1)
        log_precisions.append(math.log(max(p, 1e-9)))

    # Brevity penalty
    bp = (
        1.0
        if len(cand_tokens) > len(ref_tokens)
        else math.exp(1 - len(ref_tokens) / max(1, len(cand_tokens)))
    )
    geo_mean = math.exp(sum(w * lp for w, lp in zip(weights, log_precisions, strict=True)))
    return max(0.0, min(1.0, bp * geo_mean))


# ---------------------------------------------------------------------------
# Per-condition runner
# ---------------------------------------------------------------------------


@dataclass
class LoCoMoPerQuestionResult:
    qid: str
    episode_id: str
    category: str
    seed: int
    condition: str
    grader_score: float
    bleu4: float
    latency_ms: float
    grader_cached: bool
    candidate_answer: str
    gold_answer: str


@dataclass
class LoCoMoResult:
    dataset: str
    n_episodes: int
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
    """Same shape as the LongMemEval dry-run grader.

    Substring match; not a real grader. Lets ``--dry-run`` verify wiring
    without any API calls.
    """

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


async def _run_locomo_condition(
    *,
    condition: str,
    store_urls: list[str],
    episodes: list[LoCoMoEpisode],
    seeds: list[int],
    k: int,
    grader: GraderProtocol,
    dry_run: bool,
) -> list[LoCoMoPerQuestionResult]:
    rows: list[LoCoMoPerQuestionResult] = []
    workspace = Path(".memorywire-eval-dbs") / "locomo"
    for seed in seeds:
        _ = random.Random(seed)

        for ep in episodes:
            # One pass over every QA pair for this episode, but each
            # question runs against a *fresh* Memory with a unique
            # agent_id **and** a per-question sqlite-vec file. The fresh
            # file is correctness-critical: sqlite-vec's vec0 ANN runs
            # ``MATCH ... AND k=N`` before the agent_id WHERE filter, so
            # a shared DB lets earlier questions' rows crowd the current
            # agent's content out of the candidate set and recall
            # returns zero hits. See
            # ``scripts/lib/eval_common.per_question_store_urls``.
            for q in ep.questions:
                agent_id = f"locomo-{condition}-{seed}-{ep.episode_id}-{q['qid']}"
                scoped_urls, owned_dbs = per_question_store_urls(
                    store_urls,
                    workspace=workspace,
                    key=f"{condition}-{seed}-{ep.episode_id}-{q['qid']}",
                )
                mem = Memory(agent_id=agent_id, stores=scoped_urls)
                try:
                    # Ingest the episode session history into THIS
                    # question's agent-scoped slice.
                    for sess_ix, session in enumerate(ep.sessions):
                        for turn_ix, turn in enumerate(session):
                            if not turn.get("content"):
                                continue
                            try:
                                await mem.remember(
                                    turn["content"],
                                    type=MemoryType.EPISODIC,
                                    metadata={
                                        "episode_id": ep.episode_id,
                                        "session_id": sess_ix,
                                        "turn_ix": turn_ix,
                                        "role": turn.get("role", "user"),
                                    },
                                )
                            except Exception as exc:
                                sys.stderr.write(
                                    f"warning: remember failed for {ep.episode_id}/"
                                    f"{sess_ix}/{turn_ix}: {type(exc).__name__}: {exc}\n"
                                )

                    t0 = time.perf_counter()
                    try:
                        hits = await mem.recall(q["question"], k=k)
                    except Exception as exc:
                        sys.stderr.write(
                            f"warning: recall failed for {q['qid']}: {type(exc).__name__}: {exc}\n"
                        )
                        hits = []
                    latency_ms = (time.perf_counter() - t0) * 1000.0
                    context = build_grader_context(hits)
                    candidate = f"Retrieved memories:\n{context}"

                    cached_flag = False
                    if dry_run:
                        grader_score = grader.grade(
                            question=q["question"],
                            gold_answer=q["gold_answer"],
                            candidate_answer=candidate,
                            rubric=None,
                        )
                    else:
                        if isinstance(grader, LLMGrader):
                            meta = grader.grade_with_meta(
                                question=q["question"],
                                gold_answer=q["gold_answer"],
                                candidate_answer=candidate,
                                rubric=None,
                            )
                            grader_score = meta.score
                            cached_flag = meta.cached
                        else:
                            grader_score = grader.grade(
                                question=q["question"],
                                gold_answer=q["gold_answer"],
                                candidate_answer=candidate,
                                rubric=None,
                            )

                    rows.append(
                        LoCoMoPerQuestionResult(
                            qid=str(q["qid"]),
                            episode_id=ep.episode_id,
                            category=str(q.get("category") or "general"),
                            seed=seed,
                            condition=condition,
                            grader_score=grader_score,
                            bleu4=_bleu4(candidate, q["gold_answer"]),
                            latency_ms=latency_ms,
                            grader_cached=cached_flag,
                            candidate_answer=candidate[:500],
                            gold_answer=q["gold_answer"],
                        )
                    )
                finally:
                    await mem.close()
                    cleanup_question_dbs(owned_dbs)
    return rows


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _summarise(rows: list[LoCoMoPerQuestionResult]) -> dict[str, Any]:
    if not rows:
        return {
            "n_questions": 0,
            "grader_mean": 0.0,
            "bleu4_mean": 0.0,
            "per_category_grader": {},
            "per_category_bleu4": {},
            "per_seed_grader": {},
        }
    per_cat_g: dict[str, list[float]] = {}
    per_cat_b: dict[str, list[float]] = {}
    per_seed: dict[int, list[float]] = {}
    for r in rows:
        per_cat_g.setdefault(r.category, []).append(r.grader_score)
        per_cat_b.setdefault(r.category, []).append(r.bleu4)
        per_seed.setdefault(r.seed, []).append(r.grader_score)
    return {
        "n_questions": len(rows),
        "grader_mean": statistics.fmean(r.grader_score for r in rows),
        "bleu4_mean": statistics.fmean(r.bleu4 for r in rows),
        "per_category_grader": {k: statistics.fmean(v) for k, v in per_cat_g.items()},
        "per_category_bleu4": {k: statistics.fmean(v) for k, v in per_cat_b.items()},
        "per_seed_grader": {k: statistics.fmean(v) for k, v in per_seed.items()},
    }


def _pair_scores(
    rows_a: Iterable[LoCoMoPerQuestionResult],
    rows_b: Iterable[LoCoMoPerQuestionResult],
    *,
    metric: str,
) -> tuple[list[float], list[float]]:
    """Pair scores by (qid, seed) for paired bootstrap."""
    list_a = list(rows_a)
    list_b = list(rows_b)
    index_a = {(r.qid, r.seed): getattr(r, metric) for r in list_a}
    index_b = {(r.qid, r.seed): getattr(r, metric) for r in list_b}
    common = sorted(set(index_a.keys()) & set(index_b.keys()))
    return [index_a[k] for k in common], [index_b[k] for k in common]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_text(result: LoCoMoResult) -> str:
    lines: list[str] = []
    lines.append("memorywire LoCoMo harness")
    lines.append("=" * 76)
    lines.append(f"  dataset            : {result.dataset}")
    lines.append(f"  episodes           : {result.n_episodes}")
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
    lines.append(f"{'condition':<32}{'grader':>10}{'BLEU-4':>10}  per-category (grader)")
    for cond in result.per_condition:
        per_cat = "  ".join(f"{c}={v:.3f}" for c, v in sorted(cond["per_category_grader"].items()))
        lines.append(
            f"{cond['condition']:<32}{cond['grader_mean']:>10.3f}{cond['bleu4_mean']:>10.3f}  {per_cat}"
        )

    if result.pairwise_comparisons:
        lines.append("")
        lines.append("Pairwise comparisons (paired bootstrap, Holm-Bonferroni corrected)")
        lines.append("-" * 76)
        for cmp in result.pairwise_comparisons:
            ci = f"[{cmp['ci_low']:+.3f}, {cmp['ci_high']:+.3f}]"
            label = f"{cmp['a']} vs {cmp['b']} ({cmp['metric']})"
            lines.append(
                f"  {label:<60} Î”={cmp['mean_diff']:+.3f}  CI={ci}  "
                f"p={cmp['p_value_raw']:.3g}  reject={cmp['reject_null']}"
            )
    return "\n".join(lines)


def _try_plot(result: LoCoMoResult, plot_path: Path) -> str | None:
    try:
        import matplotlib  # type: ignore[import-not-found]

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]
    except ImportError as exc:
        return f"matplotlib not installed ({exc}); plot skipped."

    try:
        conditions = result.conditions
        # Plot grader mean and BLEU-4 mean side-by-side per condition.
        if not conditions:
            return "no data to plot"
        graders = [c["grader_mean"] for c in result.per_condition]
        bleus = [c["bleu4_mean"] for c in result.per_condition]
        xs = list(range(len(conditions)))
        bar_w = 0.4
        fig, ax = plt.subplots(figsize=(max(6, len(conditions) * 1.5), 4.5))
        ax.bar([x - bar_w / 2 for x in xs], graders, width=bar_w, label="grader")
        ax.bar([x + bar_w / 2 for x in xs], bleus, width=bar_w, label="BLEU-4")
        ax.set_xticks(xs)
        ax.set_xticklabels(conditions, rotation=20, ha="right")
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("score (mean)")
        ax.set_title("memorywire LoCoMo â€” overall means")
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(loc="best")
        fig.tight_layout()
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_path, dpi=120)
        plt.close(fig)
        return None
    except Exception as exc:
        return f"plot write failed: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def _estimated_cost_usd(
    *, n_questions: int, n_conditions: int, n_seeds: int, grader_model: str
) -> float:
    """LoCoMo prompts are longer than LongMemEval (more session context);
    bump input-token estimate to 900."""
    return estimate_grader_cost(
        n_calls=n_questions * n_conditions * n_seeds,
        avg_input_tokens=900,
        avg_output_tokens=100,
        model=grader_model,
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> LoCoMoResult:
    config = EvalConfig(
        stores=[s.strip() for s in args.stores.split(",") if s.strip()],
        seeds=args.seeds,
        n_queries=args.n_queries,
        k=args.k,
        grader_model=args.grader_model,
        cache_dir=Path(args.cache_dir).expanduser(),
        dataset_name="locomo",
        dry_run=args.dry_run,
        download=args.download,
        json_output=bool(args.json),
        plot=args.plot,
        out_json=Path(args.out_json) if args.out_json else None,
        out_csv_dir=Path(args.out_csv_dir) if args.out_csv_dir else None,
    )

    if config.dry_run:
        # n_queries here means "total questions across episodes". We
        # synthesise ~1 question per episode, so n_episodes â‰ˆ n_queries.
        episodes = _load_synthetic_locomo(max(1, args.n_queries or 3))
        dataset_label = "locomo-synthetic-dry-run"
    else:
        staged = stage_dataset(
            "locomo",
            config.cache_dir,
            download=config.download,
            hf_repo=LOCOMO_HF_REPO,
            git_url=LOCOMO_GIT_URL,
        )
        episodes = _load_locomo_from_disk(staged.root)
        dataset_label = f"locomo ({staged.source})"

    # Cap total questions: flatten to a list and trim, preserving episode order.
    total_q = sum(len(ep.questions) for ep in episodes)
    if args.n_queries and args.n_queries > 0 and total_q > args.n_queries:
        budget = args.n_queries
        capped_eps: list[LoCoMoEpisode] = []
        for ep in episodes:
            if budget <= 0:
                break
            take = min(len(ep.questions), budget)
            capped_eps.append(
                LoCoMoEpisode(
                    episode_id=ep.episode_id,
                    sessions=ep.sessions,
                    questions=ep.questions[:take],
                )
            )
            budget -= take
        episodes = capped_eps
    n_questions = sum(len(ep.questions) for ep in episodes)
    if n_questions == 0:
        raise RuntimeError("no questions to evaluate; check dataset cache or --n-queries")

    conditions = [(url, url) for url in config.stores]

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

    cost = _estimated_cost_usd(
        n_questions=n_questions,
        n_conditions=len(conditions),
        n_seeds=config.seeds,
        grader_model=config.grader_model,
    )
    sys.stderr.write(
        f"LoCoMo harness: {len(episodes)} episodes / {n_questions} questions x "
        f"{len(conditions)} conditions x {config.seeds} seeds -> "
        f"~{n_questions * len(conditions) * config.seeds} grader calls; "
        f"estimated cost: ${cost:.2f} ({config.grader_model})\n"
    )
    if config.dry_run:
        sys.stderr.write("(dry-run: no grader calls will be made)\n")

    seeds = list(range(config.seeds))
    all_rows: list[LoCoMoPerQuestionResult] = []
    wall_start = time.perf_counter()
    grader_calls = 0
    grader_cache_hits = 0
    try:
        for cond_label, store_url in conditions:
            rows = await _run_locomo_condition(
                condition=cond_label,
                store_urls=[store_url],
                episodes=episodes,
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

    # Aggregate
    per_condition: list[dict[str, Any]] = []
    for cond_label, _ in conditions:
        rows = [r for r in all_rows if r.condition == cond_label]
        summary = _summarise(rows)
        summary["condition"] = cond_label
        per_condition.append(summary)

    # Comparisons: memorywire variant vs baseline (first store), on both metrics.
    comparisons: list[dict[str, Any]] = []
    if len(per_condition) >= 2:
        baseline = per_condition[0]["condition"]
        baseline_rows = [r for r in all_rows if r.condition == baseline]
        for cond in per_condition[1:]:
            cond_rows = [r for r in all_rows if r.condition == cond["condition"]]
            metric_pvalues: list[float] = []
            metric_meta: list[dict[str, Any]] = []
            for metric in ("grader_score", "bleu4"):
                a, b = _pair_scores(cond_rows, baseline_rows, metric=metric)
                if not a or not b:
                    continue
                mean_a, mean_b, ci_low, ci_high, p = paired_bootstrap_ci(a, b)
                metric_meta.append(
                    {
                        "a": cond["condition"],
                        "b": baseline,
                        "metric": metric,
                        "mean_a": mean_a,
                        "mean_b": mean_b,
                        "mean_diff": mean_a - mean_b,
                        "ci_low": ci_low,
                        "ci_high": ci_high,
                        "p_value_raw": p,
                        "n_pairs": len(a),
                    }
                )
                metric_pvalues.append(p)
            # Holm correction across the two metrics for this comparison.
            rejected = holm_bonferroni(metric_pvalues)
            for meta, reject in zip(metric_meta, rejected, strict=True):
                meta["reject_null"] = bool(reject)
                comparisons.append(meta)

    result = LoCoMoResult(
        dataset=dataset_label,
        n_episodes=len(episodes),
        n_questions=n_questions,
        seeds=seeds,
        k=config.k,
        grader_model=config.grader_model,
        dry_run=config.dry_run,
        conditions=[c["condition"] for c in per_condition],
        per_question=[asdict(r) for r in all_rows],
        per_condition=per_condition,
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
        prog="run_locomo",
        description="memorywire LoCoMo harness (paper Â§5 long-conversation numbers).",
    )
    p.add_argument(
        "--stores",
        type=str,
        default="sqlite-vec://./locomo.db",
        help="Comma-separated memorywire store URLs.",
    )
    p.add_argument("--seeds", type=int, default=5, help="Number of seeds (default: 5).")
    p.add_argument(
        "--n-queries",
        type=int,
        default=200,
        help="Total question cap; 0 = all (default: 200).",
    )
    p.add_argument("--k", type=int, default=5, help="Top-k for Memory.recall (default: 5).")
    p.add_argument(
        "--grader-model",
        type=str,
        default="gpt-4-turbo",
        help="OpenAI grader model (default: gpt-4-turbo).",
    )
    p.add_argument(
        "--cache-dir",
        type=str,
        default=str(Path("~/.cache/amp").expanduser()),
        help="Cache root (default: ~/.cache/amp).",
    )
    p.add_argument("--download", action="store_true", help="Fetch dataset if missing.")
    p.add_argument("--dry-run", action="store_true", help="Skip grader API calls.")
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    p.add_argument("--plot", action="store_true", help="Write docs/locomo-results.png.")
    p.add_argument(
        "--out-json",
        type=str,
        default=str(_REPO_ROOT / "docs" / "locomo-results.json"),
        help="JSON results path (default: docs/locomo-results.json).",
    )
    p.add_argument(
        "--out-csv-dir",
        type=str,
        default=None,
        help="Optional directory for per-question CSV dumps.",
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

    if args.out_json:
        write_json(Path(args.out_json), asdict(result))
    if args.out_csv_dir:
        out_dir = Path(args.out_csv_dir)
        write_csv(out_dir / "per_question.csv", result.per_question)

    if args.plot:
        plot_path = _REPO_ROOT / "docs" / "locomo-results.png"
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
