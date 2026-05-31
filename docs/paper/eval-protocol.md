# Eval protocol (paper Ã‚Â§5)

This document is the canonical methodology reference cited from paper
Ã‚Â§5. It explains *exactly* how memorywire's LongMemEval / LoCoMo / BEAM numbers
are produced: which datasets, how many seeds, what grader, what
statistical machinery, and what we deliberately don't claim. Reviewers
should be able to reproduce every published number end-to-end from
this page alone, given an OpenAI API key.

## Datasets

We evaluate memorywire on three canonical agent-memory benchmarks:

1. **LongMemEval** (Wu et al., 2024) Ã¢â‚¬â€ five task types over long
   chat histories:
   single-session-preferences, multi-session-reasoning,
   knowledge-update, temporal-reasoning, information-extraction. We
   load the upstream JSON dump (`longmemeval_s.json` / `_m.json` /
   `_oracle.json`) and normalise it to a uniform per-question struct.
   Source: <https://github.com/xiaowu0162/LongMemEval>.
2. **LoCoMo** (Maharana et al., 2024) Ã¢â‚¬â€ multi-session conversational
   episodes with QA pairs spanning the conversation. We report both a
   GPT-4 grader score (the headline) and a sentence-BLEU-4 score
   (cheap reference-anchored sanity check). Source:
   <https://github.com/snap-research/locomo>.
3. **BEAM** Ã¢â‚¬â€ covered by the same machinery but currently gated by
   dataset availability; the harness's loader is dataset-agnostic and
   will pick BEAM up automatically once the manifest lands in
   `~/.cache/amp/beam/`.

Datasets stage under `~/.cache/amp/<dataset>/` and are fetched with
`--download` (HuggingFace Hub first, `git clone` fallback). Reruns are
free: the harness detects the cache and skips fetching.

## memorywire configuration

For every benchmark, the eval loop drives the public
`memorywire.api.Memory` facade Ã¢â‚¬â€ the same surface a downstream user gets
from `pip install memorywire`. Each session turn becomes
one `Memory.remember(...)` call (typed `EPISODIC` with `session_id`
and `turn_ix` metadata); each test question becomes one
`Memory.recall(query, k=5)` call. The retrieved hits form the grader
context. We do **not** call any LLM to "synthesize an answer" from
the retrieved memories Ã¢â‚¬â€ the grader sees the retrieved snippets and
judges whether the right facts surfaced. This makes the eval a clean
retrieval-quality measurement, not a generation-polish measurement,
and removes generator-LLM variance from the headline number.

Conditions are passed via `--stores STORE1,STORE2,...`. The first
URL is the **baseline** (treated as the reference for all paired
comparisons); subsequent URLs are memorywire variants under test. Typical
configurations we report:

| Condition | URL |
|---|---|
| `sqlite-vec-only` (baseline) | `sqlite-vec://./eval.db` |
| `mem0-only` | `mem0://default` |
| `letta-only` | `letta://localhost:8283` |
| `pgvector-only` | `pgvector://default` |
| `amp-fusion-2x` | (router with two backends) |

The "fusion" condition exercises the inter-store RRF path. It is
reported separately from the per-backend baselines so the paper can
claim *fusion vs single-best-backend*, not *fusion vs arbitrary
single-backend*.

## Seeds, bootstrap, and correction

* **Seeds: n = 5.** Each seed re-initialises the `agent_id` and the
  per-condition RNG. We use a small n because each seed is expensive
  (full grader pass over the dataset); n = 5 is the lower bound
  recommended for the paired-bootstrap CI to be meaningful at
  10 000 resamples.
* **Paired bootstrap: n = 10 000 resamples.** We compute the 95% CI
  on the *paired difference* between conditions (same (question, seed)
  pair across both conditions) using the stdlib implementation in
  `scripts/lib/eval_common.py:paired_bootstrap_ci`. The bootstrap is
  on the linear difference of paired observations Ã¢â‚¬â€ mathematically
  equivalent to resampling rows and recomputing the difference of
  means Ã¢â‚¬â€ so it composes cleanly with task-type slicing.
* **Holm-Bonferroni correction.** Each memorywire-variant-vs-baseline
  comparison generates a family of p-values: one overall plus one per
  task type (5 for LongMemEval, ~5 for LoCoMo categories). We correct
  the family with Holm's step-down procedure (Holm 1979) at ÃŽÂ± = 0.05.
  We report *both* the raw p-value and the post-correction
  rejection decision, so a reviewer can verify the correction was
  honest. Implementation: `holm_bonferroni` in `eval_common.py`.

We choose Holm over plain Bonferroni because Holm is uniformly more
powerful (it rejects everything Bonferroni rejects, plus more) and
preserves FWER (family-wise error rate) at the same ÃŽÂ±.

## Grader

* **Default model: `gpt-4-turbo`.** Swappable via `--grader-model`.
  The harness clamps grader output to a `{"score": 0.0..1.0,
  "reason": "..."}` JSON shape via the `response_format=json_object`
  parameter on OpenAI's chat-completions API; malformed responses
  score 0 (defensive Ã¢â‚¬â€ we'd rather under-credit a parse failure than
  crash a 1000-question eval).
* **Temperature 0.0.** Deterministic-ish for grader reproducibility.
* **Caching by `sha256(model || prompt)`.** A cache hit costs zero
  API time. The cache is sqlite (via `requests-cache`) when available,
  otherwise stdlib `shelve`. Cache lives under
  `~/.cache/amp/grader/`. Swapping the model or the prompt template
  invalidates the cache automatically Ã¢â‚¬â€ both are part of the cache
  key.
* **Retry policy:** exponential backoff with jitter on 429 / 5xx,
  up to 4 attempts; other HTTP errors fail fast.

## Cost / time estimates

Pre-run cost estimation is printed before kickoff so the user can
Ctrl-C if the bill is unacceptable. The harness uses these
per-1k-token rates (USD, 2026-Q2):

| Model | Input | Output |
|---|---|---|
| `gpt-4-turbo` | $0.010 | $0.030 |
| `gpt-4o` | $0.005 | $0.015 |
| `gpt-4o-mini` | $0.00015 | $0.0006 |
| `gpt-4.1` | $0.002 | $0.008 |

Token estimates per call: LongMemEval Ã¢â€°Ë† 600 input / 80 output,
LoCoMo Ã¢â€°Ë† 900 input / 100 output (LoCoMo prompts carry more session
context).

For 5 seeds Ãƒâ€” 200 questions Ãƒâ€” 1 condition (baseline only):

| Dataset | Grader calls | `gpt-4-turbo` | `gpt-4o-mini` |
|---|---:|---:|---:|
| LongMemEval | 1 000 | Ã¢â€°Ë† $8.40 | Ã¢â€°Ë† $0.14 |
| LoCoMo | 1 000 | Ã¢â€°Ë† $12.00 | Ã¢â€°Ë† $0.19 |

Multiply by the number of conditions; subtract any cache hits. A
representative full paper-Ã‚Â§5 run (3 conditions Ãƒâ€” 2 datasets) at
`gpt-4-turbo` is **~$60-$70**; at `gpt-4o-mini` it is **~$1**.
Cached reruns are free.

Wall-clock for a full run is dominated by the grader API roundtrips;
expect 1-3 hours per dataset at `gpt-4-turbo` (rate-limit bound), or
20-40 minutes at `gpt-4o-mini`. memorywire's recall path itself runs at
40-100 ms p50 so the in-process side of the loop is negligible.

## Honest framing

* **Grader-based eval has its own biases.** GPT-4-turbo is the
  benchmarks' canonical grader, but it sometimes credits hallucinated
  content that "sounds right" or under-credits a correct-but-laconic
  candidate. We report *mean Ã‚Â± 95% CI*, not point estimates, and
  publish per-question grader transcripts in the JSON output so
  reviewers can audit.
* **The candidate is the retrieval output, not a generation.** We
  measure whether the right facts surfaced; we do not measure how
  well a downstream LLM stitches them into prose. That is a separate
  experiment we defer to a future paper.
* **5 seeds is small.** We chose 5 to fit the grader budget, not
  because more seeds aren't valuable. The 10 000-resample bootstrap
  partially mitigates the small-n by enriching the difference
  distribution, but a reader who cares about microscopic effect
  sizes should run more seeds.
* **No claim of LongMemEval / LoCoMo SoTA.** We claim memorywire's
  *protocol* and *router* are usable on these workloads and that
  fusion provides a measurable lift over single-backend baselines.
  Where memorywire is below SoTA on a sub-task we report that openly.
* **Cache reproducibility.** The grader cache is shipped with the
  paper's artifact. Running the harness against the cached
  prompts/responses reproduces every number in the paper without
  any further API spend.

## Reproducing the headline numbers

```bash
# One-time dataset fetch (HF Hub then git fallback)
python scripts/run_longmemeval.py --download --dry-run
python scripts/run_locomo.py --download --dry-run

# Verify the harness wiring without burning API budget
python scripts/run_longmemeval.py --dry-run --n-queries 3
python scripts/run_locomo.py --dry-run --n-queries 3

# Full run (Ã¢â€°Ë† 1-3 hours, Ã¢â€°Ë† $20 per dataset at gpt-4-turbo)
export OPENAI_API_KEY=sk-...
python scripts/run_longmemeval.py --seeds 5 --n-queries 200 \
    --stores sqlite-vec://./lme.db
python scripts/run_locomo.py --seeds 5 --n-queries 200 \
    --stores sqlite-vec://./locomo.db
```

The full set of JSON / CSV / PNG outputs lands under `docs/`. The
test suite at `tests/benchmarks/test_eval_harness.py` exercises the
statistical primitives and the dry-run pipeline; pass `-m benchmark`
to run them.

## References

* Wu et al. (2024). *LongMemEval: Benchmarking Chat Assistants on
  Long-Term Interactive Memory*.
  <https://github.com/xiaowu0162/LongMemEval>.
* Maharana et al. (2024). *Evaluating Very Long-Term Conversational
  Memory of LLM Agents (LoCoMo)*.
  <https://github.com/snap-research/locomo>.
* Holm, S. (1979). A Simple Sequentially Rejective Multiple Test
  Procedure. *Scand. J. Statist.* 6: 65-70.
* Efron, B. & Tibshirani, R. (1993). *An Introduction to the
  Bootstrap.* Chapman & Hall.
* Hesterberg, T. (2015). What Teachers Should Know About the
  Bootstrap. *The American Statistician* 69(4): 371-386.
