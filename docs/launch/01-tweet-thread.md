# Twitter / X launch thread

Substitute `<ARXIV_ID>` with the real `2605.NNNNN` before posting.
Substitute `<HN_URL>` with the Show HN URL once it's live.

Post in order. Wait ~30 seconds between tweets so the thread
linker resolves cleanly. Tag the four handles only in tweet 6
(tagging earlier triggers X's "tagging in OP" rate limits).

---

## 1/6

```
Every agent-memory framework today (mem0, Letta, Cognee, Zep, MemoryOS) stores memories in its own format. No shared wire format. No diff-and-approve surface.

I drafted the protocol that's missing and built a reference implementation. arXiv preprint:

https://arxiv.org/abs/<ARXIV_ID>
```

## 2/6

```
memwire is the layer above storage frameworks.

5 operations (remember / recall / forget / merge / expire).
4 memory types (semantic / episodic / procedural / emotional).
5 day-1 backend adapters (sqlite-vec, mem0, Letta, Cognee, pgvector).

Designed to compose with what you ship, not compete with it.
```

## 3/6

```
Empirical numbers in the paper:

â€¢ Microbench: recall@5 = 1.000 / ingest p50 37.8 ms / recall p50 40.6 ms
â€¢ Conformance: 16 scenarios Ã— 5 adapters â†’ 68/12/0 PASS/SKIP/FAIL
â€¢ Preliminary LongMemEval + LoCoMo numbers in Â§5.6
```

## 4/6

```
The piece I leaned on most: every remember() can stage behind a human-review queue with a structured diff against current memory state. The Co-memorize / Governed Memory pattern, productized.

Full threat model in the paper Â§6 â€” 6 adversaries mapped to OWASP + CWE.
```

## 5/6

```
This is a companion paper to my earlier arxiv:2604.18248 (Prompt Injection Detection).

Same threat-class lens, different vector: prompt-side injection vs memory-side injection. memwire's THREATS.md Â§3.1 names malicious memory injection as adversary 1.

Memory is where prompt injection becomes persistent.
```

## 6/6

```
Code, datasets, conformance suite, threat model, deployment scaffold, paper source: 

https://github.com/mthamil107/memwire

Discussion on HN: <HN_URL>

Curious what @charlespacker @taranjeetio @vasilije1990 think â€” memwire composes with your frameworks, not against them.
```

---

## Alternative shorter version (3 tweets if you want lower commitment)

### 1/3
```
New arXiv preprint: memwire â€” a vendor-neutral wire format for agent memory operations. 5 operations, 4 types, 5 backend adapters, a router, and a governance UI for diff-and-approve workflows on what agents remember.

https://arxiv.org/abs/<ARXIV_ID>
```

### 2/3
```
Headline: every agent-memory framework today stores memories in its own format, and none ship a human-review surface for memory writes. memwire fixes the protocol gap and ships a reference implementation with five adapters (sqlite-vec, mem0, Letta, Cognee, pgvector).
```

### 3/3
```
Code + datasets + threat model + 16-scenario conformance suite: https://github.com/mthamil107/memwire

Show HN: <HN_URL>

Companion to my earlier arxiv:2604.18248 (Prompt Injection Detection). Same threat-class lens, applied to memory.
```

---

## Notes for the author

- The 6-tweet version is the recommended default. The 3-tweet version is a fallback if you want lower visibility / less commitment.
- Tag the maintainers ONLY in the final tweet. Tagging earlier triggers X's notification dampening for "tags in opening tweet".
- Pin tweet 1/6 to your profile for the first 72 hours.
- Do NOT quote-RT yourself to boost.
