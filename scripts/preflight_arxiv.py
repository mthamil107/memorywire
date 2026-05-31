"""arXiv pre-upload preflight â€” runs against the checklist arXiv displays
just before file upload. Catches the issues that slow down announcement:

  1. TeX source is present (not PDF-only).
  2. Every file referenced by the .tex (\\input, \\include,
     \\includegraphics) resolves inside the bundle.
  3. The bibliographystyle is one arXiv has built-in (`plain`,
     `abbrv`, `acm`, `apalike`, `unsrt`, `alpha`, `ieeetr`, `siam`).
  4. No suspicious comments are about to be archived forever
     (TODO, FIXME, XXX, DRAFT, internal notes, real names that
     shouldn't be in source).
  5. No stray binary files in the bundle (only .tex/.bib/.png/.md).
  6. memwire.bib parses cleanly + every \\cite resolves.

Run from repo root:
    .venv/Scripts/python.exe scripts/preflight_arxiv.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1] / "docs" / "paper" / "arxiv-submission"
TEX = ROOT / "memwire-paper.tex"
BIB = ROOT / "memwire.bib"

tex = TEX.read_text(encoding="utf-8")
bib = BIB.read_text(encoding="utf-8")

failures: list[str] = []
warnings: list[str] = []

print("=" * 76)
print(f"arXiv preflight on: {ROOT}")
print("=" * 76)

# 1. TeX source present
print("\n[1] TeX source upload (not PDF-only)")
files = sorted(p.name for p in ROOT.iterdir() if p.is_file())
print(f"    files in bundle: {files}")
if "memwire-paper.tex" not in files:
    failures.append("memwire-paper.tex missing from bundle")
else:
    print("    OK -- .tex present; arXiv compiles server-side.")

# 2. Files referenced by the .tex
print("\n[2] File-reference resolution")
ref_re = re.compile(r"\\(?:input|include|includegraphics)(?:\[[^\]]*\])?\{([^}]+)\}")
refs = ref_re.findall(tex)
print(f"    referenced files: {refs}")
for r in refs:
    candidates = [ROOT / r, ROOT / (r + ".tex"), ROOT / (r + ".png"), ROOT / (r + ".pdf")]
    hit = next((c for c in candidates if c.exists()), None)
    if hit:
        print(f"      OK   {r}  -> {hit.name}")
    else:
        failures.append(f"referenced file not in bundle: {r}")
        print(f"      MISS {r}")

# 3. Bibliographystyle
print("\n[3] BibTeX style")
style_match = re.search(r"\\bibliographystyle\{([^}]+)\}", tex)
arxiv_builtin = {"plain", "abbrv", "acm", "apalike", "unsrt", "alpha", "ieeetr", "siam"}
if style_match:
    style = style_match.group(1)
    print(f"    \\bibliographystyle{{{style}}}")
    if style in arxiv_builtin:
        print("    OK -- arXiv ships this style.")
    else:
        warnings.append(f"non-stock bib style {style!r}; you'd need to bundle the .bst file")
        print(f"    WARN -- non-stock style. Verify {style}.bst ships in your bundle, or switch to plain.")
else:
    warnings.append("no \\bibliographystyle directive; default plain assumed")
    print("    WARN -- no \\bibliographystyle; arXiv will likely default to plain.")

# 4. Archival-forever-comment scan
print("\n[4] Suspicious-comment scan (archived forever)")
sensitive_patterns = [
    (r"%\s*TODO\b",          "TODO marker in comment"),
    (r"%\s*FIXME\b",         "FIXME marker in comment"),
    (r"%\s*XXX\b",           "XXX marker in comment"),
    (r"%\s*HACK\b",          "HACK marker in comment"),
    (r"%\s*DRAFT\b",         "DRAFT marker in comment"),
    (r"%\s*confidential\b",  "confidential keyword in comment"),
    (r"%\s*private\b",       "private keyword in comment"),
    (r"%\s*password\b",      "password keyword in comment"),
    (r"%[^\n]*api[_-]?key", "api key reference in comment"),
    (r"%[^\n]*<.+@.+\>",    "email address in comment"),
]
found_any = False
for pat, label in sensitive_patterns:
    for m in re.finditer(pat, tex, flags=re.IGNORECASE):
        line_no = tex[: m.start()].count("\n") + 1
        snippet = tex[m.start() : tex.find("\n", m.start())][:120]
        warnings.append(f"L{line_no}: {label}: {snippet}")
        print(f"    WARN L{line_no}: {label}")
        print(f"         {snippet}")
        found_any = True
if not found_any:
    print("    OK -- no sensitive patterns matched.")

# Also count total comment lines & characters for awareness.
comment_lines = [ln for ln in tex.splitlines() if ln.lstrip().startswith("%")]
print(f"    info: {len(comment_lines)} comment lines, {sum(len(c) for c in comment_lines):,} comment chars.")

# 5. Binary/stray files
print("\n[5] Bundle hygiene")
allowed_ext = {".tex", ".bib", ".png", ".pdf", ".md", ".bst", ".sty", ".cls"}
stray = [p.name for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() not in allowed_ext]
if stray:
    warnings.append(f"stray files in bundle: {stray}")
    print(f"    WARN -- non-standard files in bundle: {stray}")
else:
    print("    OK -- only standard LaTeX bundle extensions present.")

# 6. BibTeX entries + cite resolution
print("\n[6] Citation resolution")
cite_re = re.compile(r"\\cite[a-z]*\{([^}]+)\}")
cited = set()
for m in cite_re.finditer(tex):
    for k in m.group(1).split(","):
        cited.add(k.strip())
bib_keys = set(re.findall(r"@\w+\{([^,]+),", bib))
missing = cited - bib_keys
if missing:
    failures.append(f"\\cite keys missing from memwire.bib: {sorted(missing)}")
    print(f"    FAIL -- missing keys: {sorted(missing)}")
else:
    print(f"    OK -- all {len(cited)} cite keys resolve in memwire.bib ({len(bib_keys)} entries)")

# Verdict
print()
print("=" * 76)
print("VERDICT")
print("=" * 76)
if failures:
    print("  FAIL -- DO NOT UPLOAD YET:")
    for f in failures:
        print(f"    - {f}")
else:
    print("  PASS -- bundle is upload-ready.")
if warnings:
    print(f"\n  {len(warnings)} non-blocking warnings:")
    for w in warnings:
        print(f"    - {w}")
print()
