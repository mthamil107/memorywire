"""Tests for the ``amp`` CLI.

Two flavours of coverage:

* ``--version`` / ``--help`` already covered by ``test_smoke.py``; not
  duplicated here (kept green by leaving the subparser top-level intact).
* Subcommand happy-paths and error paths use a patched
  :func:`memorywire.api._build_store` so the CLI runs against an in-process
  :class:`MockStore` Ã¢â‚¬â€ no sqlite-vec / mem0 deps required.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Any
from urllib.parse import urlparse

import pytest

from memorywire import (
    Capability,
    ExpireAction,
    FusionAlgorithm,
    MemoryStore,
    MemoryType,
    MergeStrategy,
    RecallHit,
)
from memorywire.models import (
    ExpireRequest,
    ExpireResponse,
    ForgetRequest,
    ForgetResponse,
    ForgetStoreResult,
    MergeRequest,
    MergeResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)

# ---------------------------------------------------------------------------
# CLI MockStore Ã¢â‚¬â€ keyed by URL so multiple --store flags share state across
# Memory() instantiations within a single CLI invocation.
# ---------------------------------------------------------------------------


_MOCK_REGISTRY: dict[str, CliMockStore] = {}


class CliMockStore:
    """Tiny store used by CLI tests via a patched ``_build_store``."""

    BACKEND_NAME = "mock"

    def __init__(self, url: str = "mock://default") -> None:
        self._url = url
        self._records: dict[str, dict[str, Any]] = {}
        self.remember_calls: list[RememberRequest] = []
        self.recall_calls: list[RecallRequest] = []
        self.forget_calls: list[ForgetRequest] = []

    @property
    def capabilities(self) -> set[str]:
        return {
            Capability.SEMANTIC,
            Capability.EPISODIC,
            Capability.PROCEDURAL,
            Capability.EMOTIONAL,
        }

    async def remember(self, req: RememberRequest) -> RememberResponse:
        self.remember_calls.append(req)
        memory_id = f"mock-{len(self._records) + 1}"
        self._records[memory_id] = {
            "id": memory_id,
            "agent_id": req.agent_id,
            "user_id": req.user_id,
            "type": req.type,
            "content": req.content,
            "metadata": req.metadata,
        }
        return RememberResponse(
            id=memory_id,
            stored_at=1_700_000_000_000,
            stores=[self.BACKEND_NAME],
            pending_approval=False,
            approval_url=None,
        )

    async def recall(self, req: RecallRequest) -> RecallResponse:
        self.recall_calls.append(req)
        needle = req.query.lower()
        hits: list[RecallHit] = []
        for rec in self._records.values():
            if rec["agent_id"] != req.agent_id:
                continue
            if needle in str(rec["content"]).lower():
                hits.append(
                    RecallHit(
                        id=rec["id"],
                        type=rec["type"],
                        content=rec["content"],
                        score=0.5,
                        metadata=rec["metadata"],
                        created_at=1_700_000_000_000,
                        supporting=[],
                        source_store=self.BACKEND_NAME,
                    )
                )
        return RecallResponse(
            results=hits[: req.k or 5],
            fusion_used=req.fusion if req.fusion is not None else FusionAlgorithm.RRF,
            stores_queried=[self.BACKEND_NAME],
            latency_ms=1,
        )

    async def forget(self, req: ForgetRequest) -> ForgetResponse:
        self.forget_calls.append(req)
        target: list[str] = []
        if req.ids:
            target.extend(mid for mid in req.ids if mid in self._records)
        if req.filter:
            for mid, rec in self._records.items():
                if mid in target:
                    continue
                if _matches_filter(rec, req.filter):
                    target.append(mid)
        for mid in target:
            self._records.pop(mid, None)
        return ForgetResponse(
            forgotten_ids=target,
            hard_delete=bool(req.hard_delete),
            stores=[ForgetStoreResult(store=self.BACKEND_NAME, count=len(target))],
            pending_approval=False,
            approval_url=None,
        )

    async def merge(self, req: MergeRequest) -> MergeResponse:
        return MergeResponse(
            canonical=req.canonical,
            merged_count=0,
            strategy_used=req.strategy
            if req.strategy is not None
            else MergeStrategy.KEEP_CANONICAL,
            stores=[self.BACKEND_NAME],
        )

    async def expire(self, req: ExpireRequest) -> ExpireResponse:
        return ExpireResponse(
            matched_count=0,
            action_taken=req.action if req.action is not None else ExpireAction.FORGET,
            stores=[self.BACKEND_NAME],
        )

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "backend": self.BACKEND_NAME}

    def close(self) -> None:
        # Don't drop the registry entry Ã¢â‚¬â€ recall/forget invocations in a
        # later test step depend on remember's state surviving.
        pass


def _matches_filter(rec: dict[str, Any], flt: dict[str, Any]) -> bool:
    """Flat key/value filter against a CLI mock record."""
    for key, value in flt.items():
        if key == "type":
            actual = rec.get("type")
            target_value = value.value if isinstance(value, MemoryType) else value
            actual_value = actual.value if isinstance(actual, MemoryType) else actual
            if actual_value != target_value:
                return False
            continue
        if key in rec:
            if rec[key] != value:
                return False
            continue
        metadata = rec.get("metadata") or {}
        if metadata.get(key) != value:
            return False
    return True


def _mock_build_store(url: str) -> MemoryStore:
    """Patched ``_build_store`` that keys off the URL string.

    Stores are cached in ``_MOCK_REGISTRY`` so multiple Memory() instances
    sharing the same URL within a single test see the same data.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"mock", "sqlite-vec", "mem0"}:
        raise ValueError(f"unknown store URL scheme: {url}")
    store = _MOCK_REGISTRY.get(url)
    if store is None:
        store = CliMockStore(url=url)
        _MOCK_REGISTRY[url] = store
    return store


@pytest.fixture(autouse=True)
def _patch_build_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace :func:`memorywire.api._build_store` with the in-process mock.

    ``autouse`` so every CLI test in this module runs hermetically. We
    also clear the per-URL registry so tests are isolated.
    """
    _MOCK_REGISTRY.clear()
    monkeypatch.setattr("memorywire.api._build_store", _mock_build_store)


# ---------------------------------------------------------------------------
# In-process CLI invocation helper
# ---------------------------------------------------------------------------


def _run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run ``memorywire.cli.main(args)`` in-process; capture stdout + stderr."""
    # Reimport inside the helper so monkeypatch is in effect.
    from memorywire import cli

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cli_version_subprocess() -> None:
    """``amp --version`` exits 0 and prints a recognisable banner."""
    result = subprocess.run(
        [sys.executable, "-m", "memorywire.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "memorywire" in result.stdout.lower()


def test_cli_help_subprocess() -> None:
    """``amp --help`` exits 0 Ã¢â‚¬â€ exercise the full entry point too."""
    result = subprocess.run(
        [sys.executable, "-m", "memorywire.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_cli_remember_prints_id() -> None:
    """``amp remember <content>`` exits 0 and prints ``id=...``."""
    code, out, _err = _run_cli(["remember", "hello world", "--store", "mock://store-a"])
    assert code == 0
    assert "id=" in out


def test_cli_recall_json_output_parses() -> None:
    """``amp recall ... --json`` emits a parseable JSON object."""
    # Seed by remembering first.
    code, _, _ = _run_cli(["remember", "tea is delightful", "--store", "mock://store-b"])
    assert code == 0

    code, out, _err = _run_cli(["recall", "tea", "--store", "mock://store-b", "--json"])
    assert code == 0
    payload = json.loads(out)
    assert "results" in payload
    assert isinstance(payload["results"], list)
    assert payload["results"], "expected at least one recall hit"
    first = payload["results"][0]
    assert "id" in first
    assert "type" in first


def test_cli_recall_human_output_lines() -> None:
    """Human-readable recall output prints one line per hit with score+id."""
    code, _, _ = _run_cli(["remember", "the lake is blue", "--store", "mock://store-c"])
    assert code == 0
    code, out, _err = _run_cli(["recall", "lake", "--store", "mock://store-c"])
    assert code == 0
    assert "score=" in out
    assert "type=" in out
    assert "id=" in out
    assert "content=" in out


def test_cli_forget_by_filter_prints_count() -> None:
    """``amp forget --filter ...`` exits 0 and prints ``forgotten=<n>``."""
    code, _, _ = _run_cli(
        [
            "remember",
            "alice booked a flight",
            "--store",
            "mock://store-d",
            "--user",
            "alice",
        ]
    )
    assert code == 0

    code, out, _err = _run_cli(
        [
            "forget",
            "--filter",
            '{"user_id":"alice"}',
            "--store",
            "mock://store-d",
        ]
    )
    assert code == 0
    assert "forgotten=" in out


def test_cli_remember_with_bad_metadata_exits_one() -> None:
    """A malformed ``--metadata`` JSON literal exits with code 1."""
    code, _, err = _run_cli(
        [
            "remember",
            "x",
            "--metadata",
            "{not valid json",
            "--store",
            "mock://store-e",
        ]
    )
    assert code == 1
    assert "metadata" in err


def test_cli_unknown_subcommand_is_non_zero() -> None:
    """``amp bogus`` exits with a non-zero status (argparse rejects it)."""
    result = subprocess.run(
        [sys.executable, "-m", "memorywire.cli", "bogus-command"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_cli_forget_without_scope_exits_one() -> None:
    """``amp forget`` with neither ``--id`` nor ``--filter`` exits 1."""
    code, _, err = _run_cli(["forget", "--store", "mock://store-f"])
    assert code == 1
    assert "forget" in err
