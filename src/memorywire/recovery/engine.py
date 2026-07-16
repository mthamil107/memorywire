"""The recovery engine: detect → recover → verify, over a memorywire ``Memory``.

Enumeration reads memory rows (including the ``source`` / ``confidence`` provenance that
``recall`` does not surface) from the backing store. v0.1 supports the reference
``SqliteVecStore``; other adapters can supply records explicitly or implement an enumerator.
All *mutations* go through the ``Memory`` facade's ``forget`` / ``expire`` so the audit trail
and soft-delete (= quarantine) semantics are the real ones.
"""
from __future__ import annotations

from memorywire.api import Memory
from memorywire.models import ExpireAction

from .report import EntryVerdict, MemoryRecord, RecoveryReport, Verdict
from .strategies import DEFAULT_TRUSTED, Detector, classify


def _enumerate_sqlite(store, agent_id: str) -> list[MemoryRecord]:
    """Read live (non-deleted) rows from a SqliteVecStore for one agent."""
    conn = getattr(store, "_conn", None)
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT id, content, source, confidence FROM memories "
        "WHERE agent_id = ? AND (deleted_at IS NULL)",
        (agent_id,),
    ).fetchall()
    return [MemoryRecord(id=r["id"], content=r["content"], source=r["source"],
                         confidence=r["confidence"]) for r in rows]


class Recoverer:
    """Detect and recover poisoned memory for one agent."""

    def __init__(
        self,
        memory: Memory,
        *,
        trusted_sources: frozenset[str] | set[str] = DEFAULT_TRUSTED,
        detectors: list[Detector] | None = None,
        records: list[MemoryRecord] | None = None,
    ) -> None:
        self._mem = memory
        self._trusted = frozenset(trusted_sources)
        self._detectors = detectors
        self._records = records  # explicit override (e.g. non-sqlite backends / tests)

    def _collect(self) -> list[MemoryRecord]:
        if self._records is not None:
            return self._records
        out: list[MemoryRecord] = []
        for store in self._mem.router.stores:
            if type(store).__name__ == "SqliteVecStore":
                out.extend(_enumerate_sqlite(store, self._mem.agent_id))
        return out

    def scan(self, *, quarantine_suspicious: bool = True) -> list[EntryVerdict]:
        return [
            classify(r, trusted_sources=self._trusted, detectors=self._detectors,
                     quarantine_suspicious=quarantine_suspicious)
            for r in self._collect()
        ]

    async def recover(
        self,
        *,
        expire_low_conf: bool = False,
        confidence_below: float = 0.75,
        quarantine_suspicious: bool = True,
        hard_delete: bool = False,
        dry_run: bool = False,
    ) -> RecoveryReport:
        verdicts = self.scan(quarantine_suspicious=quarantine_suspicious)
        report = RecoveryReport(scanned=len(verdicts), verdicts=verdicts, dry_run=dry_run)

        if dry_run:
            return report

        purge_ids = [e.record.id for e in verdicts if e.verdict is Verdict.PURGE]
        quarantine_ids = [e.record.id for e in verdicts if e.verdict is Verdict.QUARANTINE]

        if purge_ids:
            await self._mem.forget(ids=purge_ids, hard_delete=hard_delete,
                                   reason="recover:purge:untrusted-source")
        if quarantine_ids:
            # soft-delete only — removed from recall but restorable, pending human review
            await self._mem.forget(ids=quarantine_ids, hard_delete=False,
                                   reason="recover:quarantine:review")
        if expire_low_conf:
            resp = await self._mem.expire(policy={"confidence_below": confidence_below},
                                          action=ExpireAction.FORGET)
            report.expired = len(getattr(resp, "affected_ids", []) or
                                 getattr(resp, "expired_ids", []) or [])
        return report

    async def verify(self, triggers: dict[str, str] | None = None) -> dict:
        """Optional self-check. Returns residual counts; if triggers ({marker: query}) are
        given, re-recalls each and reports any marker that still surfaces."""
        residual_untrusted = sum(
            1 for e in self.scan() if e.verdict is Verdict.PURGE
        )
        result = {"residual_untrusted": residual_untrusted}
        if triggers:
            still_firing = []
            for marker, query in triggers.items():
                hits = await self._mem.recall(query, k=8)
                if any(marker in (h.content if isinstance(h.content, str) else "") for h in hits):
                    still_firing.append(marker)
            result["still_firing"] = still_firing
        return result
