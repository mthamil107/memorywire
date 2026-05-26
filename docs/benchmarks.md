# Benchmarks

> **WIP** — first numbers land in Phase 5 / launch week.

AMP measures itself against three existing memory benchmarks rather than
inventing a new one:

| Benchmark | What it measures | Where |
|---|---|---|
| **LongMemEval** | Long-term memory recall across multi-turn conversations | upstream paper |
| **LoCoMo** | Long-context memory over realistic chat logs | upstream paper |
| **BEAM** | Behavior-aware agent memory | upstream paper |

Performance targets for the reference implementation (from
[`kickoff/ARCHITECTURE.md`](kickoff/ARCHITECTURE.md) §10):

| Workload | Target |
|---|---|
| Single `remember()` (semantic) | <50 ms p50 |
| Single `recall()` (k=5, 2 stores fused) | <300 ms p50 |
| `recall()` against 100k memories in sqlite-vec | <500 ms p50 |
| FSM `procedural.store()` | <30 ms p50 |
| STM→LTM consolidation (100 STM items) | <2 s |
| Governance UI page load | <200 ms p50 |

Benchmark runners live in `tests/benchmarks/` and use `pytest-benchmark`.
