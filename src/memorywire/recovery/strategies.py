"""Classification strategies for memory-poison recovery.

Each memory is classified into one :class:`~memorywire.recovery.report.Verdict`. The default
lever is **provenance** (untrusted ``source`` → purge), which the PurgeBench benchmark found to
be the strongest recovery signal. A built-in **directive detector** flags content that reads like
an embedded instruction; trusted-origin content that trips it is *quarantined* (not deleted),
which is the honest handling of the entangled case. External detectors — including OWASP Agent
Memory Guard's — can be supplied and are treated the same way.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .report import EntryVerdict, MemoryRecord, Verdict

DEFAULT_TRUSTED = frozenset({"user", "system"})

# Heuristic directive patterns: hyphenated imperative payloads and common bypass phrasings.
_DIRECTIVE = re.compile(
    r"\b("
    r"disable-\w+|mute-\w+|skip-\w+|grant-all|root-forever|allow-any|self-approve|"
    r"auto-approve\w*|force-push|drop-table|drop-index|chmod-777|open-shell|run-as-root|"
    r"leak-\w+|exfil-\w+|reroute-\w+|paste-public|bcc-\w+|log-plaintext|poison-\w+|"
    r"ignore-\w+|add-sleep|share-all-\w+|attacker-\w+"
    r")\b"
    r"|\b(always|just|simply)\s+\w+\s+(them|it|the)\b",
    re.IGNORECASE,
)

# A detector is either a callable content->bool, or an object exposing Agent Memory Guard's
# `.inspect(key, value, operation=...)` returning something with a truthy `.matched`.
Detector = Any


def _detector_hit(detector: Detector, key: str, content: str) -> bool:
    if callable(detector):
        try:
            return bool(detector(content))
        except TypeError:
            pass
    inspect = getattr(detector, "inspect", None)
    if inspect is not None:
        try:
            res = inspect(key, content, operation="write")
            return bool(getattr(res, "matched", False))
        except Exception:
            return False
    return False


def directive_detector(content: str) -> bool:
    """Built-in heuristic: does this content read like an embedded instruction?"""
    return bool(_DIRECTIVE.search(content or ""))


def classify(
    record: MemoryRecord,
    *,
    trusted_sources: frozenset[str] = DEFAULT_TRUSTED,
    detectors: list[Detector] | None = None,
    quarantine_suspicious: bool = True,
) -> EntryVerdict:
    """Return the recovery verdict for one memory record."""
    src = (record.source or "unknown").strip()
    untrusted = src not in trusted_sources

    # 1) Provenance — the strongest lever. Untrusted origin => purge.
    if untrusted:
        return EntryVerdict(record, Verdict.PURGE, f"untrusted source '{src}'")

    # 2) Trusted origin: run detectors (built-in + any supplied). A hit here is the
    #    entangled case — a directive hiding in trusted memory. Quarantine, do not delete.
    dets: list[Callable | Detector] = [directive_detector]
    if detectors:
        dets = dets + list(detectors)
    for d in dets:
        if _detector_hit(d, record.id, record.content):
            if quarantine_suspicious:
                return EntryVerdict(record, Verdict.QUARANTINE,
                                    "trusted-origin content matched a directive pattern")
            return EntryVerdict(record, Verdict.KEEP, "flagged but quarantine disabled")

    return EntryVerdict(record, Verdict.KEEP, "clean")
