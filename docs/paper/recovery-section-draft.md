# DRAFT for review — memorywire paper v3 additions (recovery)

> This is a **draft for your review only** — it is NOT in the main paper yet and nothing has been
> submitted to arXiv. Three conservative additions that keep memorywire the headline and add the
> recovery capability + its evaluation. Approve the wording and I'll integrate it into
> `memorywire-paper.md` / `.tex`, regenerate the arXiv bundle, and hand it back for you to upload
> as a v3 replacement.

---

## Addition A — new subsection under §5 (Evaluation): "5.5 Recovery evaluation"

**5.5 Recovery from memory poisoning.** §6.1 notes that memorywire makes malicious writes
*auditable* but cannot prevent a trusted agent from being prompt-injected into planting one. A
natural question follows: once a store is poisoned, can memorywire's `forget` / `expire`
operations *recover* it? We evaluate this with PurgeBench [cite], an external, reproducible
benchmark that poisons an agent memory store with 30 adversarial entries across five classes
(direct, laundered, entangled, dormant, procedural), applies a recovery procedure, and scores the
result on **Recovery-Completeness** — the balanced combination of eradication (ER), utility
retention (UR), and re-emergence resistance (RR), RC = HarmonicMean(ER, UR) × RR, where doing
nothing and wiping the store both score zero by construction.

Run over the reference `SqliteVecStore`, a recovery procedure that purges entries by untrusted
`source` — i.e. memorywire's own provenance field driving `forget` — is the strongest of seven
procedures tested (RC 0.64), eradicating the direct, laundered, dormant, and procedural classes.
This is direct evidence that memorywire's per-entry provenance is not just an audit aid but the
most effective recovery lever measured. Two limits are equally clear. First, the **entangled**
class — a directive embedded inside an otherwise-legitimate, trusted-source memory — defeats every
automatic procedure (0.00 eradication for all non-destructive methods), because removing it also
destroys the benign fact it rides with; this is an open problem, and memorywire's `recover`
tooling (§4.x) handles it by *quarantining* such entries for human review rather than deleting
them. Second, content-anomaly detection alone is insufficient: running the OWASP Agent Memory
Guard content detectors as a recovery procedure scores RC 0.036 (near the do-nothing baseline) on
this *semantic* poison, since those detectors target injection signatures and secret leakage, not
plausible-sounding malicious facts. Provenance and rollback, not content anomaly detection, are
the levers that recover semantic memory poisoning.

---

## Addition B — new subsection under §4 (Reference Implementation): "4.x Recovery tooling"

**4.x Recovery.** The reference implementation ships a `recover` capability (`memorywire recover`
CLI and `memorywire.recovery.Recoverer`) that operationalises the finding above: it purges
untrusted-`source` memories via `forget`, quarantines trusted-source entries whose content matches
a directive heuristic (or a pluggable detector, including OWASP Agent Memory Guard's) via
soft-`forget`, and optionally drops low-confidence rows via `expire`. A `--dry-run` mode previews
every action; purges are restorable soft-deletes by default. Recovery therefore reuses the
existing operation set — no new store primitives — which is what lets it work across every adapter.

---

## Addition C — one sentence in §6.1 (Malicious memory injection), after "auditable, not preventable"

> Recovery *after* such an injection — purging the planted rows and verifying they are gone — is
> evaluated in §5.5 and shipped as the `recover` tool (§4.x); the residual hard case is poison
> entangled with a legitimate trusted memory, which recovery quarantines for human review.

---

## Addition D — one bullet in §8 (Future Work)

> **§8.x Recovery benchmarking.** The `recover` capability is evaluated here against PurgeBench's
> five poison classes; the open frontier is the *entangled* class (a directive fused into a
> trusted memory), where automatic eradication and utility retention are in direct tension. A
> promising direction is span-level revocation that excises the directive while preserving the
> benign remainder of the entry.

---

## Reference to add to the bibliography

Munirathinam, T. (2026). *PurgeBench: A Benchmark and Metric for Adversarial Memory-Poison Recovery
in LLM Agents.* Zenodo. https://doi.org/10.5281/zenodo.21379140

---

### Why this is a safe v3 replacement
- memorywire stays the paper's subject; recovery is an *application/evaluation* of its existing
  `forget`/`expire`/`source`, not a new paper.
- Additions are one Evaluation subsection, one Implementation subsection, one threat-model
  sentence, one future-work bullet, one citation — the shape of a normal revision.
- Title, abstract, and primary category (cs.CR / cs.AI) are unchanged.
