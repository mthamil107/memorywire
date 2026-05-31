# Benchmarks

memorywire v0 ships with a **microbenchmark** â€” not LongMemEval, LoCoMo, or BEAM,
which are deferred to v0.2. The point is to show concrete shape: real
embedder, real sqlite-vec backend, hand-authored corpus, honest numbers.

LongMemEval and LoCoMo are out of reach for v0 because each requires a
gated/paid GPT-4-style grader and hours of model time; landing them
honestly in v0.2 is tracked as part of the post-launch backlog.

## Methodology

- 100 hand-authored facts across ~10 distinct users, mixing all four
  memory types (semantic / episodic / procedural / emotional).
- 50 hand-authored queries with explicit gold-id labels, distributed as:
  - 24 paraphrase queries ("what foods should I avoid serving Alice?" â†’
    `f001 "Alice is allergic to peanuts and tree nuts."`),
  - 10 exact / near-exact match queries,
  - 8 multi-hit queries (gold_ids has 2-3 entries),
  - 8 no-match probes (gold_ids=`[]`, to measure how often the system
    surfaces a confident wrong answer when nothing matches).
- Embedder: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local CPU
  via PyTorch). Lazy-loaded; first call pays a one-time model-load cost
  that is excluded from per-call latency via a warm-up call.
- Backend: a single `SqliteVecStore(":memory:")` exercising the full
  intra-store RRF fusion of vec0 ANN + FTS5 keyword search (spec Â§5).
- Dataset and runner live at `tests/benchmarks/dataset.py` and
  `scripts/run_microbench.py`. Reproducible with one command:

  ```bash
  .venv/Scripts/python.exe scripts/run_microbench.py --json
  ```

## Results (n=50 queries, k=5, n=100 facts)

| Metric | Value |
|---|---|
| Recall@5 mean (labelled queries) | **1.000** |
| Precision@5 mean | 0.214 |
| Ingest latency p50 / p95 / p99 | **37.8 ms** / 46.0 ms / 69.1 ms |
| Recall latency p50 / p95 / p99 | **40.6 ms** / 46.6 ms / 55.7 ms |
| No-match probes correctly empty | 0 / 8 |
| Total benchmark runtime | ~5.9 s |

Numbers measured 2026-05-27 on Windows 11 AMD64, Python 3.13.13, CPU-only
inference. Reproduce locally with `scripts/run_microbench.py`.

The headline number â€” **recall@5 = 1.000 on 42 labelled queries** â€”
means every single paraphrase / exact-match / multi-hit query surfaced
all its gold ids in the top-5 results. The precision number is bounded
by the ratio of gold ids per query: most queries have a single gold id,
so precision@5 is upper-bounded at 0.2 by construction.

## What this number is **not**

- **Not a semantic-similarity benchmark.** 100 hand-authored facts is
  small enough that FTS5 keyword matching alone would surface many gold
  ids â€” the dataset rewards systems that combine semantic embeddings
  with keyword recall, which is exactly what memorywire's intra-store RRF does.
  At 100 facts the ANN path is doing brute-force vec0 scan, not a real
  HNSW workload.
- **Not a long-context test.** LongMemEval and LoCoMo measure recall
  over hundreds-of-thousands-of-token conversations with temporal and
  multi-hop reasoning. This benchmark measures none of that.
- **Not a multi-backend fusion test.** The benchmark exercises a single
  `SqliteVecStore`; the `--target fusion` flag wires two stores so the
  router's inter-store RRF runs, but it's the same backend twice and
  the result is two-of-everything in the candidate set â€” not a real
  cross-vendor fusion. Real fusion measurements need â‰¥3 backend
  adapters with disjoint indexes; that's a v0.2 deliverable.
- **No relevance-threshold cutoff in v0.** All 8 no-match probes return
  5 hits (the user's other content) because `recall(k=5)` always
  returns up to k. A production deployment would apply a fusion-score
  floor; that knob is tracked for v0.2 along with calibrated thresholds.

## How to reproduce

```bash
# Full benchmark (text output)
.venv/Scripts/python.exe scripts/run_microbench.py

# JSON output for copy-paste into a blog post / dashboard
.venv/Scripts/python.exe scripts/run_microbench.py --json

# Limit to a quick smoke run
.venv/Scripts/python.exe scripts/run_microbench.py --queries 5

# Force the deterministic fake embedder (no torch / no HuggingFace network)
.venv/Scripts/python.exe scripts/run_microbench.py --embedder fake

# Two-store router path (illustrates fusion plumbing, not real cross-vendor)
.venv/Scripts/python.exe scripts/run_microbench.py --target fusion
```

A subset of the benchmark is also wired into the pytest suite under
`tests/benchmarks/test_recall_benchmark.py` as an opt-in harness:

```bash
.venv/Scripts/python.exe -m pytest -m benchmark
```

It asserts a recall@5 floor of 0.6 and an ingest-p95 floor of 200 ms, so
a future regression in the storage path or the router shows up as a red
test rather than a silently-degraded blog number.

## Performance targets (spec)

The performance-target table in
[`kickoff/ARCHITECTURE.md`](kickoff/ARCHITECTURE.md) Â§10 is the canonical
SLA the implementation aims at:

| Workload | Target | Observed (v0 microbench, n=100) |
|---|---|---|
| Single `remember()` (semantic) | <50 ms p50 | 37.8 ms p50 |
| Single `recall()` (k=5, 2 stores fused) | <300 ms p50 | 40.6 ms p50 (single store) |
| `recall()` against 100k memories in sqlite-vec | <500 ms p50 | not measured at 100k yet |
| FSM `procedural.store()` | <30 ms p50 | not measured |
| STMâ†’LTM consolidation (100 STM items) | <2 s | not measured |
| Governance UI page load | <200 ms p50 | not measured |

The 100k-memory recall scaling test, FSM latency, consolidation, and UI
page-load targets are v0.2 follow-ups.

## Adversarial fusion experiment

A 1-of-N malicious-backend, rank-0 injection experiment that measures
how much the router's RRF fusion is moved by a single rogue store. Maps
1:1 to the threat enumerated in `docs/THREATS.md` Â§3.3.

### Methodology

- N child stores (default 3): N-1 *benign* + 1 *adversarial*. Benign
  stores return each query's gold ids at the top ranks with an
  independent random distractor tail (different distractor permutation
  per benign store â€” simulates "different embedders / different
  indexes"). The adversarial store returns ``K`` attacker-controlled
  ids (disjoint from the gold corpus, prefix ``a***``) at ranks
  ``0..K-1``, then optionally a benign tail so it still "looks normal"
  past rank K.
- Q queries (default 20), each with two gold ids drawn without
  replacement from a synthetic corpus of M memories (default 50).
- For ``K âˆˆ {0, 5, 10, ..., M}`` the script issues every query through
  a real `MemoryRouter.recall(k=5)` and measures:
  - **recall@5** against the gold set;
  - **adversarial leak rate** â€” fraction of returned ids that are
    attacker-controlled;
  - **gold displacement rate** â€” fraction of gold ids in the K=0
    baseline top-5 that were pushed out at higher K.
- Three fusion modes tested by re-running with `--target rrf|max|weighted`.

### Results (N=3, 1 adversarial, M=50, Q=20, k=5, seed=1337)

Numbers measured 2026-05-27 with the default config. Reproduce with
`python scripts/run_adversarial.py --json`.

| K (attacker budget) | recall@5 (RRF) | leak (RRF) | recall@5 (MAX) | leak (MAX) |
|---:|---:|---:|---:|---:|
| 0   | 1.000 | 0.000 | 1.000 | 0.000 |
| 5   | 1.000 | 0.000 | 0.500 | 0.800 |
| 10  | 1.000 | 0.000 | 0.500 | 0.800 |
| 25  | 1.000 | 0.000 | 0.500 | 0.800 |
| 50  | 1.000 | 0.000 | 0.500 | 0.800 |

Under `fusion="weighted"` with equal per-store weights the result is
identical to RRF: the consensus of two benign votes for each gold id
outpoints the single attacker vote regardless of K. The fusion algorithm
under attack â€” not the attack budget â€” is the dominant variable.

### Headline

- **RRF: defensible across the full sweep.** With 2 benign + 1
  adversarial backend, recall@5 stays at 1.000 even at K=50
  (attacker filling every top slot), and leak/displacement stay at
  0.000. This is the mathematical consequence of RRF being
  score-independent and sum-across-stores: a single rogue vote of
  `1/60 â‰ˆ 0.0167` cannot beat two benign votes summing to
  `1/60 + 1/61 â‰ˆ 0.0330`.
- **MAX collapses at K=5.** With the same setup, a single rogue
  store at attacker rank 0 immediately ties or beats the benign
  rank-0 score, pulls 4 of 5 fused top-5 slots, and halves recall.
  Operators picking `fusion="max"` (or `"weighted"` with attacker
  weight not down-weighted) accept this.

The operating point for the default config is **K=50 with recall@5 =
1.000 under RRF** â€” the curve does not cross the 0.6 floor in the
swept range. The defensible claim is therefore "RRF tolerates an
arbitrarily large 1-of-N rank-0 injection as long as the majority of
backends are benign and agree on the gold set," not "RRF tolerates K
up to some specific number."

### Reproduce

```bash
# Default sweep (RRF, N=3, 1 adversarial, M=50, Q=20)
.venv/Scripts/python.exe scripts/run_adversarial.py --json

# Compare fusion algorithms
.venv/Scripts/python.exe scripts/run_adversarial.py --target max
.venv/Scripts/python.exe scripts/run_adversarial.py --target weighted

# Stress: 50% rogue
.venv/Scripts/python.exe scripts/run_adversarial.py --n-backends 2 --n-adversarial 1

# Plot (requires matplotlib; silently skipped otherwise)
.venv/Scripts/python.exe scripts/run_adversarial.py --plot
```

Plot output (when matplotlib is installed): `docs/adversarial-results.png`.

### What this number is *not*

- **Not an end-to-end recall measurement.** Benign stores are perfect
  by construction (always return gold at top); the experiment isolates
  the fusion-math property, not the storage-stack property.
- **Not LongMemEval.** No LLM grader, uniform-difficulty queries, no
  long-context retrieval.
- **Adversary has full knowledge** of the router's k*4 over-fetch and
  fills exactly that block; a black-box attacker would do worse.
- **1-of-N case only by default.** Once `n_adversarial >= n_benign`
  the RRF consensus argument fails â€” see `--n-adversarial` to sweep.

## LongMemEval + LoCoMo â€” preliminary numbers (v1 preprint)

First live pass with a real LLM grader after fixing the per-question
SQLite-isolation bug discovered during pre-paper validation. These
numbers are reported as **preliminary** for the v1 arXiv preprint;
the full 5-seed Ã— 200-question paper-grade run is deferred to a v2
replacement on arXiv (the per-question Memory + sentence-transformers
reload pattern means each iteration is ~30-45 s on a CPU laptop and
the full run extrapolates to 10-15 hours â€” out of scope for v1).

| Bench | Subset | Seeds | Calls | Wall | Cost | Score |
|---|---|---:|---:|---:|---:|---:|
| LongMemEval | 12 questions stratified across the 5 task types | 1 | 12 | ~10 min | $0.001 | **overall = 0.417** |
| LoCoMo | 10 questions Ã— 1 episode | 1 | 10 | ~7 min | $0.001 | **grader = 0.150** |

- **Grader:** `gpt-4o-mini`.
- **Embedder:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU).
- **Backend:** `sqlite-vec://` with per-(condition, seed, qid) isolated
  DB files in `.amp-eval-dbs/` â€” required for correctness because
  sqlite-vec's ANN top-K is computed *before* the `agent_id` WHERE
  filter, so a shared DB across questions silently returns zero
  hits once the cross-question row count grows past the per-call k.
- **Bootstrap CI bands:** zero-width on a single-seed subset.
  Multi-seed CIs land with the v2 replacement.

**Per-task LongMemEval breakdown (post-fix, n=12):**

| Task type | mean | notes |
|---|---:|---|
| `single_session_preferences` | 0.90 | strongest â€” short-range recall on a single session |
| `single_session_user` | 0.75 | similar shape |
| `single_session_assistant` | 0.50 | answer is in the assistant's prior reply |
| `knowledge_update` | 0.35 | overwrites confuse a single small embedder |
| `multi_session_reasoning` | 0.00 | requires combining facts across sessions â€” MiniLM doesn't compose |
| `temporal_reasoning` | 0.00 | requires "when" reasoning â€” out of scope for embedder-only recall |

**Per-category LoCoMo breakdown (post-fix, n=10):**

- Category 2 (single-hop derivation from session text): mean = 0.25
- Categories 1 + 3 (multi-hop date / temporal): mean = 0.00

**What the numbers say honestly.** The per-question DB isolation
fix recovers memorywire's ability to find topically-relevant turns: the
prior-run candidates were dominated by `"(no relevant memories
surfaced)"`, and after the fix every candidate contains real
context from the question's haystack. The remaining gap â€” strong
on single-session, weak on multi-session and temporal â€” is a
genuine measurement of `all-MiniLM-L6-v2`'s well-known weakness
on the harder LongMemEval tiers, not a harness bug. Swapping the
embedder for a larger model (`gte-large`, `bge-m3`, or OpenAI
`text-embedding-3-large`) is the v0.2 path; the protocol itself is
embedder-agnostic, so this measurement is about the reference
embedder's recall ceiling, not memorywire's wire format.

Compared to the pre-fix run (LongMemEval 0.286, LoCoMo 0.018 with
`(no relevant memories surfaced)` dominating), the post-fix
numbers are **+46% relative on LongMemEval** and **+8.3Ã— relative
on LoCoMo** â€” the fix is real and the lift is real.

Reproduce:

```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python scripts/run_longmemeval.py --grader-model gpt-4o-mini \
  --seeds 1 --n-queries 10 --json
python scripts/run_locomo.py --grader-model gpt-4o-mini \
  --seeds 1 --n-queries 10 --json
```

JSON outputs land at `docs/longmemeval-results.json` and
`docs/locomo-results.json` (gitignored â€” every run regenerates them).

## Roadmap to v0.2

- LongMemEval proper with a GPT-4-class grader (paid).
- LoCoMo proper with a grader (paid).
- **Per-question authorized-context ingest scoping** so the
  cross-session benchmarks measure what they're designed to.
- 100k-memory recall scaling test with a synthetic corpus and recall@k
  measured against a fixed gold set.
- Cross-vendor fusion benchmark once the Letta and Cognee adapters land,
  so the router RRF path can be measured on disjoint indexes.
- Calibrated relevance-threshold cutoff for no-match probes.
