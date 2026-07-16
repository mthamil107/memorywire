"""memorywire recovery — detect, recover, and verify poisoned agent memory.

The recovery capability cleans a compromised memory store using provenance (the strongest
lever per the PurgeBench benchmark), quarantines trusted-origin content that looks like an
embedded directive (the entangled case) for human review rather than deleting it, and can
run pluggable content detectors (including OWASP Agent Memory Guard's).

    from memorywire import Memory
    from memorywire.recovery import Recoverer

    rec = Recoverer(memory)
    report = await rec.recover(dry_run=True)
    print(report.to_text())
"""
from __future__ import annotations

from .engine import Recoverer
from .report import EntryVerdict, MemoryRecord, RecoveryReport, Verdict
from .strategies import classify, directive_detector

__all__ = [
    "Recoverer",
    "RecoveryReport",
    "EntryVerdict",
    "MemoryRecord",
    "Verdict",
    "classify",
    "directive_detector",
]
