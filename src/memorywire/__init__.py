"""Agent Memory Protocol (memorywire) â€” vendor-neutral protocol and reference implementation."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("agent-memory-protocol")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

from memorywire.api import Memory
from memorywire.models import (
    ExpireAction,
    ExpireRequest,
    ForgetRequest,
    FusionAlgorithm,
    MemoryType,
    MergeRequest,
    MergeStrategy,
    Recall,
    RecallHit,
    RecallRequest,
    RememberRequest,
)
from memorywire.router import MemoryRouter
from memorywire.store.base import Capability, MemoryStore

__all__ = [
    "Capability",
    "ExpireAction",
    "ExpireRequest",
    "ForgetRequest",
    "FusionAlgorithm",
    "Memory",
    "MemoryRouter",
    "MemoryStore",
    "MemoryType",
    "MergeRequest",
    "MergeStrategy",
    "Recall",
    "RecallHit",
    "RecallRequest",
    "RememberRequest",
    "__version__",
]
