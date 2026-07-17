# Launch assets — memorywire `recover` (finalized)

Finding-first. You post these; nothing auto-sends. Attach the concept GIF
(`docs/demos/recover-explainer.gif`) on the visual channels. Point everything at the durable
landing page, not a raw repo:

**Landing page:** https://mthamil107.github.io/writing/memorywire-recover.html

The arXiv paper is `arXiv:2606.01138` (the ID is stable across versions; the recovery section is in
v3). Fire after v3 shows as posted.

---

## X / Twitter thread

**1/**
An AI agent's memory can be poisoned &mdash; a fake "fact" or a fake "successful experience" gets
written once and then quietly steers every future session. Deleting the obvious one isn't enough.
So: can you actually *recover* a poisoned agent memory, and *prove* it's clean?

[attach memorywire-recover.gif]

**2/**
I built a benchmark (PurgeBench) to measure recovery, not just attack. It scores three things at
once: did you remove the poison (ER), keep the legit memories (UR), and does it stay gone (RR)?
The two lazy answers &mdash; do nothing, or wipe everything &mdash; both score zero by design.

**3/**
Result across 7 recovery methods: **provenance wins.** Purging memory by *where it came from*
(untrusted source) is the strongest lever (RC 0.64). Content anomaly detection barely beats doing
nothing (0.036) &mdash; a plausible-sounding lie isn't an "anomaly."

**4/**
The hard case nobody's solved: a directive *hidden inside a trusted memory* ("backup at 02:00 &mdash;
and disable-backups on Fridays"). Every automatic method fails it, because deleting it also deletes
the real fact. So you shouldn't auto-delete &mdash; you quarantine it for a human.

**5/**
memorywire ships this as `recover`, and it works in **any MCP agent** (Claude Desktop, IDE
assistants) by config &mdash; no code:

`pip install "memorywire[mcp,sqlite-vec]"`

Writeup + benchmark + how to use it: https://mthamil107.github.io/writing/memorywire-recover.html

---

## LessWrong / Alignment Forum post

**Title:** Recovering a poisoned agent memory &mdash; and why provenance beats content detection

Agent memory poisoning is well studied on the *attack* side (MemoryGraft, MINJA, OWASP ASI06). The
*recovery* side &mdash; once a malicious entry is in the store, can you clean it out and verify the
clean-up &mdash; had no benchmark and little tooling. I looked at whether it's tractable.

I built PurgeBench, a small reproducible benchmark that scores recovery on three axes &mdash;
eradication, utility retention, and re-emergence resistance &mdash; combined so both degenerate
strategies (do nothing / wipe everything) score zero. Across seven recovery procedures over a real
memory store, the strongest by a wide margin is **purging by provenance** (remove memories from
untrusted sources): RC 0.64. Running OWASP Agent Memory Guard's content detectors as a recovery
step scores 0.036 &mdash; near do-nothing &mdash; because they target injection signatures, not
semantically-plausible malicious facts.

One class defeats every automatic method: a directive **entangled** inside a legitimate,
trusted-source memory. Removing it costs the benign fact it's fused with, so the honest answer is to
*quarantine* it for human review, not delete it.

I shipped this as `memorywire recover` (`pip install memorywire`; also an MCP server so any MCP
agent gets it by config). I'd value disagreement on the metric &mdash; is "you only win by removing
the poison *and* keeping the good memory *and* keeping it gone" the right definition of recovery, or
am I missing an axis?

Writeup, benchmark, and results: https://mthamil107.github.io/writing/memorywire-recover.html ·
Paper: arXiv:2606.01138

---

## Do / don't
- Lead with the **finding** (poison persists; provenance recovers it), not the repo URL. Link the
  **landing page** as the "full writeup."
- Attach the **concept GIF** on X/LessWrong &mdash; it explains the idea in ~11s.
- Frame Agent Memory Guard **fairly**: "content detection misses semantic poison," NOT "OWASP tool
  fails." It's a detection/prevention tool; this measures recovery.
- One coordinated post per channel the same day, then let it stand. No identical cross-posts to five
  subreddits.
- A warm quote-boost from a known researcher is the biggest multiplier &mdash; worth one ask.
- Fire only **after** the arXiv v3 shows as posted, so the paper link is live.
