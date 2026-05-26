# AMP — Architecture

**Generated:** 2026-05-26 · **Status:** locked for v0 sprint. Re-litigate only with a measurement that contradicts the table at the bottom.

---

## 1. Stack decisions (locked)

| Concern | Choice | Why |
|---|---|---|
| **Language** | Python 3.11+ | Async-first, dominant in agent / memory ecosystem, all target adapters (mem0, Letta, Cognee) are Python |
| **Build tool** | `uv` for dev/lock/install | Passed Poetry on PyPI downloads in 2026; 10-100× faster |
| **Build backend** | `hatchling` (PEP 517) | Most stable; what FastAPI / Pydantic / Polars use |
| **Versioning** | `hatch-vcs` from git tags | Single source of truth |
| **Spec format** | JSON Schema Draft 2020-12 | Standard for cross-language schemas; tooling mature |
| **Spec doc format** | Markdown with embedded schemas | Same approach MCP took; easy to PR upstream |
| **License** | Apache-2.0 (protocol + reference impl) | More permissive than MIT for protocols; allows trademark protection |
| **CI** | GitHub Actions, multi-OS matrix | Standard 2026 baseline |
| **Lint / type / format** | `ruff` (lint + format) + `mypy --strict` + `pre-commit` | Standard |
| **Async** | native `asyncio`; expose sync wrappers via `asgiref` | Memory operations are I/O-heavy |
| **FSM library** | `pytransitions` | Mature, well-maintained Python FSM; simpler than XState ports |
| **Memory-router fusion** | RRF (k=60) + optional 1-hop graph boost | Same recipe as Graphiti, Mem0, Elastic |
| **Governance UI** | HTMX + Tailwind, Starlette server | Ship fast; switch to Next.js only when v1 demands richer interaction |
| **Telemetry** | OPT-IN only, never opt-out | Air-gap-friendly default |
| **Docs** | MkDocs Material + mkdocstrings | Standard for Python OSS |
| **Release** | `release-please` + PyPI OIDC trusted publisher | Replaces semantic-release |

### `pyproject.toml` skeleton

```toml
[build-system]
requires = ["hatchling>=1.27", "hatch-vcs>=0.4"]
build-backend = "hatchling.build"

[project]
name = "agent-memory-protocol"
description = "Vendor-neutral protocol and reference implementation for agent memory operations"
readme = "README.md"
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
requires-python = ">=3.11"
dynamic = ["version"]
dependencies = [
  "pydantic>=2.7",
  "jsonschema>=4.21",
  "pytransitions>=0.9",
  "typing-extensions>=4.10",
  "anyio>=4.3",
]

[project.optional-dependencies]
sqlite-vec = ["sqlite-vec>=0.1.9"]
mem0       = ["mem0ai>=0.1"]
letta      = ["letta-client>=0.5"]
cognee     = ["cognee>=0.2"]
postgres   = ["asyncpg>=0.29", "pgvector>=0.3"]
ui         = ["starlette>=0.37", "uvicorn>=0.30", "jinja2>=3.1"]
all        = ["agent-memory-protocol[sqlite-vec,mem0,letta,cognee,postgres,ui]"]

[project.scripts]
amp = "amp.cli:main"

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.targets.wheel]
packages = ["src/amp"]

[tool.uv]
dev-dependencies = [
  "pytest>=8.2", "pytest-cov>=5.0", "pytest-asyncio>=0.23",
  "pytest-benchmark>=4.0", "ruff>=0.5", "mypy>=1.10",
  "mkdocs-material>=9.5", "mkdocstrings[python]>=0.25",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
  "integration: tests that require a real backend",
  "slow: tests over 1s",
]
```

---

## 2. Directory tree

```
agent-memory-protocol/
├── README.md, LICENSE, NOTICE, CHANGELOG.md
├── CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md
├── pyproject.toml, uv.lock
├── .github/workflows/{ci,wheels,release,docs}.yml
│
├── docs/
│   ├── index.md
│   ├── getting-started.md
│   ├── spec/
│   │   └── v0.md                    # the published AMP spec
│   ├── adapters.md                  # how to write a new MemoryStore adapter
│   ├── governance-ui.md
│   └── benchmarks.md                # LongMemEval / LoCoMo / BEAM results
│
├── src/
│   └── amp/
│       ├── __init__.py
│       ├── api.py                   # public surface — Memory class
│       ├── models.py                # pydantic schemas matching the spec
│       ├── schemas/                 # JSON Schema files
│       │   ├── operations/
│       │   │   ├── remember.json
│       │   │   ├── recall.json
│       │   │   ├── forget.json
│       │   │   ├── merge.json
│       │   │   └── expire.json
│       │   └── types/
│       │       ├── semantic.json
│       │       ├── episodic.json
│       │       ├── procedural.json
│       │       └── emotional.json
│       ├── store/
│       │   ├── base.py              # MemoryStore Protocol class
│       │   ├── sqlite_vec.py
│       │   ├── mem0_adapter.py
│       │   ├── letta_adapter.py
│       │   ├── cognee_adapter.py
│       │   └── pgvector_adapter.py
│       ├── router.py                # memory-router (fan + RRF fuse)
│       ├── procedural.py            # FSM backend via pytransitions
│       ├── transformer.py           # STM<->LTM consolidator (async background)
│       ├── governance/              # diff/approve, health, audit
│       │   ├── diff.py
│       │   ├── health.py
│       │   └── audit.py
│       └── cli.py
│
├── ui/                              # governance UI (separate sub-package)
│   ├── pyproject.toml
│   ├── src/amp_ui/
│   │   ├── app.py                   # Starlette + HTMX
│   │   ├── routes/
│   │   ├── templates/
│   │   └── static/
│   └── tests/
│
├── examples/
│   ├── 01_quickstart.py             # end-to-end one-page demo
│   ├── 02_multi_backend.py
│   ├── 03_procedural_fsm.py
│   └── 04_governance_ui.py
│
├── tests/
│   ├── unit/                        # mocks, no real backends, <2s total
│   ├── integration/                 # real backends, <60s
│   └── benchmarks/                  # LongMemEval / LoCoMo runners
│
└── scripts/
    ├── run_benchmarks.py
    └── verify_spec.py               # JSON-Schema-validate examples
```

---

## 3. Storage schema (SQLite reference)

For backends that don't have native schemas (sqlite-vec, Postgres), the AMP reference schema:

```sql
-- Memories: the primary table. Type-tagged.
CREATE TABLE memories (
  id           TEXT PRIMARY KEY,        -- uuid v7
  agent_id     TEXT NOT NULL,
  user_id      TEXT,
  type         TEXT NOT NULL CHECK (type IN ('semantic','episodic','procedural','emotional')),
  content      TEXT NOT NULL,
  metadata     TEXT,                    -- JSON blob
  confidence   REAL DEFAULT 1.0,
  source       TEXT,                    -- which call/episode produced it
  created_at   INTEGER NOT NULL,        -- unix epoch ms
  updated_at   INTEGER NOT NULL,
  expires_at   INTEGER,                 -- optional TTL
  deleted_at   INTEGER                  -- soft delete for governance audit
);
CREATE INDEX idx_memories_agent ON memories(agent_id, type);
CREATE INDEX idx_memories_user ON memories(user_id);
CREATE INDEX idx_memories_created ON memories(created_at);

-- Embeddings: separate vec0 virtual table for ANN search
CREATE VIRTUAL TABLE memories_vec USING vec0(embedding float[768]);

-- FTS5: keyword search over content
CREATE VIRTUAL TABLE memories_fts USING fts5(content, content='memories', content_rowid='rowid');

-- Procedures: FSM state machines, JSON-serialized
CREATE TABLE procedures (
  id           TEXT PRIMARY KEY,
  agent_id     TEXT NOT NULL,
  name         TEXT NOT NULL,
  states       TEXT NOT NULL,           -- JSON: pytransitions state machine
  current      TEXT,                    -- current state
  metadata     TEXT,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);

-- Episodes: bounded sequences of memories
CREATE TABLE episodes (
  id           TEXT PRIMARY KEY,
  agent_id     TEXT NOT NULL,
  title        TEXT,
  started_at   INTEGER NOT NULL,
  ended_at     INTEGER,
  memory_ids   TEXT NOT NULL            -- JSON array of memory.id
);

-- Audit log: every operation, append-only
CREATE TABLE audit_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts           INTEGER NOT NULL,
  operation    TEXT NOT NULL,           -- 'remember' | 'recall' | 'forget' | 'merge' | 'expire'
  agent_id     TEXT,
  user_id      TEXT,
  memory_id    TEXT,
  payload      TEXT NOT NULL,           -- full JSON of the request
  result       TEXT,                    -- full JSON of the response
  approved_by  TEXT,                    -- user_id if HITL approved
  approval_at  INTEGER
);
```

---

## 4. Public API shape

```python
from amp import Memory, MemoryType, Recall

# Configure once; adapters injected at init
mem = Memory(
    agent_id="my-agent",
    stores=["sqlite-vec://./mem.db", "mem0://default"],
    fusion="rrf",
    governance=None,  # or governance=GovernanceClient("http://localhost:8000")
)

# Write
await mem.remember(
    "Alice is allergic to peanuts",
    type=MemoryType.SEMANTIC,
    user_id="alice@example.com",
)

# Read
results: list[Recall] = await mem.recall(
    "what should I avoid feeding alice?",
    k=5,
    types=[MemoryType.SEMANTIC, MemoryType.EPISODIC],
    hops=1,
)

# Forget
await mem.forget(filter={"user_id": "alice@example.com", "type": "episodic"})

# Merge dupes
await mem.merge(entity_a="Alice Smith", entity_b="alice")

# Expire (TTL apply)
await mem.expire(policy={"older_than_days": 90, "type": "episodic"})

# Procedural
proc = await mem.procedural.store(
    name="book-flight",
    states=["search", "select", "pay", "confirm"],
    transitions=[...]
)
await mem.procedural.replay("book-flight", start_state="search")
```

---

## 5. Memory-router algorithm

```python
async def recall(query: str, k: int = 5, hops: int = 1) -> list[Recall]:
    # 1. Fan out: query every store in parallel
    futures = [store.recall(query, k=k*4) for store in self.stores]
    results_per_store = await asyncio.gather(*futures)

    # 2. RRF fusion (k_rrf = 60 standard)
    fused = {}
    for store_results in results_per_store:
        for rank, item in enumerate(store_results):
            score = 1.0 / (60 + rank)
            if item.id in fused:
                fused[item.id].score += score
            else:
                fused[item.id] = item
                fused[item.id].score = score

    # 3. Optional 1-2 hop graph boost
    if hops > 0:
        for item in list(fused.values()):
            neighbors = await self._graph_neighbors(item, hops=hops)
            for n in neighbors:
                if n.id in fused:
                    fused[n.id].score *= (1 + 0.1 * (1 / (1 + n.hop_distance)))

    # 4. Sort, dedupe, return top-k
    return sorted(fused.values(), key=lambda x: x.score, reverse=True)[:k]
```

Graph boost is applied in Python after RRF — recursive CTE in SQLite is too slow at scale.

---

## 6. FSM procedural-memory backend

Use `pytransitions` to model agent procedures as state machines.

```python
from amp.procedural import Procedure

proc = Procedure(
    name="book-flight",
    states=["searching", "comparing", "selecting", "paying", "confirmed"],
    transitions=[
        {"trigger": "found_options", "source": "searching", "dest": "comparing"},
        {"trigger": "picked", "source": "comparing", "dest": "selecting"},
        {"trigger": "paid", "source": "selecting", "dest": "paying"},
        {"trigger": "receipt", "source": "paying", "dest": "confirmed"},
    ],
    initial="searching",
)
await mem.procedural.store(proc)
loaded = await mem.procedural.recall("book-flight")
loaded.found_options()  # transition; persists new current state
```

Procedures persist as JSON blobs (`states`, `transitions`, `current`). Replayable for debugging, inspectable in the governance UI.

---

## 7. STM↔LTM transformer module

Always-on async background task that:

1. Watches the STM buffer (in-memory recent ops)
2. On a configurable cadence (default 60s) OR when STM size > N (default 100):
   - Scores each STM item for "should this become long-term memory?" (heuristic: importance, recency, recall-frequency)
   - Items above threshold get `remember()`-ed into LTM via the router
   - Lower-scored items get `forget()`-ed (or aged)
3. Surfaces eviction decisions to the governance UI for human review (Co-memorize loop)

```python
from amp.transformer import STMToLTMTransformer

t = STMToLTMTransformer(
    memory=mem,
    cadence_seconds=60,
    stm_max_size=100,
    importance_threshold=0.6,
)
await t.start()  # runs forever in background
```

---

## 8. Governance UI (Pro tier)

Server-rendered HTMX + Tailwind for v0. Five screens:

1. **Pending Approvals** — list of `remember()` calls awaiting human review with diff against current state
2. **Memory Health Dashboard** — staleness, drift, contradictions, coverage by memory type
3. **Audit Log** — every operation, filterable, exportable as JSON/CSV
4. **Co-memorize Bulk Review** — periodic batch view of forget/merge candidates with model-generated reasoning
5. **Approval Patterns** — learned approve/reject rules, "auto-allow?" recommendations

Architecture: Starlette + Jinja2 + HTMX. No SPA framework. State server-side.

---

## 9. CI / wheel matrix

GitHub Actions workflows:

- `ci.yml` — lint (ruff, mypy) + unit tests on ubuntu/macos/windows × Python 3.11/3.12/3.13
- `wheels.yml` — cibuildwheel on tag (pure Python = simple, no native deps in core)
- `release.yml` — release-please + PyPI OIDC publish
- `docs.yml` — MkDocs Material → gh-pages

Day-1 wheel matrix: pure Python source dist + wheel (no native compilation needed — all native deps are in optional extras).

---

## 10. Hard performance targets (v0)

| Workload | Target | Why |
|----------|--------|-----|
| Single `remember()` (semantic) | <50ms p50 | One write to one store + audit log row |
| Single `recall()` (k=5, 2 stores fused) | <300ms p50 | RRF fusion + graph boost |
| `recall()` against 100k memories in sqlite-vec | <500ms p50 | Brute-force ANN is fine at this scale |
| FSM `procedural.store()` | <30ms p50 | One JSON write |
| STM→LTM consolidation (100 STM items) | <2s | Async background, not user-blocking |
| Governance UI page load | <200ms p50 | Server-rendered, no SPA |

Benchmark these in `tests/benchmarks/` using `pytest-benchmark`. Publish results in `docs/benchmarks.md` as part of the launch blog post.

---

## 11. Open architectural questions for week 1

These are deliberately not locked. Spike in week 1, update this doc with decisions:

- **Embedding model** — local (sentence-transformers) vs hosted (OpenAI embeddings). Default local. Decide based on quality on LongMemEval.
- **Audit log durability** — append-only SQLite vs separate jsonl file. SQLite WAL is probably sufficient.
- **Schema migrations** — alembic-style migrations vs single schema.sql. For v0, single schema.sql is fine.
- **Procedural memory: pytransitions vs xstate-python** — pytransitions is more mature in Python; xstate-python is newer but matches XState spec better. Decide based on community ergonomics.
- **Pro tier license** — fair-source vs source-available vs proprietary. Likely Functional Source License (FSL) for the UI; keeps it visible while protecting the revenue path.
