"""Structural validation of the arXiv submission bundle.

Runs without a local LaTeX install. Verifies:

* Brace balance + ``\\begin``/``\\end`` balance in the .tex source.
* BibTeX parses + every ``\\cite{}`` key has a matching ``@entry``.
* Every ``\\Cref``/``\\ref`` target has a matching ``\\label``.
* Every ``\\includegraphics{path}`` resolves to a real file in the bundle.
* Abstract block is present and non-empty.
* Open ``\\citeneeded`` / ``[CITATION NEEDED]`` markers are surfaced.
* Common pitfalls (empty cite key, double ampersand in table) are scanned.

Exit code:
* 0 if every check passes.
* 1 otherwise (and prints the failures).
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import bibtexparser

ROOT = Path(__file__).resolve().parents[1] / "docs" / "paper" / "arxiv-submission"
TEX = ROOT / "memwire-paper.tex"
BIB = ROOT / "memwire.bib"


def main() -> int:
    tex = TEX.read_text(encoding="utf-8")
    bib_text = BIB.read_text(encoding="utf-8")

    line = "=" * 70
    print(line)
    print(f"Bundle: {ROOT}")
    print(f"Sizes : memwire-paper.tex={len(tex):,} chars | memwire.bib={len(bib_text):,} chars")
    print(line)

    failures: list[str] = []

    # 1. Braces
    opens, closes = tex.count("{"), tex.count("}")
    if opens != closes:
        failures.append(f"brace mismatch: {opens} open vs {closes} close")
    print(f"\n[1] Brace balance        : {opens} open / {closes} close")

    # 2. begin/end
    begins = re.findall(r"\\begin\{(\w+)\}", tex)
    ends = re.findall(r"\\end\{(\w+)\}", tex)
    b_count, e_count = Counter(begins), Counter(ends)
    mismatched = {
        k: (b_count[k], e_count[k])
        for k in set(begins) | set(ends)
        if b_count[k] != e_count[k]
    }
    if mismatched:
        failures.append(f"begin/end mismatch: {mismatched}")
    print(f"[2] begin/end balance    : "
          f"{'OK' if not mismatched else 'MISMATCH ' + str(mismatched)}")

    # 3. BibTeX
    bib_db = bibtexparser.loads(bib_text)
    bib_keys = {e["ID"] for e in bib_db.entries}
    print(f"\n[3] BibTeX entries       : {len(bib_db.entries)} parsed")
    for e in bib_db.entries:
        print(f"      - {e['ID']:30s} type={e['ENTRYTYPE']}")

    # 4. Cite resolution
    cite_re = re.compile(r"\\cite[a-z]*\{([^}]+)\}")
    cited = set()
    for m in cite_re.finditer(tex):
        for k in m.group(1).split(","):
            cited.add(k.strip())
    missing_cites = cited - bib_keys
    unused_bib = bib_keys - cited
    print("\n[4] Citation resolution  :")
    print(f"      cited keys           = {len(cited)}")
    print(f"      bib entries          = {len(bib_keys)}")
    print(f"      missing in bib       = {sorted(missing_cites) if missing_cites else 'none'}")
    if unused_bib:
        print(f"      unused bib entries   = {sorted(unused_bib)}")
    if missing_cites:
        failures.append(f"missing bib entries: {sorted(missing_cites)}")

    # 5. Label / ref
    label_re = re.compile(r"\\label\{([^}]+)\}")
    ref_re = re.compile(r"\\(?:Cref|cref|ref|autoref|pageref)\{([^}]+)\}")
    labels = set(label_re.findall(tex))
    refs: set[str] = set()
    for m in ref_re.finditer(tex):
        refs.update(k.strip() for k in m.group(1).split(","))
    missing_refs = refs - labels
    unused_labels = labels - refs
    print("\n[5] Label / Ref resolve  :")
    print(f"      labels               = {len(labels)}")
    print(f"      refs                 = {len(refs)}")
    if missing_refs:
        failures.append(f"refs without labels: {sorted(missing_refs)}")
        print(f"      MISSING LABELS       = {sorted(missing_refs)}")
    if unused_labels:
        print(f"      unused labels        = {sorted(unused_labels)[:5]}{'...' if len(unused_labels) > 5 else ''}")

    # 6. Figures
    fig_re = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
    figs = fig_re.findall(tex)
    print("\n[6] Figures              :")
    for f in figs:
        p = ROOT / f
        if p.exists():
            print(f"      {f}: OK ({p.stat().st_size:,} bytes)")
        else:
            failures.append(f"figure not found: {f}")
            print(f"      {f}: MISSING")

    # 7. Word count
    def strip_tex(s: str) -> str:
        s = re.sub(r"%[^\n]*", "", s)
        s = re.sub(r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}", "", s, flags=re.DOTALL)
        s = re.sub(r"\\begin\{verbatim\}.*?\\end\{verbatim\}", "", s, flags=re.DOTALL)
        s = re.sub(r"\\[a-zA-Z]+\*?(?:\{[^}]*\})*", " ", s)
        s = s.replace("{", " ").replace("}", " ")
        return s

    words = strip_tex(tex).split()
    print(f"\n[7] Word count           : {len(words):,}")

    # 8. Sections
    sections = re.findall(r"\\section\{([^}]+)\}", tex)
    print(f"\n[8] Top-level sections   : {len(sections)}")
    for i, s in enumerate(sections, 1):
        print(f"      {i:2}. {s}")

    # 9. Abstract
    abs_match = re.search(r"\\begin\{abstract\}(.+?)\\end\{abstract\}", tex, re.DOTALL)
    if abs_match:
        abs_words = len(abs_match.group(1).split())
        print(f"\n[9] Abstract             : present, ~{abs_words} words")
    else:
        failures.append("abstract block missing")
        print("\n[9] Abstract             : NOT FOUND")

    # 10. Open citation gaps
    needed_tex = len(re.findall(r"\\citeneeded\{|\[CITATION NEEDED\]", tex))
    needed_bib = bib_text.count("% TODO")
    print(f"\n[10] Citation TODOs      : {needed_tex} in .tex / {needed_bib} in .bib")

    # 11. Pitfalls
    pitfalls: list[str] = []
    if re.search(r"\\cite\{,", tex):
        pitfalls.append("empty leading cite key")
    if re.search(r"\}\s*\}\s*\{", tex):
        pitfalls.append("triple brace suspicious")
    if re.search(r"(?<!\\)&\s*&", tex):
        pitfalls.append("double ampersand in table")
    print(f"\n[11] Pitfall scan        : {pitfalls if pitfalls else 'clean'}")

    # Verdict
    print()
    print(line)
    print("VERDICT")
    print(line)
    if failures:
        print("  FAIL")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  PASS  -  bundle is structurally arXiv-ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
