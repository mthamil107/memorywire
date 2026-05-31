# LinkedIn launch post â€” corrected framing

This version is post-AI-feedback (May 31 review). The earlier draft
implied research novelty on the adversarial-fusion experiment;
Byzantine-robust aggregation is a real, well-developed field
(Lamport/Pease/Shostak 1982, Blanchard et al. 2017's Krum,
Yin et al. 2018, Pillutla et al. 2022) that memorywire's Â§5.2 measures
*within* rather than discovers. So this post leads with the
engineering / tool framing â€” "tool I needed and couldn't find" â€”
and saves the protocol-as-published-artifact claim for the closing
line where it can stand on its own.

Length: ~290 words, ~1,950 characters. Pure ASCII. No em-dashes
that LinkedIn renders as `?`.

## Step 1 â€” Open the LinkedIn composer

Click "Start a post" on the LinkedIn home feed.

## Step 2 â€” Attach the GIF

Click the image-attach icon and upload:

```
D:/Repo/agent-memory/docs/demos/memorywire-explainer.gif
```

The GIF (~1 MB, 1080x1080, ~6 seconds, loops) shows the islanded-
frameworks-then-memorywire-layer-then-governance-UI storyboard in plain
visual terms.

## Step 3 â€” Paste this verbatim into the text field

```
Just open-sourced memorywire â€” a vendor-neutral wire format for agent memory operations.

Every framework I tried to use across multiple agent projects â€” mem0, Letta, Cognee, Zep, MemoryOS â€” ships its own SDK, its own storage layout, and its own operational vocabulary. There is no shared wire format. Every migration rebuilds memory from scratch. And none of them ship a governance surface where a human can review what the agent is about to remember BEFORE it enters long-term storage.

This is not a novel-research claim. It is a tool I needed for a real project and could not find. So I built it.

What ships today:

- Five memory operations (remember, recall, forget, merge, expire) over four memory types (semantic, episodic, procedural, emotional), specified as JSON Schema 2020-12.
- A Python reference implementation (~15k lines, 380+ tests) with five day-1 backend adapters: sqlite-vec, mem0, Letta, Cognee, and pgvector.
- A fan-out memory router that fuses results across N backends via Reciprocal Rank Fusion (k=60).
- A governance UI (Starlette + HTMX) for the diff-and-approve workflow.
- A six-adversary threat model mapped to OWASP and CWE.

A 9,760-word arXiv preprint covers all of it. The public arXiv ID lands Monday US-evening when the announcement window opens; until then the paper source lives in the repo at /docs/paper/.

This is a companion to my earlier arXiv:2604.18248 (Prompt Injection Detection) â€” same threat-class lens applied to memory-side injection.

Code (Apache-2.0 for the protocol; FSL for the governance UI):
https://github.com/mthamil107/memorywire

Naming note: there is a prior project called AMP at github.com/akshayaggarwal99/amp (an MCP-native memory server with visualizations). This is a different shape â€” a vendor-neutral wire format and spec + 5 backend adapters. Renamed to memorywire before launch to avoid confusion. See docs/PRIOR-WORK.md for the long version.

Curious what folks at memory-framework teams and the MCP working group make of it. memorywire is designed to compose with what you ship, not against it.

#AI #AgentMemory #OpenSource #Protocols #Security
```

## Step 4 â€” Click Post

That's it. No external URL preview tricks, no hashtag stuffing
past five.

---

## Why this version is different from v1

| Change | Why |
|---|---|
| Drops the word "novel" entirely | AI feedback (May 31): Byzantine-robust aggregation is the prior-art field for Â§5.2; "novel" overclaimed |
| Adds "It is not a novel-research claim. It is a tool I needed for a real project and could not find. So I built it." as the second paragraph | Disarms the reviewer reflex; reframes contribution as engineering / OSS, not research; sells better on LinkedIn anyway |
| Removes the "Adversarial-fusion experiment showing RRF holds" bullet | The implicit research framing on Â§5.2 is gone; the result still lives in the paper but doesn't need to lead on LinkedIn |
| Keeps the Conformance / Threat-model / Microbench bullets | These are honest engineering deliverables; the conformance suite IS genuinely useful as protocol-validation evidence |
| Closing line emphasises "compose with, not against" | Honest positioning on memorywire-vs-MCP and memorywire-vs-frameworks; consistent with docs/MCP-RELATIONSHIP.md |

## Optional follow-up comment

Once the post is live, add this as the first comment from your own
account within five minutes. LinkedIn's algorithm boosts posts
where the author engages within the first hour.

```
For folks who want the technical deep-dive:

- docs/spec/v0.md in the repo is the full JSON Schema specification
- docs/THREATS.md is the threat model with line-level mitigation citations
- docs/MCP-RELATIONSHIP.md is the memorywire-vs-MCP positioning if you want the answer to "why not just an MCP extension?" before clicking through

The memorywire-MCP relationship doc and the threat model are the two artifacts I'd point a reviewer at first.
```

## Best posting time

Tuesday / Wednesday / Thursday, 10 AM â€“ 2 PM US Eastern. Friday
afternoon and weekend posts underperform on LinkedIn by ~50% per
LinkedIn's own algorithm bias. If you post outside that window
anyway, it still works â€” just expect roughly half the reach.

## After posting

Set a 90-minute timer. LinkedIn rewards author replies to comments
in the first 90 minutes. Reply to every comment with at least one
sentence â€” even "Thanks, will follow up via DM" counts. The
algorithm uses "reply rate" as a signal for "post quality".

Paste the live post URL back to the orchestrator after posting and
the next platform (Twitter thread) gets wired up to reference it.
