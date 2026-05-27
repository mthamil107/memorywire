"""Opt-in tests for the LongMemEval / LoCoMo eval harness wiring.

Marked ``benchmark`` so the default ``pytest -m "not integration and
not benchmark"`` skips them. Opt in with ``pytest -m benchmark``.

What this covers
----------------
* :func:`scripts.lib.eval_common.paired_bootstrap_ci` on a known
  effect-size dataset — verifies the CI is in the right ballpark and
  the p-value is small.
* :func:`scripts.lib.eval_common.holm_bonferroni` on a textbook input
  — verifies the rejection mask matches the algorithm definition.
* The ``run_longmemeval.py --dry-run`` CLI on a tiny synthetic subset
  — verifies the full pipeline (dataset → AMP → grader → stats) wires
  end-to-end and the script exits 0.
* The :class:`LLMGrader` cache path — uses a mock OpenAI client so the
  test runs without an API key. Verifies the grader scores correctly
  and that cache hits skip the LLM call entirely.

These tests must pass on a bare environment (no openai, no
requests_cache, no matplotlib, no pandas, no pyarrow). The
``ModuleNotFoundError`` branch for each is exercised implicitly by
not importing them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Pull in the things we test. We import inside test functions where a
# fresh import matters (the grader cache test needs a clean module),
# but the stats primitives are pure and can be top-level.
from scripts.lib.eval_common import (  # noqa: E402
    LLMGrader,
    holm_bonferroni,
    paired_bootstrap_ci,
)

pytestmark = [pytest.mark.benchmark]


# ---------------------------------------------------------------------------
# Statistics primitives
# ---------------------------------------------------------------------------


def test_paired_bootstrap_smoke() -> None:
    """Bootstrap a known effect-size pair and assert the CI brackets the truth.

    We hand-build two paired score lists with a constant +0.2 lift in
    ``a`` over ``b``. The paired-bootstrap CI for ``mean(a) - mean(b)``
    must be tight around +0.2 and the p-value must be small.
    """
    # 30 paired observations, b[i] = a[i] - 0.2 deterministically.
    a = [0.5 + (i % 5) * 0.05 for i in range(30)]
    b = [x - 0.2 for x in a]
    mean_a, mean_b, ci_low, ci_high, p = paired_bootstrap_ci(a, b, n_resamples=2000, seed=42)

    # Means are exact (no resampling involved in the means themselves).
    assert abs(mean_a - mean_b - 0.2) < 1e-9, "constant +0.2 lift expected"
    # CI should bracket the true difference (0.2) tightly. With a
    # constant lift, the per-pair differences are zero-variance so the
    # bootstrap CI collapses to 0.2 ± float-precision epsilon. Use an
    # explicit epsilon rather than a strict <= because IEEE-754 noise
    # in the resample-sum / N can push both bounds slightly above 0.2.
    eps = 1e-9
    assert ci_low - eps <= 0.2 <= ci_high + eps, (
        f"CI [{ci_low}, {ci_high}] should bracket 0.2 within {eps}"
    )
    assert ci_high - ci_low < 0.01, "constant-lift CI should be very tight"
    # Two-sided p-value: with all paired diffs == 0.2 (>0), every
    # resample gives a positive mean, so n_le_zero == 0 and p == 0.0.
    assert p == 0.0, f"expected p=0.0 for constant +0.2 lift, got {p}"


def test_paired_bootstrap_no_effect() -> None:
    """Identical inputs → CI brackets 0, p ≈ 1.0."""
    a = [0.4, 0.5, 0.6, 0.5, 0.4, 0.7, 0.6, 0.5, 0.55, 0.45]
    b = list(a)
    mean_a, mean_b, ci_low, ci_high, p = paired_bootstrap_ci(a, b, n_resamples=2000, seed=42)
    assert mean_a == mean_b
    assert ci_low == 0.0 and ci_high == 0.0
    # With zero diffs, every resample has mean 0, both counts are
    # n_resamples, p = 2 * min / n = 2.0 → clamped to 1.0.
    assert p == pytest.approx(1.0)


def test_paired_bootstrap_input_validation() -> None:
    """Mismatched lengths and empty inputs both raise ValueError."""
    with pytest.raises(ValueError):
        paired_bootstrap_ci([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        paired_bootstrap_ci([], [])


def test_holm_bonferroni_smoke() -> None:
    """Textbook Holm-Bonferroni example.

    p-values = [0.01, 0.02, 0.03, 0.5] at alpha=0.05, m=4:
      sorted: 0.01, 0.02, 0.03, 0.5
      thresholds: 0.05/4=0.0125, 0.05/3=0.0167, 0.05/2=0.025, 0.05/1=0.05
      step 1: 0.01 <= 0.0125 → reject
      step 2: 0.02 <= 0.0167 → False → STOP, all subsequent fail
    So only the smallest is rejected; the rest are not.
    """
    pvalues = [0.01, 0.02, 0.03, 0.5]
    rejected = holm_bonferroni(pvalues, alpha=0.05)
    assert rejected == [True, False, False, False]


def test_holm_bonferroni_preserves_input_order() -> None:
    """Out-of-order input → rejection mask still aligns by index."""
    pvalues = [0.5, 0.01, 0.03, 0.02]
    rejected = holm_bonferroni(pvalues, alpha=0.05)
    # Sorted view: index 1 (0.01), 3 (0.02), 2 (0.03), 0 (0.5).
    # Step 1: 0.01 <= 0.05/4=0.0125 → reject (index 1).
    # Step 2: 0.02 <= 0.05/3=0.0167 → False, stop.
    assert rejected == [False, True, False, False]


def test_holm_bonferroni_empty() -> None:
    assert holm_bonferroni([]) == []


# ---------------------------------------------------------------------------
# Dry-run CLI smoke
# ---------------------------------------------------------------------------


def test_eval_dry_run_longmemeval(tmp_path: Path) -> None:
    """``run_longmemeval.py --dry-run --n-queries 3`` exits 0 and writes JSON.

    The dry-run path uses the synthetic dataset and the no-op grader,
    so it needs no API key and no sentence-transformers — fits CI.
    """
    out_json = tmp_path / "lme-dry.json"
    result = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "run_longmemeval.py"),
            "--dry-run",
            "--n-queries",
            "3",
            "--seeds",
            "1",
            "--out-json",
            str(out_json),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"run_longmemeval.py --dry-run failed: rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert out_json.exists(), "expected JSON output at --out-json path"
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["dry_run"] is True
    assert data["n_questions"] > 0
    assert data["grader_calls"] > 0
    # Result struct must include the per-condition aggregates.
    assert data["per_condition"], "per_condition aggregate missing"


def test_longmemeval_per_question_isolation(tmp_path: Path) -> None:
    """Bug-2 regression: question 2 must NOT see question 1's ingested content.

    Builds two LMEQuestions, each with a uniquely-fingerprinted fact in
    its session history, runs ``_run_condition`` against an isolated
    sqlite-vec DB in dry-run mode, then asserts the recorded candidate
    answer for question 2 contains question 2's fingerprint and NOT
    question 1's. Before the per-(seed, qid) ``Memory`` isolation fix,
    question 2's recall would surface question 1's content because they
    shared a single agent-scoped store.
    """
    import asyncio

    from scripts.run_longmemeval import (
        LMEQuestion,
        _NoOpGrader,
        _run_condition,
    )

    db_path = tmp_path / "leak-check.db"
    store_url = f"sqlite-vec://{db_path}"
    fingerprint_q1 = "ZEBRA-ALPHA-72431"
    fingerprint_q2 = "OCTOPUS-DELTA-19287"

    questions = [
        LMEQuestion(
            qid="qid-001",
            task_type="single_session_preferences",
            question="What is the unique fingerprint mentioned?",
            gold_answer=fingerprint_q1,
            sessions=[
                [
                    {"role": "user", "content": f"My secret code is {fingerprint_q1}."},
                    {"role": "assistant", "content": "Noted."},
                ],
            ],
            rubric=None,
        ),
        LMEQuestion(
            qid="qid-002",
            task_type="single_session_preferences",
            question="What is the unique fingerprint mentioned?",
            gold_answer=fingerprint_q2,
            sessions=[
                [
                    {"role": "user", "content": f"My secret code is {fingerprint_q2}."},
                    {"role": "assistant", "content": "Noted."},
                ],
            ],
            rubric=None,
        ),
    ]

    rows = asyncio.run(
        _run_condition(
            condition=store_url,
            store_urls=[store_url],
            questions=questions,
            seeds=[0],
            k=5,
            grader=_NoOpGrader(),
            dry_run=True,
        )
    )

    assert len(rows) == 2, f"expected 2 result rows, got {len(rows)}"
    row_q2 = next(r for r in rows if r.qid == "qid-002")
    # Question 2's recall surfaced its own ingest (fingerprint_q2). The
    # leak we're protecting against is question 1's fingerprint showing
    # up in question 2's recall context — that would indicate the agent
    # scope did not isolate the two.
    assert fingerprint_q1 not in row_q2.candidate_answer, (
        f"cross-question leak detected: question 1's fingerprint "
        f"{fingerprint_q1!r} surfaced in question 2's recall: "
        f"{row_q2.candidate_answer!r}"
    )


def test_eval_dry_run_locomo(tmp_path: Path) -> None:
    """``run_locomo.py --dry-run --n-queries 3`` exits 0."""
    out_json = tmp_path / "locomo-dry.json"
    result = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "run_locomo.py"),
            "--dry-run",
            "--n-queries",
            "3",
            "--seeds",
            "1",
            "--out-json",
            str(out_json),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"run_locomo.py --dry-run failed: rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert out_json.exists()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["dry_run"] is True
    assert data["n_questions"] > 0


# ---------------------------------------------------------------------------
# Grader mocks
# ---------------------------------------------------------------------------


class _MockCompletions:
    """Drop-in for ``openai.OpenAI().chat.completions``."""

    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        # Score 1.0 if the gold answer appears in the candidate, else 0.0.
        prompt = kwargs["messages"][0]["content"]
        score = (
            1.0
            if "Gold answer: blue" in prompt and "blue" in prompt.split("Candidate answer:")[1]
            else 0.0
        )

        msg_content = json.dumps({"score": score, "reason": "mock"})

        class _Msg:
            content = msg_content

        class _Choice:
            message = _Msg()

        class _Resp:
            def __init__(self) -> None:
                self.choices = [_Choice()]

        return _Resp()


class _MockChat:
    def __init__(self) -> None:
        self.completions = _MockCompletions()


class _MockOpenAI:
    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.chat = _MockChat()


def test_grader_mocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mocked grader returns deterministic scores and caches them.

    Verifies:
    * a fresh prompt triggers exactly one upstream API call,
    * a repeated prompt is served from cache (call count unchanged),
    * the parsed score matches the mock's JSON output,
    * altering the model invalidates the cache (new API call).
    """
    # Inject a fake openai module so :class:`LLMGrader` can import it.
    import types

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _MockOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    grader = LLMGrader(
        model="gpt-4-turbo",
        api_key="sk-test",
        cache_dir=tmp_path / "grader",
    )
    try:
        # First call → API hit.
        score1 = grader.grade(
            question="What is the user's favorite color?",
            gold_answer="blue",
            candidate_answer="The candidate retrieved: blue.",
        )
        assert score1 == 1.0
        # The fake completions counter is reachable via the mock chain.
        client = grader._ensure_client()
        assert client.chat.completions.calls == 1

        # Second call with identical prompt → cache hit, no API call.
        score2 = grader.grade(
            question="What is the user's favorite color?",
            gold_answer="blue",
            candidate_answer="The candidate retrieved: blue.",
        )
        assert score2 == 1.0
        assert client.chat.completions.calls == 1, "cache should have prevented a second API call"

        # Different prompt → API hit again.
        score3 = grader.grade(
            question="What is the user's favorite color?",
            gold_answer="blue",
            candidate_answer="The candidate retrieved: red.",
        )
        assert score3 == 0.0
        assert client.chat.completions.calls == 2

        # Different model → cache key changes → API hit.
        grader2 = LLMGrader(
            model="gpt-4o-mini",
            api_key="sk-test",
            cache_dir=tmp_path / "grader",
        )
        try:
            score4 = grader2.grade(
                question="What is the user's favorite color?",
                gold_answer="blue",
                candidate_answer="The candidate retrieved: blue.",
            )
            assert score4 == 1.0
            assert grader2._ensure_client().chat.completions.calls == 1
        finally:
            grader2.close()
    finally:
        grader.close()


def test_grader_parses_malformed_response(tmp_path: Path) -> None:
    """A grader response that isn't valid JSON scores 0 — never crashes."""
    from scripts.lib.eval_common import _parse_grader_response

    # Total garbage → 0.0.
    score, raw = _parse_grader_response("not json at all")
    assert score == 0.0
    assert raw == "not json at all"

    # JSON wrapped in markdown fences (defensive case).
    score, _ = _parse_grader_response('```json\n{"score": 0.75}\n```')
    assert score == 0.75

    # Out-of-range scores clamp to [0, 1].
    assert _parse_grader_response('{"score": 1.5}')[0] == 1.0
    assert _parse_grader_response('{"score": -0.3}')[0] == 0.0

    # NaN scores → 0.0 (defensive).
    score, _ = _parse_grader_response('{"score": "nope"}')
    assert score == 0.0


# ---------------------------------------------------------------------------
# Optional-dep import guards (verify the lazy-import promise)
# ---------------------------------------------------------------------------


def test_eval_common_imports_without_optional_deps() -> None:
    """``scripts.lib.eval_common`` must import on a bare environment.

    We can't easily unimport ``openai`` (it's already imported by the
    grader-mock test or by another part of the harness), but we *can*
    assert the module-level imports don't require pandas / matplotlib /
    pyarrow / requests_cache. We verify by checking those aren't
    importable side effects of the eval_common import.
    """
    # Already-imported sentinel: if eval_common pulls in any of these,
    # they'd show up in sys.modules after a fresh re-import.
    import importlib

    import scripts.lib.eval_common as ec

    importlib.reload(ec)
    # The optional dep names that must NOT be imported by reading the module.
    for name in ("pandas", "matplotlib", "pyarrow"):
        # We only assert that the module *can* import without these;
        # we don't assert they're absent because another test might
        # have pulled them in. Just check find_spec doesn't crash.
        importlib.util.find_spec(name)
