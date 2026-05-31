"""Inspect the arXiv-compiled preview PDF to verify content matches the bundle."""

from __future__ import annotations

import sys
from pathlib import Path

# Force stdout to UTF-8 so we can print extracted PDF text on cp1252 consoles.
sys.stdout.reconfigure(encoding="utf-8")

from pypdf import PdfReader

PDF = Path(r"C:\Users\THAMIL\Downloads\view.pdf")

r = PdfReader(str(PDF))

print("=" * 76)
print(f"FILE : {PDF}")
print(f"SIZE : {PDF.stat().st_size:,} bytes")
print(f"PAGES: {len(r.pages)}")
md = r.metadata or {}
for k, v in md.items():
    print(f"  {k:14s} : {v}")
print("=" * 76)

print()
print("=" * 76)
print(" PAGE 1 (title + author + abstract)")
print("=" * 76)
print(r.pages[0].extract_text())

print()
print("=" * 76)
print(" PAGE 2 (intro continued)")
print("=" * 76)
print(r.pages[1].extract_text()[:1500])

print()
print("=" * 76)
print(" LAST PAGE (references)")
print("=" * 76)
print(r.pages[-1].extract_text())

# Quick text scan: are the key strings we expect in the PDF?
all_text = " ".join(p.extract_text() for p in r.pages)
print()
print("=" * 76)
print(" KEY-STRING SCAN")
print("=" * 76)
checks = [
    ("Title: memwire wire format",          "Vendor-Neutral Wire Format"),
    ("Author: Thamilvendhan",            "Thamilvendhan"),
    ("Author: Munirathinam",             "Munirathinam"),
    ("Affiliation: Independent",         "Independent Researcher"),
    ("Email: mthamil107@gmail",          "mthamil107@gmail"),
    ("Repository URL",                   "github.com/mthamil107/agent-memory-protocol"),
    ("Abstract opener",                  "Agent-memory frameworks"),
    ("Microbench number",                "recall@5 = 1.000"),
    ("Adversarial number",               "0.500"),
    ("Conformance number",               "68"),
    ("Preliminary LME number",           "0.417"),
    ("Preliminary LoCoMo number",        "0.150"),
    ("Threat model section",             "Malicious memory injection"),
    ("MCP positioning",                  "Model Context Protocol"),
    ("References list",                  "Cormack"),
    ("Old name placeholder absent",      "M. Thamil"),
]
for label, needle in checks:
    found = needle in all_text
    mark = "  OK " if found else " MISS"
    # Last check is inverted â€” we want it NOT found
    if label.startswith("Old name placeholder absent"):
        mark = "  OK " if not found else " FAIL"
    print(f"  [{mark.strip()}] {label:38s}  ({'present' if found else 'absent'})")

print()
# Word-count tally
words = sum(len(p.extract_text().split()) for p in r.pages)
print(f"Total extracted word count : {words:,}")
