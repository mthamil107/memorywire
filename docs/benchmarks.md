# Benchmarks

AMP v0 ships with a **microbenchmark** — not LongMemEval, LoCoMo, or BEAM,
which are deferred to v0.2. The point is to show concrete shape: real
embedder, real sqlite-vec backend, hand-authored corpus, honest numbers.

LongMemEval and LoCoMo are out of reach for v0 because each requires a
gated/paid GPT-4-style grader and hours of model time; landing them
honestly in v0.2 is tracked as part of the post-launch backlog.

## Methodology

- 100 hand-authored facts across ~10 distinct users, mixing all four
  memory types (semantic / episodic / procedural / emotional).
- 50 hand-authored queries with explicit gold-id labels, distributed as:
  - 24 paraphrase queries ("what foods should I avoid serving Alice?" →
    `f001 "Alice is allergic to peanuts and tree nuts."`),
  - 10 exact / near-exact match queries,
  - 8 multi-hit queries (gold_ids has 2-3 entries),
  - 8 no-match probes (gold_ids=`[]`, to measure how often the system
    surfaces a confident wrong answer when nothing matches).
- Embedder: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local CPU
  via PyTorch). Lazy-loaded; first call pays a one-time model-load cost
  that is excluded from per-call latency via a warm-up call.
- Backend: a single `SqliteVecStore(":memory:")` exercising the full
  intra-store RRF fusion of vec0 ANN + FTS5 keyword search (spec §5).
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

The headline number — **recall@5 = 1.000 on 42 labelled queries** —
means every single paraphrase / exact-match / multi-hit query surfaced
all its gold ids in the top-5 results. The precision number is bounded
by the ratio of gold ids per query: most queries have a single gold id,
so precision@5 is upper-bounded at 0.2 by construction.

## What this number is **not**

- **Not a semantic-similarity benchmark.** 100 hand-authored facts is
  small enough that FTS5 keyword matching alone would surface many gold
  ids — the dataset rewards systems that combine semantic embeddings
  with keyword recall, which is exactly what AMP's intra-store RRF does.
  At 100 facts the ANN path is doing brute-force vec0 scan, not a real
  HNSW workload.
- **Not a long-context test.** LongMemEval and LoCoMo measure recall
  over hundreds-of-thousands-of-token conversations with temporal and
  multi-hop reasoning. This benchmark measures none of that.
- **Not a multi-backend fusion test.** The benchmark exercises a single
  `SqliteVecStore`; the `--target fusion` flag wires two stores so the
  router's inter-store RRF runs, but it's the same backend twice and
  the result is two-of-everything in the candidate set — not a real
  cross-vendor fusion. Real fusion measurements need ≥3 backend
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
[`kickoff/ARCHITECTURE.md`](kickoff/ARCHITECTURE.md) §10 is the canonical
SLA the implementation aims at:

| Workload | Target | Observed (v0 microbench, n=100) |
|---|---|---|
| Single `remember()` (semantic) | <50 ms p50 | 37.8 ms p50 |
| Single `recall()` (k=5, 2 stores fused) | <300 ms p50 | 40.6 ms p50 (single store) |
| `recall()` against 100k memories in sqlite-vec | <500 ms p50 | not measured at 100k yet |
| FSM `procedural.store()` | <30 ms p50 | not measured |
| STM→LTM consolidation (100 STM items) | <2 s | not measured |
| Governance UI page load | <200 ms p50 | not measured |

The 100k-memory recall scaling test, FSM latency, consolidation, and UI
page-load targets are v0.2 follow-ups.

## Roadmap to v0.2

- LongMemEval proper with a GPT-4-class grader (paid).
- LoCoMo proper with a grader (paid).
- 100k-memory recall scaling test with a synthetic corpus and recall@k
  measured against a fixed gold set.
- Cross-vendor fusion benchmark once the Letta and Cognee adapters land,
  so the router RRF path can be measured on disjoint indexes.
- Calibrated relevance-threshold cutoff for no-match probes.
