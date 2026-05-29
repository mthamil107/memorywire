"""Extract the AMP paper abstract as plain text ready for the arXiv form."""

from __future__ import annotations

import re
from pathlib import Path

TEX = Path(__file__).resolve().parents[1] / "docs" / "paper" / "arxiv-submission" / "amp-paper.tex"

tex = TEX.read_text(encoding="utf-8")
m = re.search(r"\\begin\{abstract\}(.+?)\\end\{abstract\}", tex, re.DOTALL)
assert m, "abstract not found"
abs_tex = m.group(1).strip()

# Plain-text cleanup for arXiv's abstract field (which renders text only).
clean = abs_tex
clean = re.sub(r"\\texttt\{([^}]+)\}", r"\1", clean)
clean = re.sub(r"\\emph\{([^}]+)\}", r"\1", clean)
clean = re.sub(r"\\textbf\{([^}]+)\}", r"\1", clean)
clean = re.sub(r"\\cite\{[^}]+\}", "", clean)
clean = re.sub(r"\\Cref\{[^}]+\}", "the relevant section", clean)
clean = re.sub(r"\\ref\{[^}]+\}", "", clean)
clean = clean.replace(r"\&", "&").replace(r"\%", "%").replace(r"\#", "#").replace(r"\$", "$")
clean = re.sub(r"\\\\", " ", clean)
clean = clean.replace("---", "—").replace("--", "–")
# Strip math-mode delimiters; arXiv's text field renders math as text.
clean = re.sub(r"\$([^$]+)\$", r"\1", clean)
# Replace common math symbols with plain-text equivalents.
clean = clean.replace(r"\,", " ")
clean = clean.replace(r"\in", "in")
clean = clean.replace(r"\geq", ">=")
clean = clean.replace(r"\leq", "<=")
clean = clean.replace(r"\dots", "...")
clean = clean.replace(r"\{", "{").replace(r"\}", "}")
clean = clean.replace(r"\&", "&").replace(r"\%", "%")
clean = clean.replace(r"\times", "x")
# Collapse whitespace.
clean = re.sub(r"\s+", " ", clean).strip()

print("=" * 72)
print(" PASTE THIS INTO arXiv's 'Abstract' field — plain text ready")
print("=" * 72)
print()
print(clean)
print()
print("=" * 72)
print(f" Character count: {len(clean):,}  (arXiv limit: 1,920)")
print(f" Word count:      {len(clean.split())}")
print(f" Headroom:        {1920 - len(clean):,} chars left")
print("=" * 72)
