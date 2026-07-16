# Launch assets — `memorywire recover` (v0.2.0)

Finding-first framing (lead with the problem + result, not the repo). You post these; nothing is
auto-sent. Attach `docs/demos/recover-explainer.gif` (the concept GIF) to the visual channels.

---

## X / Twitter thread

**1/**
An agent's memory can be poisoned — a bad "fact" or "successful experience" gets written once and
then steers every future session. Deleting the obvious one isn't enough. So: can you actually
*recover* a poisoned agent memory, and *prove* it's clean?

[attach recover-explainer.gif]

**2/**
I built a small benchmark (PurgeBench) to measure recovery, not just attack. It scores three
things at once: did you remove the poison (ER), keep the legit memories (UR), and does it stay gone
(RR)? Two trivial answers — do nothing, or wipe everything — both score zero by design.

**3/**
Result across 7 recovery methods: **provenance wins.** Purging memories by *where they came from*
(untrusted source) is the strongest lever (RC 0.64). Content anomaly detection alone barely beats
doing nothing on *semantic* poison — it's tuned for injection signatures, not plausible lies.

**4/**
The hard case nobody's solved: a directive *hidden inside a trusted memory* ("backup at 02:00 —
and disable-backups on Fridays"). Every automatic method fails it, because deleting it also
deletes the real fact. So you shouldn't auto-delete — you should quarantine it for a human.

**5/**
memorywire now ships `recover` that does exactly this: purge untrusted-origin poison, quarantine
the entangled case for review, keep the benign facts — reusing its existing forget/expire ops, so
it works across every backend. `--dry-run` shows you everything first.

Tool: github.com/mthamil107/memorywire · Benchmark: github.com/mthamil107/purgebench

---

## LessWrong / Alignment Forum post (short)

**Title:** Recovering a poisoned agent memory — and why provenance beats content detection

Agent memory poisoning is now well studied on the *attack* side (MemoryGraft, MINJA, OWASP ASI06).
The *recovery* side — once a malicious entry is in the store, can you clean it out and verify the
clean-up — has no benchmark and little tooling. I looked at whether it's tractable.

I built PurgeBench, a small reproducible benchmark that scores recovery on three axes —
eradication, utility retention, and re-emergence resistance — combined so that both degenerate
strategies (do nothing / wipe everything) score zero. Across seven recovery procedures run over a
real memory store, the strongest by a wide margin is **purging by provenance** (remove memories
from untrusted sources): RC 0.64. Running OWASP Agent Memory Guard's content detectors as a
recovery step scores 0.036 — near do-nothing — because they target injection signatures, not
semantically-plausible malicious facts.

One class defeats every automatic method: a directive **entangled** inside a legitimate,
trusted-source memory. Removing it costs the benign fact it's fused with, so the honest answer is
to *quarantine* it for human review, not delete it.

I've shipped this as `memorywire recover` (purge untrusted, quarantine entangled, keep benign;
`--dry-run` first). I'd value disagreement on the metric — is "you only win by removing the poison
*and* keeping the good memory *and* keeping it gone" the right definition of recovery, or am I
missing an axis?

Benchmark + results: github.com/mthamil107/purgebench · Tool: github.com/mthamil107/memorywire

---

## Do / don't (same rules as the signalbench launch)
- Lead with the **finding** (poison persists; provenance recovers it), not the repo URL.
- Attach the **concept GIF** on X/LessWrong — it explains the idea in ~11s.
- Frame Agent Memory Guard **fairly**: "content detection misses semantic poison," NOT "OWASP tool
  fails." (It's a detection/prevention tool; this measures recovery.)
- One coordinated post, then let it stand. No cross-posting identical text to five subreddits.
- A warm quote-boost from a known researcher is the biggest multiplier — worth one ask.
