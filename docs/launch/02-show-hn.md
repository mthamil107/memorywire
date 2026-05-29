# Show HN post

Submit at <https://news.ycombinator.com/submit>. Substitute
`<ARXIV_ID>` with the real `2605.NNNNN`.

The Show HN format: title must start with `Show HN:`. The URL
field points to either the arXiv abstract page OR the repo —
**use the arXiv page** (more "showable" than a repo). Put the
repo link in the first comment.

---

## Title (80-char limit)

```
Show HN: AMP – a vendor-neutral wire format for agent memory operations
```

(74 chars; fits.)

## URL field

```
https://arxiv.org/abs/<ARXIV_ID>
```

## Text field

**Leave blank.** Show HN posts with a URL should put the
description in the first comment, not the text field. The
title plus the linked artifact carry the post; the comment
gives context.

## First comment (post this within 30 seconds of submitting)

```
Hi HN — author here.

The pitch in one line: every agent-memory framework today (mem0,
Letta, Cognee, Zep, MemoryOS) stores memories in its own format,
and none of them ship a governance surface that lets a human
review writes before they enter long-term storage. AMP is the
layer above them — five operations (remember, recall, forget,
merge, expire), four memory types (semantic, episodic,
procedural, emotional), a memory router that fuses results
across backends via RRF, and an optional human-in-the-loop
diff-and-approve channel.

Concrete artifacts:

- Spec: JSON-Schema 2020-12 with 12 schemas + 15 worked examples
- Reference Python implementation, ~15k lines, 380+ unit tests
- Five day-1 backend adapters (sqlite-vec, mem0, Letta, Cognee, pgvector)
- Governance UI (Starlette + HTMX) for the diff-and-approve flow
- Microbench: recall@5 = 1.000 on a 100-fact / 50-query corpus
- Adversarial fusion experiment: RRF holds against 1-of-N rank-0
  injection across the full attack budget I swept; MAX fusion
  collapses to 0.500 with 80% leak
- 16-scenario cross-adapter conformance suite passing 68/80 cells
- Six-adversary threat model with line-level code citations
- Preliminary LongMemEval + LoCoMo numbers under a real grader

What this is NOT: a new algorithm. RRF is from Cormack et al.
2009; the four-type taxonomy is from Tulving 1972; FSMs are
from pytransitions; STM/LTM consolidation predates the
frameworks I cite. The contribution is composition + a
venue-neutral protocol with an empirically validated reference,
positioned to compose with MCP rather than compete with it.

Companion paper to my earlier arXiv:2604.18248 (Prompt
Injection Detection) — same threat-class lens, applied to
memory-side injection rather than prompt-side.

Repo (Apache-2.0 for the protocol, FSL for the governance UI):
https://github.com/mthamil107/agent-memory-protocol

Honest about what's not there: full 5-seed × 200-question
LongMemEval / LoCoMo runs are deferred to a v2 replacement on
arXiv — the per-question Memory construction pattern that
protects against cross-question contamination costs ~30-45 s
per iteration in CPU-only inference, which extrapolates to ~12
hours wall time. The harness exists; the wall time doesn't.

Happy to answer questions about the protocol design, the
conformance suite results (especially the 12 SKIP cells which
are v0.2 spec-tightening signals), the threat model, or how
AMP composes with MCP.
```

---

## Posting strategy

- **Best time:** Tuesday or Wednesday, 7:00-9:00 AM Pacific
  (the canonical Show HN sweet spot). Avoid Friday afternoon
  and Sunday — the algorithm de-weights weekend posts.
- **Reply window:** the first 6 hours determine front-page
  placement. Plan to be at a keyboard for those 6 hours.
- **Do not** ask friends to upvote. HN bans this and it's
  detectable.
- **Do** engage every substantive comment, even the critical
  ones. Especially the critical ones — the algorithm rewards
  thread depth.

## If the post gets traction (>100 points / >50 comments)

Cross-post (NOT cross-spam) to:

- `r/MachineLearning` (self-post; describe the work, link arXiv + repo)
- `r/LocalLLaMA` (different framing: "I built a cross-vendor
  memory layer for local LLM agents — would love feedback")
- `r/programming` (lighter, infra-friendly framing)

Stagger by 2+ hours between subreddits.

## If the post stalls (<10 points after 2 hours)

Do not delete. Do not edit. Do not re-submit. HN treats
re-submission as spam and shadow-flags subsequent attempts.

Just leave it and pivot to the Twitter thread.
