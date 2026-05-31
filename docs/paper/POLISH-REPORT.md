# memorywire Paper Polish Report

**Date:** 2026-05-28
**Source file:** `docs/paper/amp-paper.md`
**Word count:** 9946 (before) Ã¢â€ â€™ 9750 (after) Ã¢â‚¬â€ within the 8500-10000 target.
**Outputs produced:** polished `amp-paper.md`, new `amp-paper.tex`, new `amp.bib`.

## Factual corrections made

1. **`src/memorywire/store/sqlite_vec.py` capabilities.** The Ã‚Â§4.2 table previously
   listed `{semantic, episodic, vector, fts, procedural}`. Code returns
   `{SEMANTIC, EPISODIC, PROCEDURAL, EMOTIONAL, VECTOR, FTS, RECALL_TRACKING}`.
   Table updated.
2. **`src/memorywire/store/cognee_adapter.py` capabilities.** Previously listed as
   `{semantic, graph}`. Actual code returns
   `{SEMANTIC, EPISODIC, VECTOR, GRAPH}`. Table updated.
3. **`src/memorywire/store/pgvector_adapter.py` capabilities.** Previously listed
   `{semantic, episodic, vector, fts}`. Actual code returns
   `{SEMANTIC, EPISODIC, PROCEDURAL, EMOTIONAL, VECTOR, RECALL_TRACKING,
   GOVERNANCE}` Ã¢â‚¬â€ and pgvector docstring explicitly says FTS is absent.
   Table updated.
4. **`src/memorywire/router.py` graph-boost line range.** Paper cited lines 486-503;
   the actual loop is at lines 482-501. Updated.
5. **Code volume estimate.** Ã‚Â§4 previously said "roughly 14k lines of
   Python." Actual non-test source is ~15k lines (8.4k `src/`, 2.4k
   `ui/src/`, 4.2k `scripts/`); ~10k more lines of test code under
   `tests/`. Updated to the more precise breakdown.
6. **Date / version metadata.** Front matter updated to `2026-05-28`,
   status bumped to `v0.2 (polish pass)`.

All other empirical numbers verified against source-of-truth files:

- **Microbenchmark** (recall@5 = 1.000, ingest p50 37.8 ms, recall p50 40.6 ms)
  matches `docs/benchmarks.md`.
- **Adversarial sweep** (RRF flat 1.000 across K=0..50; MAX collapses to
  0.500 with 80% leak at K=5) matches `docs/adversarial-results.rrf.json`
  and `Ã¢â‚¬Â¦max.json` exactly.
- **Conformance matrix** (16 scenarios Ãƒâ€” 5 adapters; per-adapter
  16/13/13/10/16; aggregate 68 PASS / 12 SKIP / 0 FAIL) matches
  `docs/adapters.md` exactly. Number of ProtocolScenario entries in
  `tests/conformance/scenarios.py` = 16 (verified).
- **Commit SHA `c828d76`** still resolves (`fix: 5 critical findings from
  code-review + security-review`). Cited in Ã‚Â§6.5 LaTeX version.

## Tightening pass

- **Ã‚Â§1.3 limitations.** Three paragraphs ("not a new algorithm" / "not an
  LLM contribution" / "not a stabilization paper") merged into a single
  ~140-word paragraph that preserves all three claims and the citations.
- **Ã‚Â§9 conclusion.** Three paragraphs collapsed to two; second paragraph
  merges the "honest bet" framing with the "memorywire is to memory what MCP is
  to tool-use" pull quote.
- **Abstract.** Tightened the K-sweep claim phrasing to match Ã‚Â§5.2
  verbatim ($K \in \{0,5,\dots,50\}$ / $K \geq 5$) and the headline
  recall figure to "1.000 on the 42 labelled queries" (matches Ã‚Â§5.1).

Argument preserved. No technical content changed; no claims weakened;
no new contributions introduced.

## Citation resolution (9 [CITATION NEEDED] markers)

| # | Marker location (line) | Resolution |
|---|---|---|
| 1 | Ã‚Â§2.5 inline (Governed Memory) | **Pinned.** Verified via arxiv.org/abs/2603.17787: Taheri, "Governed Memory: A Production Architecture for Multi-Agent Workflows," 2026-03-18. The YYMM prefix `2603` (March 2026) is unusual but valid. `% TODO verify` comment retained in the .bib for camera-ready double-check. |
| 2 | References preamble meta-note | **Removed.** The "verify every entry" meta-note was deleted now that markers are resolved. |
| 3 | MemGPT venue | **Pinned to arXiv-only.** The arXiv listing for 2310.08560 does not show a final published venue. Cited as arXiv preprint; if it has since published at COLM 2024, the bib entry should be upgraded Ã¢â‚¬â€ `% TODO` left in bib comments. |
| 4 | BEAM canonical reference | **Marked TBD.** No canonical paper located via the available search. The bib entry exists as a placeholder with `note = "Canonical reference TBD"`; the markdown reference lists it as TBD and limits its usage to "future evaluation target only." |
| 5 | Governed Memory arXiv ID | **Verified.** See #1. |
| 6 | mem0 architecture writeup | **Pinned.** Chhikara et al., "Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory," arXiv:2504.19413, 2025. Replaces the placeholder. |
| 7 | MCP specification pin | **Pinned to `2025-11-25`.** Verified via modelcontextprotocol.io/specification. |
| 8 | Cloudflare Web Bot Auth draft revision | **Pinned to draft-05 (2 March 2026).** Verified via datatracker.ietf.org. Authors: Meunier, Ladd. |
| 9 | Author's prior work self-citation | **Removed.** `CITATION.cff` lists no prior publications; we removed the placeholder entry rather than fabricate one. The `@software{amp_protocol}` handle stays at the end of the markdown references as the citation handle for this work itself. |

**Items the user must verify before camera-ready submission:**

- **(BEAM)** The bib entry contains a `% TODO verify canonical reference`
  comment. If a canonical BEAM paper exists, replace the placeholder
  entry; otherwise consider dropping the citation entirely and rewording
  Ã‚Â§5.4 / Ã‚Â§8.1 to drop the BEAM reference.
- **(MemGPT venue)** Confirm whether 2310.08560 was published at COLM
  2024 or another venue. If yes, upgrade `@misc` to `@inproceedings`.
- **(Governed Memory)** Re-fetch arxiv.org/abs/2603.17787 close to
  submission and confirm the listing hasn't moved; `2603` is a valid but
  unusual YYMM prefix.
- **(double-blind)** The submission is currently `\author{Anonymous (...)}` Ã¢â‚¬â€
  swap in the real author block once a venue's policy is known.

## LaTeX format details

- **Document class.** `article` with `[11pt,letterpaper,twocolumn]`.
  `usenix2019_v3.sty` is NOT vendored in this repo; a comment at the top
  of `amp-paper.tex` marks the "USENIX template swap point" so the
  preamble can be replaced verbatim with the USENIX boilerplate before
  submission. The body content uses only portable packages
  (`amsmath`, `booktabs`, `tabularx`, `listings`, `hyperref`, `cleveref`)
  that the USENIX template should accept.
- **Sectioning.** Every `\section`/`\subsection` has a `\label{sec:...}`
  for cross-refs; `\Cref{}` is used throughout for consistent reference
  style.
- **Math.** RRF formula in display math `\[ ... \]`. Inline math uses `$...$`.
- **Tables.** Four `tabular`/`tabularx` tables: types, adapters, microbench
  results, adversarial sweep, conformance matrix.
- **Figure.** `architecture.png` embedded via `\includegraphics[width=\columnwidth]{../architecture.png}`
  (path is relative to the `.tex` file location at `docs/paper/`).
- **Code.** Python protocol block uses `\begin{lstlisting}[language=Python]`.
- **Bibliography.** `\bibliographystyle{plain}` + `\bibliography{memorywire}`.
- **`\citeneeded`.** A red-text macro is defined for any future un-pinned
  citations; not currently used because all body citations are pinned.

## Rendering caveats

- The `..` relative path on the figure (`../architecture.png`) assumes
  `amp-paper.tex` is compiled from `docs/paper/`. If the build is done
  from `docs/`, change to `architecture.png`.
- `cleveref` must be loaded after `hyperref` (already correct).
- The conformance table uses `\checkmark` and `$\square$` symbols; if the
  USENIX template forces a font without these glyphs, replace with `Y` /
  `--` / `X`.
- The `\bibliographystyle{plain}` produces numeric citations; USENIX
  typically prefers `acm` or `IEEEtran` style. Swap when the template
  lands.

## Quality gate evidence

```
$ wc -w docs/paper/amp-paper.md
9750
$ ls docs/paper/
amp-paper.md  amp-paper.tex  amp.bib  POLISH-REPORT.md  eval-protocol.md  user-study/
```

Pytest regression check pending Ã¢â‚¬â€ see follow-on command.
