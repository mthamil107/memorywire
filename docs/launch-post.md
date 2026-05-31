---
title: "Every agent memory framework is islanded. I drafted a protocol and built a reference implementation."
slug: memorywire-launch
date: 2026-06-10
canonical_url: https://github.com/mthamil107/memorywire
tags: [agent-memory, MCP, OSS, protocol, governance]
status: draft
---

<!--
Alternate titles considered (kept here for the social copy):
  - "What MCP did for tool-use, memorywire does for memory."
  - "Five backends, one wire format: building the protocol layer above agent memory frameworks."
-->

Every agent memory framework today stores broadly the same information &mdash; user facts, conversation episodes, sometimes a procedure &mdash; in an incompatible shape. Integrate more than one and you write the same adapter twice. Try to move memory between frameworks and there's no migration path, only export-and-rewrite.

The dominant players, as of 2026-05: **mem0** at roughly 51k GitHub stars and a Series A; **Letta** (formerly MemGPT) around 21.7k stars; **Cognee** at a published $7.5M seed; **Zep/Graphiti** as the graph variant; **MemoryOS** and **MemTensor MemOS** on the research edge. All of them store memory. None of them store it the same way. None of them ship a vendor-neutral wire format another framework can speak.

The **memorywire** is the layer above them. A small, stable wire format &mdash; five operations, four memory types, one router, one optional governance channel &mdash; that composes with existing frameworks rather than competing with them. The repo (`https://github.com/mthamil107/memorywire`) ships the spec, a Python reference implementation, five day-1 backend adapters, an STM&harr;LTM transformer, an FSM procedural backend, and a Starlette/HTMX governance UI.

## How I found this gap

I don't want to sound mystical about this. The discovery has a paper trail. Between March and May 2026 I ran an autonomous market-research pipeline I call **GapFinder** across four sequential scout investigations &mdash; on-device SLM reasoning, AI bot authentication, Claude Code orchestration, and the full agentic-AI module taxonomy &mdash; each one a nine-stage discover/scan/kill/explore pipeline whose explicit goal is to *aggressively try to disprove* every gap it surfaces. The most valuable output is the gaps killed, not the ones surfaced.

Four runs in, the same meta-pattern recurred every time:

| Run | Saturated primitive layer | Surviving operations / protocol layer |
|-----|---------------------------|---------------------------------------|
| 1 (kg-slm)         | On-device SLM runtimes (Ollama, MLX, llama.cpp)              | KG-shaped memory above them |
| 2 (web-bot-auth)   | CDN-tier bot management (Cloudflare, Akamai, AWS WAF)        | FOSS middleware for self-hosted operators |
| 3 (Claude Code)    | Orchestrators (Ruflo, Gas Town, Multiclaude, Agent Teams)    | Cost / skill-health / consequence-preview ops layer |
| 4 (Agentic AI)     | Memory frameworks (mem0, Letta, Cognee, Zep)                 | Memory governance protocol + diff-and-approve UI |

The pattern: **when a primitive layer saturates, the operations / governance / cross-vendor protocol layer above it survives as the open gap.** Run 4 applied the heuristic to memory and surfaced three pieces visibly unbuilt: an FSM-based procedural memory product (research papers exist, no shipping product), a standalone always-on STM&harr;LTM transformer primitive (Letta bundles one inside a runtime but no one ships it as a module), and a unified semantic + episodic + procedural + working stack with a real router API and a cross-agent protocol. That third piece &mdash; the MCP-equivalent for memory &mdash; is what I sat down to draft.

The receipts for every step live at [`docs/kickoff/FINDINGS-CONTEXT.md`](docs/kickoff/FINDINGS-CONTEXT.md). Deliberately verbose, because the gap can only be trusted if the methodology is visible. I didn't even start out building this &mdash; I started building a Claude Code orchestrator, Run 3 killed it (Ruflo at 31k stars, Gas Town, Multiclaude all ship variations), and only then did the 15-module agentic-AI scan surface memorywire. The willingness to kill the first idea is what produced the second.

## What memorywire is

memorywire defines **five operations** &mdash; `remember`, `recall`, `forget`, `merge`, `expire` &mdash; each with a JSON Schema 2020-12 request/response shape in [`src/memorywire/schemas/`](src/memorywire/schemas/). **Four memory types** drawn from the cognitive-science taxonomy: `semantic` (facts), `episodic` (events with time/place), `procedural` (FSM-encoded how-to), `emotional` (affective associations). One **`MemoryStore` Protocol** that any backend implements. One **memory router** that fans operations across N stores in parallel and fuses recall results with Reciprocal Rank Fusion at k=60, with an optional 1-hop graph boost. One **STM&harr;LTM transformer** running as an async background task, scoring short-term items on importance / recency / recall-count and promoting or evicting them. One **FSM procedural backend** that serialises pytransitions-compatible state machines so how-to procedures can be stored, replayed, and edited in the UI. And one optional **governance channel** that intercepts `remember`/`forget`/`merge` calls flagged with `approval_required`, stages them, and exposes a structured diff for human review.

![memorywire architecture: client, orchestration, storage and governance layers](docs/architecture.png)

*Figure 1. The full runtime: SDK/CLI calls hit the `Memory` facade, which delegates to the router; the router fans across heterogeneous backends and fuses recall via RRF (k=60); procedural writes take an FSM side-path; the STM&harr;LTM transformer runs out-of-band; the governance UI and the sqlite-vec adapter share the same SQLite database so reviewers can diff pending writes against live state.*

Five day-1 backend adapters ship with v0: `sqlite-vec` (local default), `mem0`, `Letta`, `Cognee`, and `pgvector`. The single-page spec is at [`docs/spec/v0.md`](docs/spec/v0.md); schemas at [`src/memorywire/schemas/`](src/memorywire/schemas/); architecture writeup at [`docs/architecture.md`](docs/architecture.md).

## What memorywire is not

**memorywire is not an algorithmic invention.** I didn't invent RRF (Cormack et al. 2009), didn't invent the semantic/episodic/procedural taxonomy (Tulving 1972), didn't invent diff-and-approve workflows. memorywire is a *composition* of established primitives into a stable wire format. The work is in the shape of the protocol and the discipline of the spec.

**Not a new vector store** &mdash; the router calls existing ones. **Not a replacement for mem0/Letta/Cognee** &mdash; it's a layer *above* them. **Not an MCP fork.** From [`docs/MCP-RELATIONSHIP.md`](docs/MCP-RELATIONSHIP.md): *"memorywire is what MCP would be if MCP had a memory primitive; I built it as a standalone spec so the design can stabilize without blocking on MCP-WG governance, with intent to propose adoption as an MCP extension at v0.5."* The two address adjacent concerns &mdash; tool-use (MCP) and memory (memorywire) &mdash; and the agents I build use both.

## Concrete numbers

Microbench, on Windows 11 / Python 3.13.13 / CPU-only with `sentence-transformers/all-MiniLM-L6-v2` + `sqlite-vec(:memory:)`: **recall@5 = 1.000 on 42 labelled queries**, ingest p50 **37.8 ms**, recall p50 **40.6 ms**, full run ~5.9 s. Dataset: 100 hand-authored facts, 50 queries (24 paraphrase, 10 exact-match, 8 multi-hit, 8 no-match). Reproduce with `python scripts/run_microbench.py --json`. Read the caveats at [`docs/benchmarks.md`](docs/benchmarks.md): this is a microbench, not LongMemEval/LoCoMo. Those land in v0.2 (each needs a paid GPT-4-class grader, which I'm deferring rather than cutting corners on). The no-match probes correctly empty in 0/8 cases &mdash; there's no calibrated relevance threshold in v0, also a v0.2 follow-up. Headline holds: every paraphrase / exact / multi-hit query surfaced all its gold ids in the top-5.

## The governance angle

This is the piece I most want operators to test, because it has the strongest standalone value.

![memorywire governance UI: pending memory, structured diff, approve, audit](docs/demos/ui.gif)

A `remember` with `approval_required: true` stages the row behind a sentinel (`PENDING_APPROVAL_DELETED_AT = -1` in `memories.deleted_at`) so it cannot influence recall until a human approves. The Pro-tier UI (Starlette + HTMX, source-available under FSL 1.1, auto-converts to Apache-2.0 after 2 years) renders the pending memory with a structured diff against the closest live counterpart; the reviewer approves or rejects; the decision is journaled into an append-only audit log keyed by `approved_by`. The same flow covers `forget` and `merge`. An approval-learning loop sits on top: track which patterns the reviewer always approves or rejects and auto-allow after N consistent decisions.

This matters because *memory governance is becoming a compliance problem*, not just a quality-of-life one. EU AI Act transparency / human-oversight, HIPAA audit-trail expectations on systems that persist patient context, SOC2 data-handling &mdash; all assume you can answer "what does this system remember, who decided, and when?" Today, with no protocol-level governance primitive across memory frameworks, the answer is "instrument each framework separately." memorywire's channel is one place to instrument and one log to query. The closest published precedent is the Co-memorize HITL pattern from the *Governed Memory* paper (arXiv 2603.17787); memorywire's contribution is shipping it as protocol surface and a working UI.

## Security in one paragraph

The threat model is at [`docs/THREATS.md`](docs/THREATS.md). Six adversaries enumerated &mdash; malicious memory injection, recall exfiltration, poisoned backend in RRF fusion, audit log tampering, cross-tenant IDOR, and approval bypass (UI no-auth + procedural-memory RCE through pytransitions callback strings) &mdash; each with a `Current mitigation / Residual risk / v0.2 hardening` block. The IDOR set and the procedural-memory RCE were both caught by a security-review pass before launch and fixed in commit `c828d76`. RRF is score-independent by construction, which limits how much a single poisoned backend can dominate fused recall. Append-only audit discipline is enforced at the code layer in v0; Merkle-chained rows are tracked for v0.2. None of this substitutes for the upstream backends' own security; it makes memorywire itself not the weakest link.

## Try it

From source (PyPI tag goes live shortly):

```bash
git clone https://github.com/mthamil107/memorywire
cd memorywire
uv venv && uv pip install -e ".[sqlite-vec]"
```

Quickstart:

```python
import asyncio
from memorywire import Memory, MemoryType

async def main():
    mem = Memory(
        agent_id="customer-bot",
        stores=["sqlite-vec://./mem.db", "mem0://default"],
    )

    await mem.remember(
        "Alice is allergic to peanuts",
        type=MemoryType.SEMANTIC,
        user_id="alice@example.com",
    )
    await mem.remember(
        "On 2026-03-10 Alice reported a billing issue",
        type=MemoryType.EPISODIC,
        user_id="alice@example.com",
    )

    hits = await mem.recall(
        "what should I avoid feeding alice?",
        k=5,
        hops=1,
    )
    for h in hits:
        print(f"{h.score:.2f}  {h.type}  {h.content}")

asyncio.run(main())
```

End-to-end demos: [`examples/01_quickstart.py`](examples/01_quickstart.py) (50 facts &rarr; recall &rarr; forget) and [`examples/03_procedural_fsm.py`](examples/03_procedural_fsm.py) (FSM procedural memory). The `memorywire` CLI ships three subcommands &mdash; `memorywire remember`, `memorywire recall`, `memorywire forget` &mdash; demoed in [`docs/demos/cli.gif`](docs/demos/cli.gif). If you're reading this on launch day, the live governance-UI demo is at `<DEPLOY_URL_TBD>`.

## Roadmap

**v0.2 (4&ndash;6 weeks post-launch)** lands what v0 deferred: LongMemEval and LoCoMo with a paid GPT-4-class grader, calibrated relevance threshold, `privacy_intent` flags on `remember` (consent / retention / share-scope), an MCP-WG RFC filing memorywire as candidate reference for a memory extension, multi-tenant per-session agent scoping in the UI, plus a cross-vendor fusion benchmark with Letta + Cognee on disjoint indexes.

**v0.5 (Q3 2026)** is the standards moment. Spec frozen, IETF Internet-Draft submitted as `draft-<name>-memorywire-00` by analogy to Cloudflare's `draft-meunier-web-bot-auth-architecture`, cross-language ports begin (Rust and TypeScript first). **v1.0 (Q1 2027)** stabilizes the wire format, adds federated multi-tenant primitives and enterprise governance (SSO, RBAC), opens a W3C Community Group for the browser-runtime side.

## The honest closing

**Best case (~15-20%).** memorywire becomes the de-facto cross-vendor memory protocol via MCP-WG &rarr; IETF &rarr; W3C, the same arc MCP took for tool-use in 2024-2026. mem0, Letta, Cognee, Zep ship native memorywire support within six months. One foundation-model vendor acknowledges and contributes. Pro-tier UI lands paying enterprise customers on SOC2/HIPAA/EU-AI-Act compliance. 12-month outcome: $200K-$1M ARR, plausibly an acquihire offer. I don't bet on this case &mdash; standards races are slow, and many vendors prefer to own the layer themselves.

**Likely case (~50%, the baseline expectation).** 500-5,000 GitHub stars over six months. One or two of mem0/Letta/Cognee accepts an adapter PR; the others ship something incompatible. The spec isn't canonical but is taken seriously by people in this corner of the field. Pro-tier UI plateaus at $30-150K ARR. The cumulative artifact &mdash; clean spec, reference impl across five backends, governance UI, demo video, threat model, microbench &mdash; lands a memory-focused job offer. Useful + finished + visible is hire-me even when not venture-scale.

**Worst case (~20-25%).** A foundation-model vendor ships a memory protocol with first-party tooling the same quarter. mem0/Letta/Cognee adopt it; memorywire becomes a footnote. Six-month outcome: ~100 stars, no engagement, the spec and demo survive as portfolio. I'm taking this bet *because the floor is itself valuable* &mdash; a polished spec, a working reference impl across five backends, a governance UI, and a threat model mapped to OWASP/CWE is a substantial artifact regardless. Bet on the floor, play for the ceiling.

> Pull quote, if you want one: **Memory storage is saturated. The protocol layer above it is not.**

## Call to action

If any of this lands: **file an issue on the spec** &mdash; protocol-level disagreement is more useful than agreement at this stage. **Star the repo** if you want to track v0.2. **Tweet a frame** of the architecture diagram or governance UI &mdash; the launch thread is at [TWEET_URL_TBD]. **File an adapter PR** upstream into mem0/Letta/Cognee/Zep or your backend of choice &mdash; the contract is one Protocol and roughly 200 lines of Python ([`docs/adapters.md`](docs/adapters.md)). If you're at a memory framework or a foundation-model memory team and want to talk composition: open an MCP-WG-tagged issue. The protocol is only useful if other people adopt it or fork it into something better. Either is fine. Doing nothing is the failure mode I'm avoiding.
