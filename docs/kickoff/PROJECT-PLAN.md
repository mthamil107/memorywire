# AMP — 2-Week Sprint Plan

**Generated:** 2026-05-26 · **Launch target:** 2026-06-10 (Wednesday after WWDC) · **WWDC 2026:** June 9

> Goal: ship the AMP spec v0 + Python reference implementation + governance UI + blog post + Show HN, with PRs landed (or filed) upstream into mem0/Letta/Cognee. Success metric = ≥1 of the three framework maintainers engages publicly, OR ≥500 GitHub stars, OR ≥3 inbound DMs from memory-framework maintainers within 30 days.

---

## Why this 2-week window specifically

| Date | Event | Why it matters |
|------|-------|----------------|
| **Mon 2026-05-26** | Sprint start (today) | First commit |
| **Mon 2026-06-09** | WWDC 2026 keynote | Apple may announce memory primitives; either way the on-device-AI conversation peaks |
| **Tue 2026-06-10** | Our launch | Post-WWDC, in the discussion window. Apple's announcements are tailwind, not threat, because AMP is vendor-neutral. |
| **Mon 2026-06-23** | End of week 4 follow-up window | Direct outreach to memory-framework maintainers concludes; decide go-deeper or pivot |

If a major vendor (Apple/OpenAI/Anthropic/Google) announces a memory protocol the same week, reframe the launch as: *"Here's how AMP composes with [announcement] — same primitives, but vendor-neutral."* That's a stronger pitch, not weaker.

---

## Week 1 (May 26 - Jun 1) — Spec + Reference Implementation

**Theme:** prove the protocol is real and runs end-to-end across two backends.

| Day | Deliverable |
|-----|-------------|
| **Mon May 26** | Repo bootstrap: Apache-2.0 LICENSE, NOTICE, README stub, `.gitignore`, `pyproject.toml` (uv + hatchling), `.github/workflows/ci.yml`. Push initial commit. |
| **Tue May 27** | Refine `docs/spec/v0.md` from the AMP-SPEC-v0.md draft. Add JSON Schema 2020-12 files to `src/amp/schemas/`. Add 3 worked examples per operation. Open as a Discussion on GitHub. |
| **Wed May 28** | `src/amp/store/base.py` — `MemoryStore` Protocol with type hints. `src/amp/models.py` — pydantic models matching schemas. Unit tests with a mock store. |
| **Thu May 29** | `src/amp/store/sqlite_vec.py` — sqlite-vec adapter. SQLite schema from `ARCHITECTURE.md` §3. Integration tests. |
| **Fri May 30** | `src/amp/store/mem0_adapter.py` — mem0 adapter (wraps mem0ai client). Integration test against a local mem0 instance. |
| **Sat May 31** | `src/amp/router.py` — memory router with RRF fusion. Tests with both stores returning overlapping + non-overlapping memories. |
| **Sun Jun 1** | Off. (Or buffer for anything broken.) |

**End-of-week-1 success criteria:**

- `pip install -e .` works on macOS / Linux / Windows
- `pytest -m "not integration"` passes in <60s
- `python examples/01_quickstart.py` ingests 50 text snippets into both sqlite-vec + mem0, recalls via the router, prints fused results
- `amp` CLI works: `amp remember`, `amp recall`, `amp forget`

If any of these fail by Sunday, the project is technically infeasible — radically reduce scope (drop mem0 adapter, ship sqlite-vec only) and proceed.

---

## Week 2 (Jun 2 - Jun 8) — FSM + Transformer + UI + Launch Prep

**Theme:** ship the differentiators (FSM procedural memory + STM↔LTM transformer + governance UI) and prepare the launch.

| Day | Deliverable |
|-----|-------------|
| **Mon Jun 2** | `src/amp/procedural.py` — FSM backend via `pytransitions`. Demo: store "book-flight" FSM, replay it, inspect current state. |
| **Tue Jun 3** | `src/amp/transformer.py` — STM↔LTM consolidator as async background task. Tested with a synthetic workload. |
| **Wed Jun 4** | `ui/` sub-package — Starlette + HTMX governance UI. Two screens: Pending Approvals + Audit Log. |
| **Thu Jun 5** | UI screens 3-5: Memory Health Dashboard + Co-memorize Bulk Review + Approval Patterns. |
| **Fri Jun 6** | Write the launch blog post (~2,000 words). Title: *"Every agent memory framework is islanded. I drafted a protocol and built a reference."* Reference the 4-run GapFinder methodology, the three virgin pieces (FSM/STM↔LTM/protocol), the Co-memorize gap, the diff/approve workflow. Include the LongMemEval benchmark number once you have it. |
| **Sat Jun 7** | Record demo screencast (~90 seconds). Run on real workload. Capture diff/approve UI in action. |
| **Sun Jun 8** | Buffer. WWDC eve. |

**End-of-week-2 success criteria:**

- Full demo runs: ingest sample agent conversation → router fuses across 2 backends → FSM stores 1 procedure → UI shows pending approval → human approves → audit log shows the operation
- Blog post drafted, 90% done
- Show HN post drafted
- Demo video edited and compressed

---

## Launch week (Jun 9 - Jun 15)

| Day | Action |
|-----|--------|
| **Mon Jun 9** | Watch WWDC keynote. Take notes. If Apple announced memory primitives → update blog post with comparison angle (90 min work). |
| **Tue Jun 10** | **LAUNCH DAY.** 6:30am PT: Show HN. Same hour: r/MachineLearning + r/LocalLLaMA self-posts. Twitter thread tagging `@charlespacker` (Letta), `@taranjeetio` (mem0), `@vasilije1990` (Cognee), `@gertjanvdburg` and Anthropic / OpenAI memory team handles. |
| **Wed Jun 11** | Engage every comment on HN / Reddit. Respond thoughtfully. Each reply is a public interview audition. |
| **Thu Jun 12** | File adapter PRs upstream: mem0 (add AMP-compatible adapter), Letta (same), Cognee (same). Open issues with each: "would you accept an AMP-compatible adapter?" |
| **Fri Jun 13** | Reach out directly to Letta / mem0 / Cognee CEOs via Twitter DM with the spec + demo link. |
| **Sat-Sun Jun 14-15** | Off. |

---

## Weeks 4-5 (Jun 16 - Jun 29) — Convert attention to engagement

**Theme:** the launch is shipped; now work the outreach.

This is the part that solo-side-project people skip and then wonder why nothing happened. **The outbound after launch matters more than the launch itself.**

| Week | Action |
|------|--------|
| **Week 4 (Jun 16-22)** | Reply to every PR/issue comment on the adapter PRs. Engage in MCP working-group discussions about memory extensions. Submit a talk to a memory-focused conference (Memory & Agents Summit 2026 if it exists; otherwise an MLOps or LangChain meetup). |
| **Week 5 (Jun 23-29)** | Direct outreach to 15-20 specific people: Letta hiring managers, mem0 hiring managers, Cognee team, Anthropic Memory team, OpenAI Memory team, Microsoft Azure AI Foundry Memory team. Personalized DMs referencing the spec and a piece of their published work. |

**End-of-week-5 success metrics:**

- ≥500 GitHub stars (or ≥1k if HN front page hit)
- ≥1 of mem0/Letta/Cognee accepted (or substantively engaged on) the adapter PR
- ≥3 first-round interviews scheduled with target memory teams
- ≥1 spec comment / question from someone at OpenAI / Anthropic / Google / Microsoft memory teams

If those numbers land, the project worked. The hire follows from quality outreach + concrete artifact.

---

## Hard kill / pivot triggers

Stop or reshape if:

- **End of week 1:** Spec runs end-to-end with 2 backends fails → drop mem0 adapter, ship sqlite-vec only, narrow blog post to "AMP v0 with the reference impl."
- **End of week 2:** Governance UI not shipping → drop UI from launch, position as protocol-only release. Ship UI as v0.2 in week 5-6.
- **WWDC announces a fully-formed memory protocol:** REFRAME as comparison-and-positioning. Don't abandon. Apple/OpenAI/Google announcements expand the market for cross-vendor memory thinking, they don't shrink it.
- **End of week 5:** Zero inbound from any target team, <100 stars, no PR engagement → reassess. Either deepen the technical artifact (publish benchmark numbers, write a research-style writeup), or pivot the outreach (broader OSS infra hiring vs narrow memory-team focus).
- **mem0 / Letta ships a competing protocol** during your sprint → embrace it. Their protocol is now your competitive baseline. Position AMP as the cross-vendor adapter layer ABOVE their protocol. Same play Cloudflare made with Web Bot Auth.

---

## Cost estimate

**Time:** ~30 hrs/week × 2 weeks of build + 5 hrs/week × 3 weeks of outreach = ~75 hrs total.

**Money:**

- Domain `amp-protocol.dev` or similar: $12/yr
- Hosting (GitHub Pages + Vercel for governance UI demo): $0
- Embedding API costs for benchmarks (optional, if not using local sentence-transformers): $5-20
- **Total out-of-pocket: $20-50.**

This is a substantially cheaper bet than the kg-slm sprint because there's no iOS device requirement, no Apple Developer Program, no native code compilation.

---

## What's explicitly NOT in this plan

For clarity, these are out of scope and should NOT be re-added:

- ❌ A full agent runtime (we use existing ones; we ship the protocol)
- ❌ A new vector store (we adapt existing ones)
- ❌ A LLM evaluation framework (orthogonal; not what users need from a memory protocol)
- ❌ A memory-as-a-service hosted SaaS (Pro tier UI is the only revenue path)
- ❌ Cross-language (Rust / Go / TS) reference implementations — defer to v0.5
- ❌ A memory benchmark of our own — use LongMemEval / LoCoMo / BEAM
- ❌ Enterprise governance features (SSO, RBAC, multi-tenant) — defer to v1.0 Pro
- ❌ Federated / multi-org memory — defer to v1.0

If any of these resurface during execution, push back.

---

## Reference materials in this directory

- [`KICKOFF.md`](KICKOFF.md) — bootstrap prompt for new Claude Code session
- [`FINDINGS-CONTEXT.md`](FINDINGS-CONTEXT.md) — how we found this gap (4 GapFinder scout runs)
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — stack, schema, directory layout, performance targets
- [`AMP-SPEC-v0.md`](AMP-SPEC-v0.md) — the draft protocol specification (your week-1 deliverable to refine)
- [`FUTURE.md`](FUTURE.md) — year-1/2/3 roadmap, standards path, acquisition signals
