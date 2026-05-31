# DM target list

20 people to reach personally once the arXiv announcement is
live and the Show HN / Twitter thread has been up for 24+ hours.

**Rules of engagement:**

1. **Pace yourself.** 3-4 DMs per day spread over 5-7 days.
   Sending 20 in one hour looks like a mass-mail and gets
   flagged on most platforms.
2. **Open with a reference to their published work.** Never
   "Hi I saw your project". Specifically: a line from a blog
   post, a feature in a recent release, a tweet they posted in
   the last 4 weeks.
3. **One ask per DM.** Either "would you look at the spec" OR
   "would you accept an adapter PR" â€” never both.
4. **No upvote requests, no boosts, no quote-RT favours.** Ask
   for technical engagement only.
5. **If they don't reply within 7 days, do not chase.**

---

## Tier 1 â€” Memory framework maintainers (file PRs first, then DM)

These four are the highest-priority targets per
`docs/kickoff/PROJECT-PLAN.md`. Maintainer engagement is the
strongest validation signal in week 1-4.

### 1. Charles Packer â€” Letta (formerly MemGPT)
- Handle: `@charlespacker` (X), `cpacker` (GitHub)
- Why: founder of Letta; MemGPT was the architecture that
  made hierarchical agent memory a category. Letta is the
  21.7kâ˜… framework in the memorywire comparison table.
- Opener hook: cite the MemGPT paper or a recent Letta
  release note.
- Ask: would you look at `src/memorywire/store/letta_adapter.py`
  and tell me if the tag-encoded memorywire metadata pattern is
  the right shape, or if Letta v2 has a free-form metadata
  field I should use instead.

### 2. Taranjeet Singh â€” mem0
- Handle: `@taranjeetio` (X), `taranjeet` (GitHub)
- Why: co-founder of mem0; 51kâ˜… + Series A. The most-cited
  framework in the abstract.
- Opener hook: the mem0 architecture writeup
  (arXiv:2504.19413) or a recent Slack/Discord launch.
- Ask: feedback on whether memorywire's `MemoryStore` Protocol
  can be implemented as a thin layer ON TOP of the mem0
  Python SDK without forking â€” the current adapter wraps
  the client; v0.2 could go deeper.

### 3. Vasilije Markovic â€” Cognee
- Handle: `@vasilije1990` (X), `Vasilije1990` (GitHub)
- Why: founder of Cognee ($7.5M seed). Cognee is the only
  graph-first system in memorywire's adapter set; the SKIP cells
  in the conformance suite all flag Cognee's data_id surface.
- Opener hook: the Cognee 1.1 release or a graph-completion
  blog post.
- Ask: would Cognee expose per-record IDs (the v0.2 spec-
  tightening signal from the conformance suite Â§5.3) â€” and
  if not, what's the workaround for the synthetic `cog:`
  ID problem.

### 4. Daniel Chalef â€” Zep / Graphiti
- Handle: `@danielchalef` (X)
- Why: founder of Zep + Graphiti. memorywire's RRF k=60 fusion is
  the same recipe Graphiti uses.
- Opener hook: Graphiti's temporal-knowledge-graph paper
  or a recent Zep release.
- Ask: would you accept a `memorywire.store.zep_adapter` PR for
  v0.2 â€” the conformance suite would gain a 6th column.

---

## Tier 2 â€” Foundation-model memory teams

These are the highest-leverage hire-me targets if the OSS
path doesn't convert. Per `docs/kickoff/FUTURE.md`.

### 5. Anthropic â€” Claude Memory team
- Look up: the engineer who shipped Claude's Projects
  memory feature or the "Skills" launch.
- Handle: usually findable via Anthropic's "Meet the team"
  page or recent blog post bylines.
- Opener hook: a specific Anthropic blog post on memory.
- Ask: feedback on memorywire's positioning relative to MCP, since
  Anthropic is the MCP author. memorywire is downstream / extension.

### 6. OpenAI â€” Memory team
- Same shape as #5. Find the engineer behind ChatGPT's
  cross-session memory feature.
- Opener hook: a specific OpenAI release note or X thread.
- Ask: is memorywire's 4-type taxonomy compatible with whatever
  ChatGPT memory's internal type system looks like, and
  would a public-facing protocol be useful.

### 7. Microsoft â€” Azure AI Foundry Memory team
- Microsoft has shipped enterprise governance for memory in
  Azure AI Foundry. The PM or eng-lead is the right target.
- Opener hook: a specific Foundry release.
- Ask: feedback on memorywire's governance UI as a model for
  what an enterprise-tier memory audit surface should
  look like.

### 8. Google â€” ADK Memory team
- Google's Agent Development Kit (ADK) has a memory
  primitive. Look up the ADK team leads.
- Opener hook: a specific ADK release.
- Ask: would the ADK memory API benefit from a wire-format
  layer, or is it intentionally proprietary.

---

## Tier 3 â€” Standards-body engagement

Per `docs/kickoff/FUTURE.md` the standards path runs through
three bodies. These three contacts are the highest leverage.

### 9. MCP working-group leads (Anthropic-side)
- Per the MCP specification, the spec authors are listed in
  the spec repo's CODEOWNERS. Target whoever is most active
  on memory-related issues in the MCP-WG GitHub.
- Opener hook: the MCP spec section on resources /
  prompts (the closest existing surface to memory).
- Ask: would the MCP-WG accept a memory-extension proposal
  citing memorywire as the reference impl, or is there a different
  shape they'd prefer.

### 10. IETF â€” applicable working group
- memorywire's intended IETF home is either
  `httpapi` (REST-shaped JSON-Schema APIs) or `core` (constrained
  applications). Find the WG chair via the IETF datatracker.
- Opener hook: nothing â€” IETF DMs are usually cold and
  context-free is normal. Reference Cloudflare's
  Web-Bot-Auth Internet-Draft (draft-meunier-web-bot-auth-
  architecture-05) as the precedent for a startup-shipped
  protocol going through IETF.
- Ask: would memorywire's v0.5 spec be in scope for an Internet-
  Draft submission to your WG.

### 11. W3C â€” Community Group sponsor
- W3C has lightweight "Community Groups" that don't
  require IETF-level commitment. The W3C CG chair for
  AI / agents is the right contact.
- Opener hook: a recent W3C announcement on AI / agents.
- Ask: would you sponsor an "Agent Memory" Community
  Group with memorywire as the founding submission.

---

## Tier 4 â€” Adjacent ecosystem (lower priority, higher count)

These are LOW-LIKELIHOOD targets but the bar is also lower
(any one of them replying is a small win).

### 12. HuggingFace â€” community OSS team
- Acquires OSS tools that fit the Hub.
- Opener hook: a recent HF release.
- Ask: would memorywire fit as a `pip install huggingface-memorywire`
  shim or as a Spaces template.

### 13. Mistral
- Foundation-model adjacent; may want a memory story.
- Opener hook: Mistral's most recent release.

### 14. Cohere
- Foundation-model adjacent; enterprise positioning.
- Opener hook: Cohere's most recent release.

### 15. Replicate
- Cohort of OSS-friendly model-hosting; could host a
  reference Memory deployment.

---

## Tier 5 â€” Researchers + thinkers (no ask, just signal)

These five are not commercial targets but their public
reaction (or silence) is a strong signal. Don't ask
anything â€” just send the arXiv link with one line of
context.

### 16. Andrej Karpathy â€” `@karpathy`
- Has tweeted about memory + agents repeatedly. A like is
  signal; a quote-RT is gold.

### 17. Sebastian Raschka â€” `@rasbt`
- LLM systems writer; has covered agent infra in the past.

### 18. Jeremy Howard â€” `@jeremyphoward`
- fast.ai founder; pragmatic-systems sensibility matches memorywire.

### 19. Simon Willison â€” `@simonw`
- LLM bloggerati; writes detailed posts on the agent
  ecosystem. memorywire fits his beat exactly.

### 20. Latent Space podcast (`@swyx`, `@alessiofanelli`)
- The agent-infra podcast. A mention on Latent Space is
  worth 1000 generic RTs.

---

## Template DM (use as starting point, ADAPT PER PERSON)

```
Hi <NAME>,

Saw <specific reference to their published work â€” paper / blog / tweet from last 4 weeks>.

I just released an arXiv preprint that intersects with what you're shipping: memorywire, a vendor-neutral wire format for agent memory operations. The reference implementation includes <ONE OF: a Letta adapter / a mem0 adapter / a Cognee adapter / a Zep adapter / nothing yet for your work but should â€” drop in the specific surface to their work here>.

The contribution is a protocol + reference impl + governance UI; the framing is "the cross-vendor layer above storage", positioned to compose with MCP. Honest framing on novelty â€” not an algorithmic contribution, packaging + standards positioning.

arXiv: https://arxiv.org/abs/<ARXIV_ID>
Code: https://github.com/mthamil107/memorywire

Would value your feedback on <ONE SPECIFIC TECHNICAL QUESTION related to their work>. No rush; if it's not in your queue right now, fine.

â€” Thamilvendhan
```

---

## Tracking

Suggest a simple Notion / Airtable / Google Sheet with these
columns:

| Name | Platform | Date Sent | Status | Reply Date | Notes |

Mark `Status` as `sent / read / replied / ignored / engaged`. After
30 days, count the engaged rows â€” that's your week-4 success
metric per `docs/kickoff/PROJECT-PLAN.md`.

Target metric (per the kickoff):

> â‰¥1 of mem0/Letta/Cognee accepted (or substantively engaged on)
> the adapter PR; â‰¥3 first-round interviews scheduled with target
> memory teams; â‰¥1 spec comment from someone at
> OpenAI/Anthropic/Google/Microsoft memory teams.
