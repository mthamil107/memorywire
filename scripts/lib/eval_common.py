"""Shared helpers for the LongMemEval and LoCoMo eval harnesses.

This module contains every piece of plumbing that doesn't depend on a
specific dataset: statistics (paired bootstrap, Holm-Bonferroni), the
grader wrapper (OpenAI with retry + on-disk caching), and the
dataset-staging helper.

Design notes
------------
* No hard dependency on optional libraries. Every optional dep
  (``openai``, ``requests``, ``requests_cache``, ``pandas``,
  ``matplotlib``, ``pyarrow``) is imported lazily inside the function
  that needs it, so callers can ``from scripts.lib.eval_common import
  paired_bootstrap_ci`` on a bare environment and run the dry-run path
  without any of those installed.
* All randomness funnels through ``random.Random`` seeded by the caller;
  there is no module-level RNG state. This keeps the harness reproducible
  across machines and across reruns.
* The grader caches by ``sha256(prompt + model)``, so swapping models
  invalidates the cache and reruns automatically; resuming a partial run
  is the common case and we want that to be free.

The two paper-relevant statistical primitives are
:func:`paired_bootstrap_ci` and :func:`holm_bonferroni`. They are
deliberately small enough to read end-to-end; the docstrings cite the
references the paper uses.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shelve
import statistics
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EvalConfig:
    """Flag-driven configuration shared by both runners.

    Both ``run_longmemeval.py`` and ``run_locomo.py`` instantiate this
    from argparse and pass it down through the eval loop. Keep it small
    and JSON-serializable — the per-run JSON output embeds it for
    reproducibility audit (paper §5 calls this out).
    """

    stores: list[str] = field(default_factory=lambda: ["sqlite-vec://./eval.db"])
    seeds: int = 5
    n_queries: int = 200
    k: int = 5
    grader_model: str = "gpt-4-turbo"
    cache_dir: Path = field(default_factory=lambda: Path(os.path.expanduser("~/.cache/amp")))
    dataset_name: str = ""
    dry_run: bool = False
    download: bool = False
    json_output: bool = False
    plot: bool = False
    out_json: Path | None = None
    out_csv_dir: Path | None = None

    def to_jsonable(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict (Path → str)."""
        return {
            "stores": list(self.stores),
            "seeds": self.seeds,
            "n_queries": self.n_queries,
            "k": self.k,
            "grader_model": self.grader_model,
            "cache_dir": str(self.cache_dir),
            "dataset_name": self.dataset_name,
            "dry_run": self.dry_run,
            "download": self.download,
            "json_output": self.json_output,
            "plot": self.plot,
            "out_json": str(self.out_json) if self.out_json else None,
            "out_csv_dir": str(self.out_csv_dir) if self.out_csv_dir else None,
        }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def paired_bootstrap_ci(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_resamples: int = 10_000,
    seed: int = 1337,
    alpha: float = 0.05,
) -> tuple[float, float, float, float, float]:
    """Paired bootstrap CI on the difference of two paired score lists.

    Parameters
    ----------
    a, b:
        Equal-length sequences of per-item scores from two conditions
        (e.g. AMP vs single-backend baseline) evaluated on the *same*
        items. Pairing is positional: ``a[i]`` and ``b[i]`` must be the
        same question / seed.
    n_resamples:
        Number of bootstrap resamples (default 10000, matches the
        paper's stated protocol; "Methodology" in
        ``docs/paper/eval-protocol.md``).
    seed:
        RNG seed so the CI is reproducible across reruns.
    alpha:
        Two-sided significance level; defaults to 0.05 → 95% CI.

    Returns
    -------
    ``(mean_a, mean_b, ci_low, ci_high, p_value)``. ``ci_low`` / ``ci_high``
    bound the difference ``mean(a) - mean(b)``. ``p_value`` is the
    two-sided bootstrap p-value: ``2 * min(P(diff* >= 0), P(diff* <= 0))``.

    Notes
    -----
    Pure-stdlib implementation — no NumPy dependency, because the eval
    harness must run on a fresh ``pip install agent-memory-protocol``
    without numpy/scipy.

    References
    ----------
    Efron & Tibshirani (1993), "An Introduction to the Bootstrap" §16
    (paired bootstrap).
    """
    if len(a) != len(b):
        raise ValueError(
            f"paired_bootstrap_ci requires equal-length inputs; got {len(a)} vs {len(b)}"
        )
    if not a:
        raise ValueError("paired_bootstrap_ci requires at least one paired observation")
    n = len(a)
    diffs = [float(a[i]) - float(b[i]) for i in range(n)]
    mean_a = statistics.fmean(a)
    mean_b = statistics.fmean(b)
    rng = random.Random(seed)

    boot_diffs: list[float] = []
    # Resample with replacement on the paired differences (one resample
    # of size n per iteration). This is equivalent to resampling paired
    # rows and recomputing the difference of means, since differences
    # are linear.
    for _ in range(n_resamples):
        s = 0.0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        boot_diffs.append(s / n)

    boot_diffs.sort()
    lo_idx = max(0, math.floor((alpha / 2.0) * n_resamples))
    hi_idx = min(n_resamples - 1, math.ceil((1.0 - alpha / 2.0) * n_resamples) - 1)
    ci_low = boot_diffs[lo_idx]
    ci_high = boot_diffs[hi_idx]

    # Two-sided bootstrap p-value: how often the resampled mean diff
    # falls on the wrong side of zero (cf. Hesterberg 2015, "What
    # Teachers Should Know About the Bootstrap").
    n_ge_zero = sum(1 for d in boot_diffs if d >= 0)
    n_le_zero = sum(1 for d in boot_diffs if d <= 0)
    p_value = 2.0 * min(n_ge_zero, n_le_zero) / n_resamples
    p_value = min(1.0, p_value)

    return mean_a, mean_b, ci_low, ci_high, p_value


def holm_bonferroni(
    pvalues: Sequence[float],
    *,
    alpha: float = 0.05,
) -> list[bool]:
    """Holm-Bonferroni step-down multiple-comparisons correction.

    Returns a boolean ``reject`` mask the same length as ``pvalues``;
    ``True`` at index ``i`` means the ``i``-th null hypothesis is
    rejected at family-wise significance ``alpha`` after correction.

    Algorithm (Holm 1979):
    1. Sort p-values ascending; let ``p_(1) <= ... <= p_(m)``.
    2. Reject ``H_(i)`` iff for all ``j <= i``,
       ``p_(j) <= alpha / (m - j + 1)``.
    3. Once a step fails to reject, all later steps also fail to reject.

    The function preserves the *original* order of ``pvalues`` in its
    return value (it sorts internally only to do the comparison).

    References
    ----------
    Holm, S. (1979). "A Simple Sequentially Rejective Multiple Test
    Procedure". Scand. J. Statist. 6: 65-70.
    """
    if not pvalues:
        return []
    m = len(pvalues)
    # Pair each p-value with its original index so we can return the
    # mask in input order. Stable sort so ties resolve deterministically.
    indexed = sorted(enumerate(pvalues), key=lambda pair: pair[1])
    reject_in_sorted_order = [False] * m
    can_reject = True
    for sort_idx, (_, p) in enumerate(indexed):
        threshold = alpha / (m - sort_idx)
        if can_reject and p <= threshold:
            reject_in_sorted_order[sort_idx] = True
        else:
            can_reject = False  # Once we fail to reject, all subsequent must fail too.

    mask = [False] * m
    for sort_idx, (orig_idx, _) in enumerate(indexed):
        mask[orig_idx] = reject_in_sorted_order[sort_idx]
    return mask


# ---------------------------------------------------------------------------
# Grader
# ---------------------------------------------------------------------------


class GraderProtocol(Protocol):
    """Structural type for "something that grades an answer 0-1".

    The harness wires :class:`LLMGrader` in production and a deterministic
    stub in tests; both satisfy this Protocol.
    """

    def grade(
        self,
        *,
        question: str,
        gold_answer: str,
        candidate_answer: str,
        rubric: str | None = None,
    ) -> float: ...


@dataclass
class GraderResult:
    """Result of one grader call."""

    score: float
    raw_response: str
    cached: bool
    latency_ms: float


class LLMGrader:
    """OpenAI-backed grader with retry, exponential backoff, and on-disk caching.

    The grader sends a short prompt asking the LLM to score a candidate
    answer against a gold reference on a ``0.0..1.0`` scale. Results are
    cached on ``sha256(prompt + model)`` so reruns are free and partial
    runs resume cleanly. The cache backend is ``requests-cache`` when
    installed (faster, sqlite-backed) and falls back to stdlib ``shelve``
    otherwise.

    Cache invalidation
    ------------------
    Swap models → key changes → cache miss → fresh grade. Swap prompt
    template → key changes → cache miss → fresh grade. This is
    intentional: the paper's reproducibility claim hinges on the cache
    capturing the *exact* grader prompt + model used to produce the
    numbers, and on a different setup producing different numbers
    cleanly rather than silently reusing old grades.
    """

    DEFAULT_PROMPT_TEMPLATE = (
        "You are a strict grader for an agent-memory eval. "
        "Score the candidate answer against the gold answer.\n\n"
        "Question: {question}\n"
        "Gold answer: {gold_answer}\n"
        "Candidate answer: {candidate_answer}\n"
        "{rubric_section}"
        'Output JSON of the form {{"score": <0.0-1.0>, "reason": "..."}}. '
        "Score 1.0 only if the candidate fully answers the question with no contradictions; "
        "0.0 if it is wrong, hallucinated, or empty. Partial credit allowed."
    )

    def __init__(
        self,
        *,
        model: str = "gpt-4-turbo",
        api_key: str | None = None,
        cache_dir: Path | None = None,
        prompt_template: str | None = None,
        max_retries: int = 4,
        request_timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._cache_dir = cache_dir or Path(os.path.expanduser("~/.cache/amp/grader"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._prompt_template = prompt_template or self.DEFAULT_PROMPT_TEMPLATE
        self._max_retries = max_retries
        self._request_timeout = request_timeout
        self._client: Any | None = None
        self._cache: _CacheBackend = _open_cache(self._cache_dir)

    @property
    def model(self) -> str:
        return self._model

    def close(self) -> None:
        self._cache.close()

    def _format_prompt(
        self,
        *,
        question: str,
        gold_answer: str,
        candidate_answer: str,
        rubric: str | None,
    ) -> str:
        rubric_section = f"Rubric: {rubric}\n" if rubric else ""
        return self._prompt_template.format(
            question=question,
            gold_answer=gold_answer,
            candidate_answer=candidate_answer,
            rubric_section=rubric_section,
        )

    def _cache_key(self, prompt: str) -> str:
        h = hashlib.sha256()
        h.update(self._model.encode("utf-8"))
        h.update(b"\x00")
        h.update(prompt.encode("utf-8"))
        return h.hexdigest()

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set; pass --dry-run to test the harness without a grader."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed; `pip install openai` to use the grader."
            ) from exc
        self._client = OpenAI(api_key=self._api_key, timeout=self._request_timeout)
        return self._client

    def _call_openai(self, prompt: str) -> str:
        client = self._ensure_client()
        # Backoff is exponential with jitter; we don't retry on 4xx
        # except 429 (rate limit). 429 and 5xx → retry.
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=200,
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:  # broad: openai exception hierarchy varies by version
                last_exc = exc
                status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
                # Retry on rate-limit (429) and server errors (5xx); fail fast on others.
                if status not in (429, 500, 502, 503, 504, None):
                    raise
                if attempt == self._max_retries - 1:
                    raise
                # Exponential backoff with jitter.
                sleep_s = (2**attempt) + random.Random(attempt).random()
                time.sleep(min(sleep_s, 30.0))
        # Defensive — we only get here if max_retries == 0.
        raise RuntimeError(f"grader call failed after {self._max_retries} retries: {last_exc}")

    def grade_with_meta(
        self,
        *,
        question: str,
        gold_answer: str,
        candidate_answer: str,
        rubric: str | None = None,
    ) -> GraderResult:
        """Grade and return the score plus diagnostic metadata."""
        prompt = self._format_prompt(
            question=question,
            gold_answer=gold_answer,
            candidate_answer=candidate_answer,
            rubric=rubric,
        )
        key = self._cache_key(prompt)
        cached_raw = self._cache.get(key)
        if cached_raw is not None:
            score, raw = _parse_grader_response(cached_raw)
            return GraderResult(score=score, raw_response=raw, cached=True, latency_ms=0.0)
        t0 = time.perf_counter()
        raw = self._call_openai(prompt)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        self._cache.set(key, raw)
        score, _ = _parse_grader_response(raw)
        return GraderResult(score=score, raw_response=raw, cached=False, latency_ms=latency_ms)

    def grade(
        self,
        *,
        question: str,
        gold_answer: str,
        candidate_answer: str,
        rubric: str | None = None,
    ) -> float:
        return self.grade_with_meta(
            question=question,
            gold_answer=gold_answer,
            candidate_answer=candidate_answer,
            rubric=rubric,
        ).score


def _parse_grader_response(raw: str) -> tuple[float, str]:
    """Parse the grader's JSON response into a 0..1 score.

    Tolerant on purpose: trims markdown fences, swallows trailing text,
    accepts ``score`` as either int or float, clamps to [0, 1]. Returns
    ``(0.0, raw)`` if the response cannot be parsed at all — better to
    score a malformed grader reply as zero than to crash a 1000-question
    eval halfway through.
    """
    stripped = raw.strip()
    # Strip markdown fences if the grader wrapped JSON in them despite
    # response_format=json_object — defensive, not expected.
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(line for line in lines if not line.startswith("```"))
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        # Last-ditch: try to find the first JSON object.
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                return 0.0, raw
        else:
            return 0.0, raw
    score = data.get("score", 0.0)
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        return 0.0, raw
    if not math.isfinite(score_f):
        return 0.0, raw
    return max(0.0, min(1.0, score_f)), raw


# ---------------------------------------------------------------------------
# Cache backends
# ---------------------------------------------------------------------------


class _CacheBackend(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def close(self) -> None: ...


class _ShelveCache:
    """Stdlib-only cache backend; one DBM file under cache_dir."""

    def __init__(self, path: Path) -> None:
        self._path = path
        # writeback=False keeps memory bounded; we use the cache as a
        # straight key-value store. The shelf is held for the grader's
        # lifetime and closed via :meth:`close` — a ``with`` block here
        # would close it before any grader call could use it.
        self._shelf = shelve.open(str(path), writeback=False)  # noqa: SIM115

    def get(self, key: str) -> str | None:
        raw = self._shelf.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    def set(self, key: str, value: str) -> None:
        self._shelf[key] = value
        # Sync after every write so a SIGINT mid-run doesn't lose the
        # last grade. The dataset is small enough that the I/O is free.
        self._shelf.sync()

    def close(self) -> None:
        self._shelf.close()


class _RequestsCacheBackend:
    """requests-cache backed sqlite store (optional, faster than shelve)."""

    def __init__(self, path: Path) -> None:
        # Use the sqlite backend explicitly; the default backend picks
        # whatever's available and would surprise us.
        from requests_cache.backends.sqlite import SQLiteCache  # type: ignore[import-not-found]

        # We're not actually using requests-cache for HTTP requests; we
        # just want its sqlite key-value store. Construct directly.
        self._backend = SQLiteCache(db_path=str(path))

    def get(self, key: str) -> str | None:
        raw = self._backend.responses.get(key)
        if raw is None:
            return None
        return str(raw)

    def set(self, key: str, value: str) -> None:
        self._backend.responses[key] = value

    def close(self) -> None:
        # SQLiteCache cleans up on GC; no explicit close API.
        return


def _open_cache(cache_dir: Path) -> _CacheBackend:
    """Pick the best available cache backend."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        # Only use requests-cache if its sqlite backend imports cleanly
        # *and* exposes the ``responses`` mapping we expect.
        from requests_cache.backends.sqlite import (  # noqa: F401
            SQLiteCache,
        )

        return _RequestsCacheBackend(cache_dir / "grader_cache.sqlite")
    except Exception:
        return _ShelveCache(cache_dir / "grader_cache.shelve")


# ---------------------------------------------------------------------------
# Dataset staging
# ---------------------------------------------------------------------------


@dataclass
class StagedDataset:
    """Result of :func:`stage_dataset`."""

    name: str
    root: Path
    source: str  # "cache" | "hf-hub" | "git" | "synthetic"
    note: str | None = None


def stage_dataset(
    name: str,
    cache_dir: Path,
    *,
    download: bool = False,
    hf_repo: str | None = None,
    git_url: str | None = None,
) -> StagedDataset:
    """Discover or fetch a benchmark dataset under ``cache_dir``.

    Two paths:

    * ``download=False`` (default): look for an existing dataset
      directory at ``cache_dir / name``. If absent, raise
      :class:`FileNotFoundError` with a clear message telling the user
      to rerun with ``--download``.
    * ``download=True``: try HuggingFace Hub (``hf_repo``) first, then
      ``git clone`` (``git_url``); record which path produced the data.

    The function never deletes existing data. If both branches fail, we
    raise so the user can see what happened.
    """
    root = cache_dir / name
    if root.exists() and any(root.iterdir()):
        return StagedDataset(name=name, root=root, source="cache")

    if not download:
        raise FileNotFoundError(
            f"dataset {name!r} not found under {cache_dir}; rerun with --download "
            f"(or stage it manually under {root})"
        )

    root.mkdir(parents=True, exist_ok=True)

    # Try HuggingFace first if a repo was provided.
    if hf_repo:
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=hf_repo, repo_type="dataset", local_dir=str(root))
            return StagedDataset(name=name, root=root, source="hf-hub", note=f"hf:{hf_repo}")
        except ImportError:
            pass  # fall through to git
        except Exception as exc:  # network, auth, repo-not-found
            sys.stderr.write(f"hf-hub fetch failed for {name}: {exc!r}; trying git\n")

    if git_url:
        import subprocess

        result = subprocess.run(
            ["git", "clone", "--depth", "1", git_url, str(root)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return StagedDataset(name=name, root=root, source="git", note=f"git:{git_url}")
        raise RuntimeError(
            f"failed to git-clone {git_url}: rc={result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    raise RuntimeError(
        f"no fetch path configured for {name!r}: pass hf_repo or git_url to stage_dataset"
    )


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


# Rough per-1k-token rates as of 2026-Q2. Conservative defaults; users
# can pass their own --grader-model and we'll fall back to a generic
# rate. We don't track *every* model — only the ones we recommend.
GRADER_RATES_USD_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    # model -> (input_per_1k, output_per_1k)
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4.1": (0.002, 0.008),
}


def estimate_grader_cost(
    *,
    n_calls: int,
    avg_input_tokens: int,
    avg_output_tokens: int,
    model: str,
) -> float:
    """Cost estimate in USD for ``n_calls`` grader invocations.

    If the model isn't in :data:`GRADER_RATES_USD_PER_1K_TOKENS` we use
    the ``gpt-4-turbo`` rate as a pessimistic default — better the user
    overestimates and isn't surprised than the other way around.
    """
    rate_in, rate_out = GRADER_RATES_USD_PER_1K_TOKENS.get(
        model, GRADER_RATES_USD_PER_1K_TOKENS["gpt-4-turbo"]
    )
    in_cost = n_calls * avg_input_tokens / 1000.0 * rate_in
    out_cost = n_calls * avg_output_tokens / 1000.0 * rate_out
    return in_cost + out_cost


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def per_question_store_urls(
    base_urls: Sequence[str],
    *,
    workspace: Path,
    key: str,
) -> tuple[list[str], list[Path]]:
    """Rewrite store URLs so each question gets a *fresh* SQLite file.

    The eval harnesses rely on a per-question ``agent_id`` to isolate
    questions from each other on a shared sqlite-vec DB. That isolation
    is defeated by the vec0 ANN's top-k pre-filter: vec0 returns the K
    nearest neighbours across *every* agent's rows, then the SQL WHERE
    clause filters by ``agent_id``. When the shared DB has thousands of
    other agents' rows, none of the current agent's content makes it
    into the candidate set and recall returns zero hits.

    This helper sidesteps the issue by giving each (question, seed)
    combination its own fresh SQLite file under ``workspace``. The path
    encodes ``key`` so concurrent harness runs don't clobber each
    other. Non-``sqlite-vec`` URLs pass through unchanged — Mem0,
    Letta, etc. manage their own per-tenant isolation.

    Parameters
    ----------
    base_urls:
        The original store URLs from the harness's ``--stores`` flag.
    workspace:
        Directory to drop per-question SQLite files into. Must exist
        (or be creatable).
    key:
        A filesystem-safe key (e.g. ``f"{condition}-{seed}-{qid}"``)
        used to make the per-question DB filename unique.

    Returns
    -------
    ``(rewritten_urls, owned_paths)``:

    * ``rewritten_urls`` — the URL list to feed to ``Memory(stores=...)``.
    * ``owned_paths`` — the files the helper created and the caller
      should delete after ``mem.close()``. Empty for non-sqlite-vec
      URLs.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    out_urls: list[str] = []
    owned: list[Path] = []
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    for url in base_urls:
        scheme = url.split("://", 1)[0].lower() if "://" in url else ""
        if scheme in {"sqlite-vec", "sqlite+vec", "sqlitevec"}:
            db_path = workspace / f"q-{safe}.db"
            # Remove any stragglers from a prior crashed run so the file
            # we hand to sqlite-vec is genuinely fresh.
            for sfx in ("", "-wal", "-shm", "-journal"):
                p = db_path.with_name(db_path.name + sfx)
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            out_urls.append(f"sqlite-vec://{db_path.as_posix()}")
            owned.append(db_path)
        else:
            out_urls.append(url)
    return out_urls, owned


def cleanup_question_dbs(paths: Iterable[Path]) -> None:
    """Best-effort removal of the per-question DB files + their sidecars.

    SQLite WAL/SHM journals are removed alongside the main DB so the
    workspace stays bounded across a 1000-question run. Errors are
    swallowed — losing a stale DB file is never worth aborting the
    harness for.
    """
    for db_path in paths:
        for sfx in ("", "-wal", "-shm", "-journal"):
            p = db_path.with_name(db_path.name + sfx)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


def build_grader_context(hits: Iterable[Any], *, max_chars: int = 4000) -> str:
    """Format a list of :class:`RecallHit` rows into a grader-facing context.

    The grader doesn't see the raw recall output — it sees a flat string
    of the top-k passages, one per line, prefixed with ``[i]``. We cap
    total length at ``max_chars`` so a runaway corpus can't blow the
    grader's context window. Truncation happens at the hit boundary
    (we drop whole hits from the tail, never split mid-content).
    """
    parts: list[str] = []
    total = 0
    for i, hit in enumerate(hits):
        content = getattr(hit, "content", None) or str(hit)
        line = f"[{i + 1}] {content}".strip()
        if total + len(line) + 1 > max_chars:
            break
        parts.append(line)
        total += len(line) + 1
    return "\n".join(parts) if parts else "(no relevant memories surfaced)"


def write_json(path: Path, data: Any) -> None:
    """Write ``data`` to ``path`` as pretty-printed JSON; mkdir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """Write ``rows`` to ``path`` as CSV; stdlib only (no pandas required)."""
    import csv

    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


__all__ = [
    "GRADER_RATES_USD_PER_1K_TOKENS",
    "EvalConfig",
    "GraderProtocol",
    "GraderResult",
    "LLMGrader",
    "StagedDataset",
    "build_grader_context",
    "cleanup_question_dbs",
    "estimate_grader_cost",
    "holm_bonferroni",
    "paired_bootstrap_ci",
    "per_question_store_urls",
    "stage_dataset",
    "write_csv",
    "write_json",
]
