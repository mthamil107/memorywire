"""Data types and formatting for memory-poison recovery.

Recovery classifies each memory into one verdict, then acts on it via the memorywire
``forget`` / ``expire`` operations. Nothing here talks to a store directly — these are plain
records and reports so they are trivial to test and to serialise for automation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    KEEP = "keep"              # clean
    PURGE = "purge"            # untrusted origin (or untrusted + detector hit) -> forget
    QUARANTINE = "quarantine"  # trusted origin but looks like a directive -> soft-forget for review
    EXPIRE = "expire"          # low-confidence, dropped by the expire policy


@dataclass
class MemoryRecord:
    """A single memory row as seen by recovery."""
    id: str
    content: str
    source: str | None
    confidence: float | None


@dataclass
class EntryVerdict:
    record: MemoryRecord
    verdict: Verdict
    reason: str


@dataclass
class RecoveryReport:
    scanned: int = 0
    verdicts: list[EntryVerdict] = field(default_factory=list)
    dry_run: bool = False
    expired: int = 0

    def _by(self, v: Verdict) -> list[EntryVerdict]:
        return [e for e in self.verdicts if e.verdict is v]

    @property
    def purged(self) -> list[EntryVerdict]:
        return self._by(Verdict.PURGE)

    @property
    def quarantined(self) -> list[EntryVerdict]:
        return self._by(Verdict.QUARANTINE)

    @property
    def kept(self) -> list[EntryVerdict]:
        return self._by(Verdict.KEEP)

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "dry_run": self.dry_run,
            "purged": len(self.purged),
            "quarantined": len(self.quarantined),
            "expired": self.expired,
            "kept": len(self.kept),
            "actions": [
                {"id": e.record.id, "verdict": e.verdict.value, "source": e.record.source,
                 "reason": e.reason}
                for e in self.verdicts if e.verdict is not Verdict.KEEP
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def to_text(self) -> str:
        head = "DRY RUN - no changes made\n" if self.dry_run else ""
        lines = [
            f"{head}Recovery report - scanned {self.scanned} memories",
            f"  purged (untrusted origin): {len(self.purged)}",
            f"  quarantined (needs human review): {len(self.quarantined)}",
            f"  expired (low confidence): {self.expired}",
            f"  kept (clean): {len(self.kept)}",
        ]
        if self.quarantined:
            lines.append("")
            lines.append("  [!] Quarantined for review - trusted-origin memories that look like")
            lines.append("      directives. Recovery does NOT auto-delete these (the entangled case);")
            lines.append("      a human should confirm. They are soft-deleted (restorable):")
            for e in self.quarantined[:20]:
                lines.append(f"      - {e.record.id}: {e.reason}")
        return "\n".join(lines)
