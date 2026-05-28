# AMP — arXiv submission bundle

This directory contains everything arXiv needs to compile the AMP paper PDF server-side. No local LaTeX install required — arXiv builds the PDF for you from this source.

## Files

| File | Purpose |
|---|---|
| `amp-paper.tex` | Main paper source (~73 KB, 9,760 words; USENIX-template-shaped, article-class fallback) |
| `amp.bib` | BibTeX bibliography (13 entries; 8 pinned to real refs, 1 BEAM marked as TBD) |
| `architecture.png` | Figure 1 (1200×675, 50 KB) |

## How to submit (~10 min on the arXiv side)

1. Go to <https://arxiv.org/submit>. Log in (or sign up — needs endorsement first time; M. Thamil's account, request endorsement from any existing cs.DC arXiv author).
2. **Type of submission:** New submission.
3. **License:** Recommend `CC BY 4.0` (matches the Apache-2.0 + FSL split of the codebase ethos; allows derivative works with attribution).
4. **Archive:** `cs` (Computing Research Repository).
5. **Primary category:** `cs.DC` (Distributed, Parallel, and Cluster Computing).
6. **Secondary categories:** `cs.AI`, `cs.SE`.
7. **Upload files:** Tar/zip this entire directory (`arxiv-submission/`) and upload. arXiv accepts:
   - `.tex` (main source)
   - `.bib` (bibliography)
   - `.png` (figure)
   - Everything in one flat tarball
   - Total under 50 MB (we're at ~127 KB, well under).
8. **Compile:** arXiv runs `pdflatex` + `bibtex` + `pdflatex` × 2 server-side. Check the auto-generated PDF preview.
9. **Title:** `AMP: A Vendor-Neutral Wire Format for Agent Memory Operations`.
10. **Abstract:** Copy from the `\begin{abstract} ... \end{abstract}` block of `amp-paper.tex` (lines ~60-83). arXiv has a 1920-char limit; the polished abstract fits.
11. **Authors:** `M. Thamil` · email `mthamil107@gmail.com` · affiliation `Independent Researcher`.
12. **Submit.** arXiv announces new papers Mon-Thu evenings (Eastern Time). Submission today (Thursday) → public announcement typically same evening or Monday morning.

## Quick sanity checks before uploading

```bash
# If you have LaTeX installed locally, smoke-compile:
pdflatex amp-paper && bibtex amp-paper && pdflatex amp-paper && pdflatex amp-paper

# Check the figure path resolves
grep -c "includegraphics" amp-paper.tex   # should be 1

# Check the .bib is reachable
grep -c "@" amp.bib                        # should be 13
```

If you don't have a LaTeX install, **skip the local smoke** — arXiv will compile and surface any issues in the preview step before you click "Submit".

## What's not in this bundle (and why that's OK for a preprint)

- **BEAM benchmark citation** is marked `% TODO verify` in `amp.bib`. arXiv accepts preprints with TBD citations; you can replace this with a v2 of the preprint later. For a journal/conference submission, pin BEAM before the version-of-record.
- **USENIX `usenix2019_v3.sty`** is not vendored. The paper uses portable `article` class + standard packages (`amsmath`, `booktabs`, `tabularx`, `listings`, `hyperref`, `cleveref`); arXiv compiles this without issue. For an ATC submission later, swap in the official `.sty` from <https://www.usenix.org/conferences/author-resources/paper-templates>.

## After submission

- Once arXiv assigns an ID (e.g. `arXiv:2605.XXXXX`), update `CITATION.cff` with the real arXiv ID.
- Update the AMP repo README with a "Cite this paper" line linking to the arXiv abstract page.
- Replace the `[CITATION NEEDED]` macros in your bib's `software-self-cite` entry with the real arXiv ID.
