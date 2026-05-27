# Cross-adapter conformance suite

This suite parametrizes the SAME set of protocol scenarios across every
`MemoryStore` adapter that ships in `amp.store`. It is the "vendor
neutrality claim" evidence the paper refers to: 15 scenarios × 5
adapters = 75 cells, where every non-skipped cell must pass.

## What it tests

`scenarios.py` defines a frozen `ProtocolScenario` dataclass per AMP
wire-format invariant:

* `basic_remember_recall` — write a semantic fact, recall by paraphrase
* `remember_recall_by_user_filter` — `user_id` scoping isolates memories
* `type_filter` — `types=[SEMANTIC]` returns only semantic hits
* `forget_by_ids` — forgotten ids no longer recall
* `forget_no_scope_raises` — `forget()` with neither ids nor filter raises
  (spec §3.3 invariant)
* `expire_empty_policy_raises` / `expire_empty_policy_object_raises` —
  `expire()` with no policy raises (spec §3.5 — was a critical bug we fixed)
* `expire_by_age` — `older_than_days` removes backdated rows
* `merge_keep_canonical` — `KEEP_CANONICAL` collapses duplicates
* `approval_required_pending` — `approval_required=True` returns
  `pending_approval=True` and the row is not recallable
* `capabilities_declared` — `store.capabilities` is a non-empty set of
  recognised `Capability` constants
* `health_returns_status` — `health()` returns a dict with a `status` key
* `isinstance_protocol` — `isinstance(store, MemoryStore)` is True
* `recall_returns_score_metadata` — recall hits have populated score / type /
  content / source_store fields
* `fresher_than_days_filter` — `fresher_than_days` excludes backdated rows
* `multi_remember_then_recall` — bulk-write of 10 facts, recall returns
  at least one hit (soft threshold; see scenario docstring)

## Adapters covered

* `sqlite-vec` — the **REAL** reference adapter, in-memory SQLite + the
  sqlite-vec virtual table, with a deterministic sha256-based fake
  embedder so unit-test runs do not need sentence-transformers. This is
  the ground-truth implementation against which the others are compared.
* `mem0`, `letta`, `cognee`, `pgvector` — **MOCKED**. Each fixture builds
  a `MagicMock` / `AsyncMock` client that maintains a small in-memory
  store dict + token-overlap scoring stand-in for ANN search. The mocks
  do NOT pretend to be a full backend — they implement just enough
  surface for the protocol invariants to fire end-to-end, and the
  predicates check that the adapter's TRANSLATION layer (AMP request
  → backend call → AMP response) is correct.

## When a cell SKIPs

A `(scenario, adapter)` cell skips with a documented reason when:

1. The scenario declares `required_capabilities` the adapter does not
   include in its `.capabilities` set. Example: a graph-hop scenario
   would skip `mem0` (which doesn't declare `Capability.GRAPH`).
2. The adapter has a hard-coded override in `SKIP_OVERRIDES` because
   the backend's primitives can't honour the contract. Example: cognee's
   `forget()` only accepts data_id UUIDs, not the adapter-synthetic
   `cog:` ids minted at write time — so `forget_by_ids` is documented
   as a no-op skip.

## Adding a new adapter

1. Implement the `MemoryStore` Protocol in `src/amp/store/<your>_adapter.py`.
2. Add an `_build_<your>()` function in `conftest.py` that returns a
   ready-to-use store instance (mocking the backend where necessary).
3. Add the adapter id to `ADAPTER_IDS`.
4. If any scenario can't be satisfied for a documented reason, add
   an entry under `SKIP_OVERRIDES[<adapter>]`.

## Adding a new scenario

Append a `ProtocolScenario(...)` to `SCENARIOS` in `scenarios.py`. The
runner picks it up automatically. Predicates MUST be pure functions and
MUST NOT rely on wall-clock comparisons that don't account for the
explicit backdate markers seeded by setup requests.

## Running

```bash
.venv/Scripts/python.exe -m pytest tests/conformance/ -v
```

The matrix is summarised at the bottom of `docs/adapters.md`.
