# FUTURE — Where AMP Goes From Here

This document is the speculative roadmap. It exists so that anyone reading the v0 spec can see the longer arc and judge whether the bet is worth the next 18-24 months of work — or whether v0 is the right place to stop.

It's organized as: where AMP could go (best/likely/worst), what standards/ecosystem dynamics matter most, and the specific year-1 / 2 / 3 milestones with kill criteria.

---

## The three possible futures

### Best case — AMP becomes the de facto cross-vendor memory protocol

Same arc as MCP for tool-use: shipped by Anthropic in late 2024, adopted by OpenAI/Google/Cloudflare in 2025, became universal by 2026. If AMP lands the same way:

- mem0, Letta, Cognee, Zep, and a 4th backend ship native AMP support within 6 months
- One of the foundation-model vendors (Anthropic / OpenAI / Google / Microsoft) acknowledges and contributes to the spec
- AMP becomes an IETF Internet-Draft by month 12
- The governance UI gains paying enterprise customers seeking SOC2/HIPAA/EU AI Act compliance
- 12-month outcome: $200K-$1M Pro-tier ARR, acquihire offer from a memory framework or a foundation model lab

**Probability estimate:** ~15-20%. Standards races are slow and many vendors prefer to own the layer themselves.

### Likely case — AMP is useful OSS, hire-me artifact, no business

The most realistic outcome based on the cumulative Run 1-4 evidence:

- 500-5,000 GitHub stars over 6 months
- 1-2 of mem0 / Letta / Cognee accepts the adapter PR; the other 1-2 ship their own incompatible protocol
- The spec doesn't become the standard but is taken seriously
- Pro-tier UI lands a handful of paying customers, plateaus at $30-150K ARR
- 12-month outcome: the project is recognized portfolio work and lands a job offer at Letta / mem0 / Cognee / Anthropic Memory / OpenAI Memory / Microsoft Azure AI Foundry Memory team

**Probability estimate:** ~50%. This is the kg-slm-lesson-applied baseline expectation. Useful + finished + visible = hire-me even when not venture-scale.

### Worst case — Vendor ships first, AMP is roadkill

- WWDC 2026 (June 9) or OpenAI DevDay 2026 (October) announces a vendor-blessed memory protocol with first-party tooling
- mem0/Letta/Cognee adopt the vendor protocol; AMP becomes a footnote
- 6-month outcome: ~100 stars, no engagement, but the spec PDF and the demo video still live on as a portfolio artifact you can point at

**Probability estimate:** ~20-25%. Mitigated by AMP's vendor-neutral positioning — even a vendor protocol creates more conversation about cross-vendor memory, which still benefits anyone working in this space publicly.

---

## Year-1 Milestones

### Month 1 (Jun 2026) — Launch

- Spec v0 published
- Reference impl ships with sqlite-vec + mem0 adapters
- Governance UI shipped
- Show HN landed
- ≥1 adapter PR accepted upstream OR ≥3 inbound DMs from memory-framework maintainers
- **Kill criterion:** zero engagement from any of the 6 target memory frameworks after 30 days → reassess; project may shift to pure portfolio-piece mode

### Month 2-3 (Jul-Aug 2026) — Adoption attempt

- Add Letta + Cognee + Postgres+pgvector adapters
- Publish first benchmark on LongMemEval comparing AMP-via-router-of-2-backends vs single-backend baseline
- Engage MCP working group on memory extension positioning
- Submit talk to an AI infra / agents conference (Edge AI Summit, AI Engineer Summit, MLOps World)
- Spec v0.2 with privacy-intent flags (Module 11 "Layer 3 gap" coverage)
- **Kill criterion:** zero accepted adapter PRs by month 3 → narrow to single-vendor depth (e.g., go deep on mem0 specifically) instead of cross-vendor breadth

### Month 4-6 (Sep-Nov 2026) — Standards positioning + Pro tier polish

- Publish AMP as an Internet-Draft (IETF) and/or W3C Community Group Report
- Pro-tier UI lands first 5-10 design partners; structure feedback into v0.5 spec
- Memory-router supports 4+ backends in production for at least one design partner
- Approval-learning loop ships and reduces HITL interruption rate by ≥30% in design-partner usage
- **Kill criterion:** zero paying design partners + zero IETF/W3C uptake → focus shifts to acquisition conversations

### Month 7-9 (Dec 2026 - Feb 2027) — Acquisition / hiring window

- Either: $100K-500K ARR signals real customer pull → continue building business
- Or: acquihire conversations with mem0 / Letta / Cognee → ship the talent-asset path
- Or: direct hire at Anthropic Memory / OpenAI Memory / Microsoft / Google → ship the hire-me path
- **Kill criterion:** zero of the above paths active after 9 months → wind down to pure OSS stewardship mode (Mozilla Builders / Sovereign Tech Fund grant)

### Month 10-12 (Mar-May 2027) — v1.0 stabilization

- Spec v1.0: operations frozen, schemas stable, breaking changes off the table
- 4+ adapters in production
- ≥10 paying Pro-tier customers OR completed acquisition / hire
- ≥1k GitHub stars

---

## Year 2 (June 2027 onward) — three scenarios

### Scenario A: Standards body adoption

AMP becomes part of MCP working group, IETF, or W3C Community Group. The reference implementation continues as the canonical Python port; other-language ports emerge from the community.

- Pro tier expands into enterprise governance (SSO, RBAC, multi-tenant, federated memory)
- Hire team of 3-5 to build enterprise features
- Revenue: $1-5M ARR by end of Year 2
- Equity event: Series A possible, $10-25M raise

### Scenario B: Niche tool + acquisition

AMP doesn't win the standards race but stabilizes as a useful tool for the subset of teams that need cross-vendor memory. Acquisition by mem0 / Letta / Cognee / a memory-focused foundation-model team becomes the natural exit.

- 12-24 months from now: $1-5M acquihire-shaped exit
- Team joins acquirer to build their memory product
- Project becomes a feature inside their stack

### Scenario C: OSS stewardship

The protocol doesn't gain commercial traction but is genuinely useful. Continue as a part-time / sponsorship-funded project (Mozilla Builders, Sovereign Tech Fund, Open Collective).

- No revenue but durable impact
- Founder maintains as portfolio piece while taking employment elsewhere
- Future founders pick it up if the moment becomes right

---

## Year 3 (June 2028 onward) — depending on Year 2

### If Scenario A — Standards adoption succeeded

- AMP v2.0 with cross-language ports (Rust, Go, TypeScript) shipped by community
- Federated multi-tenant memory primitives
- Memory benchmarks owned: AMPBench becomes the canonical evaluation
- Revenue: $5-20M ARR
- Acquisition or IPO conversations

### If Scenario B — Acquired

- AMP shipped as a feature inside the acquirer's product
- Founder continues working on memory at the acquiring company
- Project may continue as open-source under acquirer's stewardship (good acquirer) or sunset (bad acquirer)

### If Scenario C — OSS stewardship

- AMP continues as a part-time project, supporting whatever fraction of the agent ecosystem still needs cross-vendor memory
- Slow steady contributor growth
- Project value compounds in the founder's network and credibility

---

## Standards-body engagement strategy

The fastest path to "AMP becomes the standard" runs through three bodies:

### 1. Model Context Protocol working group

MCP is the existing standard for agent-vendor wire formats (tool use, prompts, resources). A "memory extension" to MCP is the most natural standards path.

**Action:** in week 5-6, file an MCP RFC proposing memory extensions. Cite AMP as the reference implementation. The MCP working group meets regularly; engagement is open.

### 2. IETF — Internet-Draft route

For a truly vendor-neutral protocol, IETF is the long-game. Submit as an Internet-Draft (similar to what Cloudflare did with Web Bot Auth → `draft-meunier-web-bot-auth-architecture`).

**Action:** by month 9, submit AMP v0.5 as `draft-<surname>-agent-memory-protocol-00`. Aim for working-group adoption by month 18.

### 3. W3C Community Group

For browser-side agent memory (e.g., AMP-compatible memory in Apple Foundation Models or Google Gemini Nano via the web), W3C Community Group is the right venue.

**Action:** by month 6, propose an "Agent Memory" Community Group. Lower bar than IETF; signals seriousness.

These three bodies cover the three layers: app-level (MCP), wire-protocol (IETF), browser-runtime (W3C). Adopt all three over the year.

---

## Acquisition signals worth monitoring

In order of likelihood:

| Acquirer | Signal | Likelihood |
|----------|--------|------------|
| **Letta** (formerly MemGPT, 21.7k★, well-funded) | They're closest in spirit; an AMP that all their competitors adopt could be a strategic threat OR a strategic acquisition | HIGH (acquihire-shape) |
| **mem0** (51k★, Series A) | Bigger team, more pressure to standardize; could acquire to control the protocol direction | HIGH |
| **Cognee** ($7.5M seed) | Earlier-stage; aligned philosophically; could acquire to expand product surface | MEDIUM |
| **Anthropic** (Claude memory team) | If AMP becomes the cross-vendor standard, Anthropic might want it inside their ecosystem | MEDIUM-LOW |
| **OpenAI** (memory team) | Same logic as Anthropic; lower-likelihood since OpenAI has historically built rather than acquired | LOW |
| **Microsoft** (Azure AI Foundry) | Enterprise positioning aligned; could acquire for the governance/audit Pro tier | LOW-MEDIUM |
| **HuggingFace** (community OSS) | They acquire OSS tools that fit their hub; would prefer contribution over acquisition though | LOW |
| **Foundation-model-adjacent startup** (e.g., Mistral, Cohere, Replicate) | Lower likelihood but possible | LOW |

---

## Pivots if things don't work

### If the spec stalls but the UI sells

- Refocus on the governance UI as the product (instead of the protocol)
- Position as "memory observability and governance for AI agents" — a Sentry-shaped play
- Drop the cross-vendor angle; integrate deeply with whichever 1-2 backends have the most users
- Same playbook as Run 3's "Claude Code Ops" recommendation

### If the protocol succeeds but no UI sales

- Continue as OSS stewardship
- Apply for Mozilla Builders or Sovereign Tech Fund grant
- Use AMP as the credibility artifact for consulting / advisory work on memory-heavy agent projects

### If a foundation-model vendor ships a memory protocol first

- Pivot to "the cross-vendor adapter layer ABOVE [vendor protocol]"
- Same play Cloudflare made with Web Bot Auth (Cloudflare proposed, then sat above other vendors who also implemented)
- AMP becomes a multi-vendor orchestration layer with vendor-specific adapters

### If mem0/Letta ships a competing protocol

- Embrace it as the competitive baseline
- AMP positions as the cross-vendor adapter that works across mem0-protocol + Letta-protocol + AMP-native
- Same outcome: AMP is the layer ABOVE the per-vendor protocols

The single most-important strategic principle: **don't compete on storage, compete on the protocol and governance layer.** Storage is saturated; protocol + governance is the operations layer above.

---

## How to know it's working (every 30 days, check these)

Each is a leading indicator, not a goal:

1. **GitHub stars trending** — 0→50 first week is normal; 50→200 in month 1 is good; 200→1k in month 3 means the bet is landing
2. **Issue/PR engagement quality** — questions about edge cases vs simple bug reports tells you whether power users are arriving
3. **Spec contributions** — first external PR to the spec doc is a stronger signal than 100 stars
4. **Acquirer-side discovery** — first DM or email from someone at Letta/mem0/Cognee/Anthropic is a critical waypoint
5. **Show HN/Reddit second wave** — if a 2nd or 3rd post about AMP appears organically (not from you), the protocol has crossed the awareness threshold

If 3+ of these are positive at the 90-day check, continue. If <2, pivot per the section above.

---

## The longer view: why memory matters

The reason this gap exists isn't an accident. Memory is becoming the defining capability of next-generation agents:

- **Personalization** depends on persistent memory across sessions
- **Multi-agent collaboration** requires shared memory primitives
- **Compliance** (EU AI Act, HIPAA, SOC2) requires auditable memory operations
- **Cost** of AI usage is increasingly bottlenecked by context-window cost; persistent memory reduces re-feeding context

A vendor-neutral protocol that all memory frameworks can agree on is genuinely useful infrastructure. Whether AMP becomes that protocol or merely contributes to the eventual standard, the work is real. The cumulative GapFinder evidence — 4 runs, same pattern, increasing signal strength — is what makes this bet worth taking now.

If you ship v0 in two weeks and it doesn't land, the worst-case is that you have a polished spec, working reference impl, and demo video — which is a substantial portfolio artifact even if the project itself goes dormant. That's the floor.

Above the floor: real protocol adoption, real revenue, real exit. Bet on the floor; play for the ceiling.
