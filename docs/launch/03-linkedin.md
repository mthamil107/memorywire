# LinkedIn long-form post

LinkedIn rewards posts in the 1,200-1,800 character range
(roughly 200-300 words). The version below is ~290 words /
1,750 chars. Substitute `<ARXIV_ID>` before posting.

LinkedIn does NOT auto-render markdown. Paste as plain text
with one blank line between paragraphs. Hyperlinks in plain
text are auto-detected.

---

## Post body

```
New arXiv preprint: AMP — a vendor-neutral wire format for agent memory operations.

The problem: every agent-memory framework I tested (mem0 51k★, Letta 21.7k★, Cognee, Zep, MemoryOS) ships its own SDK, storage layout, and operational vocabulary. There is no shared wire format. Every migration rebuilds memory from scratch. And no framework ships a governance surface — a place where a human reviews what the agent is about to remember, BEFORE it enters long-term storage.

AMP is the protocol layer above storage. Five operations (remember, recall, forget, merge, expire) over four memory types (semantic, episodic, procedural, emotional), with a MemoryStore interface, a fan-out router that fuses results via Reciprocal Rank Fusion, and an optional human-in-the-loop diff-and-approve channel.

The preprint ships a reference Python implementation with five day-1 backend adapters (sqlite-vec, mem0, Letta, Cognee, pgvector); a microbench showing recall@5 = 1.000 on a labelled corpus; an adversarial-fusion experiment where RRF holds against a 1-of-N rank-0 injection attack across the full sweep; a 16-scenario cross-adapter conformance suite (68/80 PASS); a six-adversary threat model mapped to OWASP and CWE; and preliminary LongMemEval + LoCoMo numbers.

The contribution is not a new algorithm — RRF, FSMs, STM/LTM consolidation are all prior art — it's a venue-neutral protocol with an empirically validated reference, positioned to compose with MCP rather than compete with it.

Companion to my earlier arxiv:2604.18248 (Prompt Injection Detection). Same threat-class lens, applied to memory-side injection.

Paper: https://arxiv.org/abs/<ARXIV_ID>
Code (Apache-2.0): https://github.com/mthamil107/agent-memory-protocol

Curious what folks at memory-framework teams and the MCP working group think — AMP composes with what you're shipping, not against it.

#AI #AgentMemory #OpenSource #Protocols #Security
```

---

## Notes

- Lead with "New arXiv preprint" — LinkedIn's first 200 chars
  determine the See-More cutoff; you want the hook above the
  fold.
- The 5 hashtags at the end are the LinkedIn max-effective
  set. Beyond 5 the algorithm de-weights.
- DO NOT include external image attachments. LinkedIn
  de-prioritizes posts with images that link off-platform.
  Plain text + arXiv link is the right choice here.
- DO post during US business hours (10 AM - 2 PM Eastern) on
  Tuesday / Wednesday / Thursday. Mon AM and Fri PM are dead.
