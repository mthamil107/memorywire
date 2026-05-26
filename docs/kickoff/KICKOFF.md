# Agent Memory Protocol (AMP) — Project Kickoff

> **How to use this file:** open a new Claude Code session in an empty directory. Copy this entire `agent-memory-kickoff/` folder into that directory. Paste the contents of this file as the first message. Claude will read the supporting files in order and start building.

---

## Hello, Claude. You are starting a new project.

I am building **AMP — the Agent Memory Protocol**: a vendor-neutral wire format and reference Python implementation for agent memory operations, plus a governance UI for diff-and-approve workflows on what agents remember/forget. Today's date is **2026-05-26**. This is a 2-week sprint targeting a launch in early-to-mid June 2026.

Before you write any code, **read these files in order**:

1. `KICKOFF.md` (this file) — vision, scope, week-1 tasks, working agreement
2. `FINDINGS-CONTEXT.md` — how we discovered this gap (4 GapFinder scout runs, the meta-pattern, sources)
3. `ARCHITECTURE.md` — locked technical decisions, schema, stack
4. `AMP-SPEC-v0.md` — the draft protocol specification (your week-1 deliverable is to refine and ship this)
5. `PROJECT-PLAN.md` — 14-day daily schedule with decision gates
6. `FUTURE.md` — roadmap, standards path, acquisition signals, year-1/2/3 milestones

If anything in this kickoff conflicts with those files, those files win — they are the source of truth.

---

## Why this project exists

Every existing agent-memory framework is **islanded**. mem0 (51k★, Series A) stores its memory in its own format. Letta (21.7k★, formerly MemGPT) bundles memory inside a full agent runtime. Cognee ($7.5M seed) has its own graph schema. Zep/Graphiti, MemoryOS, MemTensor MemOS, Memori — all storing similar information in incompatible ways. There is **no common protocol** for memory operations across these tools.

The four GapFinder scout runs documented in `FINDINGS-CONTEXT.md` consistently surfaced the same meta-pattern: **when a primitive layer becomes saturated, the operations / governance / cross-vendor-protocol layer above it survives as the gap**. Memory storage is now saturated. The protocol + governance layer above it is not.

Three specific virgin-territory pieces from the Run 4 architecture/memory research:

1. **FSM-based procedural memory** — XState exists but no agent-procedure FSM product. Only academic papers ("Remember Me, Refine Me", MemRL, MemEvolve).
2. **Always-on STM↔LTM transformer primitive as a standalone module** — Letta is closest but bundles it inside a full runtime. No OS-level standalone.
3. **Unified semantic + episodic + procedural + working memory stack with a memory-router API and a cross-agent memory protocol** (an MCP-equivalent for memory) — explicitly virgin.

Memory benchmarks (LongMemEval, LoCoMo, BEAM) are fragmented with no canonical leaderboard. The standardization race is open.

## What we are building (full scope)

**One repo, two composable deliverables, one OSS-core + Pro tier business model.**

### Deliverable 1 — AMP Protocol + Reference Implementation (OSS, MIT)

A Python library `agent-memory-protocol` (`pip install agent-memory-protocol`) plus a published spec document.

- **Wire format**: JSON schemas for `remember()`, `recall()`, `forget()`, `merge()`, `expire()` operations
- **Memory-type tags**: `semantic` (facts), `episodic` (events), `procedural` (FSM-encoded how-to), `emotional` (sentiment associations) — from the Biswas/human-memory taxonomy
- **Backend abstraction**: a `MemoryStore` interface with adapters into mem0, Letta, Cognee, Zep/Graphiti, sqlite-vec, Postgres+pgvector
- **Memory-router**: fan-out queries across N backends, RRF-merge results, return unified `Recall` objects (MCP-equivalent for memory)
- **FSM procedural backend**: XState wrapper, callable as a standalone module — store, inspect, edit, replay agent procedures
- **STM↔LTM transformer**: an always-on background module exposing `consolidate()` / `evict()` / `route()` callable APIs

### Deliverable 2 — Memory Governance UI (Pro tier, $29-99/dev/mo)

A web app (Next.js or HTMX server-rendered — decide week 1):

- **Diff-and-approve UI** for `remember()` calls — every memory write optionally pauses for human review with a structured diff against current state
- **Memory health dashboard** — staleness scores, drift detection, contradictions surfaced, contradiction-confidence scoring
- **Audit log** — every read/write/forget operation, exportable as JSON or CSV, structured for SOC2/HIPAA/EU AI Act compliance
- **Co-memorize bulk review** — periodic "memory hygiene" view: top-N candidates for forget/merge with model-generated reasoning
- **Approval-learning loop** — track which patterns humans always approve / always reject; surface "auto-allow?" recommendations after N consistent approvals

The Pro tier is the revenue path. The OSS protocol is the distribution flywheel.

## Locked technical decisions (do not re-debate)

These were decided after the Run-4 research. Don't waste time re-evaluating; if you think one is wrong, raise it before writing code.

1. **Language / runtime**: Python 3.11+ for the reference implementation. Async-first (use `asyncio`).
2. **Build tool**: `uv` for dev/lock/install. `hatchling` for the PEP 517 build backend.
3. **Package layout**: `src/amp/` for the protocol + reference impl. Apache-2.0 license (more permissive than MIT for protocols).
4. **Spec format**: JSON Schema Draft 2020-12. Spec doc as markdown with embedded schemas. Plan to publish as an IETF draft once v0.2 is stable.
5. **Backend adapters**: ship Day 1 with adapters for `sqlite-vec` and `mem0`. Day 7 add `Letta`, `Cognee`, `Postgres+pgvector`.
6. **FSM library**: `pytransitions` for the procedural-memory backend (simpler than XState equivalents in Python; well-maintained).
7. **Memory-router fusion**: RRF (k=60) — same standard as Graphiti, Mem0, Elastic, Azure.
8. **Governance UI**: server-rendered HTMX + Tailwind for v0 (ship fast). Next.js if/when v1 demands richer interactions.
9. **Telemetry**: OPT-IN only, never opt-out. Air-gap-friendly out of the box.
10. **License**: Apache-2.0 for the protocol and reference implementation. Pro tier UI is source-available under a fair-source license.

## First sprint — week 1 deliverables (your concrete tasks)

When I confirm "go," execute these in order. Use TaskCreate to track. One PR per task even though there's no reviewer (clean changelog).

1. **Bootstrap the repo skeleton** — per `ARCHITECTURE.md` directory tree. Apache-2.0 LICENSE, NOTICE, README stub, .gitignore, `pyproject.toml` (uv + hatchling), GitHub Actions CI workflow (`xcodebuild`-equivalent for Python: `pytest` on macos+linux+windows × py3.11/3.12/3.13).

2. **Refine and publish `AMP-SPEC-v0.md`** — start from the draft in this folder. Add JSON Schema 2020-12 schemas for all 5 operations and 4 memory types. Add 3 worked examples per operation. Open as `docs/spec/v0.md` in the repo + publish as a draft on GitHub Discussions.

3. **Implement the `MemoryStore` interface** — `src/amp/store/base.py`. Pure Protocol class with type hints. Test against a mock backend. No real backends yet.

4. **Implement sqlite-vec and mem0 adapters** — `src/amp/store/sqlite_vec.py` and `src/amp/store/mem0_adapter.py`. Tests for each.

5. **Implement the memory-router** — `src/amp/router.py`. RRF fusion (k=60) over results from N adapters. Tests with two stores returning overlapping + non-overlapping memories.

6. **Implement the FSM procedural-memory backend** — `src/amp/procedural.py` using `pytransitions`. Demo: store the procedure for "book a flight" as an FSM that can be inspected, edited, replayed.

7. **Implement the STM↔LTM transformer module** — `src/amp/transformer.py`. Background async task that runs on a configurable schedule, calls `consolidate()` on STM, writes to LTM via the router.

8. **Examples + CLI** — `examples/quickstart.py` shows the full loop. `amp` CLI command: `amp remember <text>`, `amp recall <query>`, `amp forget --filter <expr>`.

By end of week 1: `pip install -e .` works on macOS/Linux/Windows. `pytest` passes in <60s. `python examples/quickstart.py` ingests 50 text snippets into sqlite-vec + mem0, recalls them via the router, dumps the FSM for one procedure.

## Working agreement

- **Test discipline**: every PR adds unit tests. Mock backends for unit tests; real backends (mem0, sqlite-vec) only in `tests/integration/`.
- **Commit discipline**: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`). **Do NOT add `Co-Authored-By` trailers.**
- **Scope discipline**: if you want to add a feature, ask. The bar is "does this strengthen the protocol or the governance UI before launch?" If not, defer.
- **Polish discipline**: weeks 1-2 are functional. Polish is week 2's job, not week 1's.
- **Spec discipline**: keep the spec ahead of the implementation. If the reference impl does something the spec doesn't describe, that's a spec bug — update the spec first.
- **Output discipline**: every public function gets a docstring with at least one example.

## Decision gates

- **End of week 1**: protocol spec v0 published, reference impl runs end-to-end with 2 backends + router + FSM + transformer, examples work. If not, the project is technically infeasible — kill or radically reduce scope.
- **End of week 2**: governance UI shipped, blog post ready, ≥3 adapter PRs filed upstream into mem0/Letta/Cognee. Ready for Show HN.
- **WWDC 2026 is June 9.** If Apple, OpenAI, Anthropic, or Google announces a memory protocol/framework at the same time as launch week, REFRAME the blog post as comparison-and-positioning ("here's how AMP composes with what was just announced") — don't abandon.

## What I want you to do right now

1. Read `FINDINGS-CONTEXT.md`, `ARCHITECTURE.md`, `AMP-SPEC-v0.md`, `PROJECT-PLAN.md`, `FUTURE.md` in that order.
2. Confirm understanding of the locked decisions.
3. List the 8 week-1 deliverables back to me with your initial questions or concerns.
4. WAIT for me to say "go" before writing any code.

When I say go, start with task 1 (repo bootstrap) and use TaskCreate to track progress.
