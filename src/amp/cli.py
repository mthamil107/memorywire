"""``amp`` command-line entry point — full Phase 5 implementation.

Three subcommands, all dispatched through the :class:`amp.api.Memory`
facade so the CLI exercises the same code path SDK consumers use:

* ``amp remember <content>`` — write a memory; prints ``id=<id>``.
* ``amp recall <query>``     — read memories; prints a table or JSON.
* ``amp forget``             — delete memories; prints ``forgotten=<n>``.

Common flags:

* ``--agent AGENT`` (default ``amp-cli``) — scope every operation.
* ``--store URL``  (repeatable, default ``sqlite-vec://./amp-cli.db``).
* ``--verbose`` / ``--quiet`` — log-level toggles.

Exit codes:

* ``0`` on success.
* ``1`` on user error (bad args, schema validation failure, malformed JSON).
* ``2`` on backend error (anything the store raised).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from typing import Any

from amp import __version__
from amp.api import Memory
from amp.models import MemoryType

logger = logging.getLogger("amp.cli")

# Stable text the smoke tests parse out of ``--help`` / ``--version``. Kept
# as module constants so refactors don't drift the contract.
_PROG_NAME = "amp"
_DEFAULT_STORE = "sqlite-vec://./amp-cli.db"
_DEFAULT_AGENT = "amp-cli"


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level ``amp`` :class:`argparse.ArgumentParser`."""
    parser = argparse.ArgumentParser(
        prog=_PROG_NAME,
        description=f"{_PROG_NAME} {__version__} — Agent Memory Protocol CLI",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{_PROG_NAME} {__version__}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging on stderr.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational logging (WARNING+ only).",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # ---- remember ----------------------------------------------------------
    remember = subparsers.add_parser("remember", help="Write a memory and print the assigned id.")
    remember.add_argument("content", help="The memory text to store.")
    remember.add_argument(
        "--type",
        choices=[t.value for t in MemoryType],
        default=MemoryType.SEMANTIC.value,
        help="Memory type tag (default: semantic).",
    )
    remember.add_argument("--user", dest="user_id", default=None, help="Optional user_id scope.")
    remember.add_argument(
        "--confidence",
        type=float,
        default=1.0,
        help="Confidence in the memory (0..1; default 1.0).",
    )
    remember.add_argument(
        "--metadata",
        default=None,
        help="Optional JSON object literal for the metadata field.",
    )
    _add_common_flags(remember)

    # ---- recall ------------------------------------------------------------
    recall = subparsers.add_parser("recall", help="Read memories matching a query.")
    recall.add_argument("query", help="Natural-language query.")
    recall.add_argument(
        "-k", type=int, default=5, help="Maximum number of hits to return (default: 5)."
    )
    recall.add_argument(
        "--type",
        dest="types",
        choices=[t.value for t in MemoryType],
        action="append",
        default=None,
        help="Restrict to memory type(s). Repeat to allow more than one.",
    )
    recall.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help='Emit results as ``{"results": [...]}`` JSON.',
    )
    _add_common_flags(recall)

    # ---- forget ------------------------------------------------------------
    forget = subparsers.add_parser("forget", help="Delete memories by id or filter.")
    forget.add_argument(
        "--id",
        dest="ids",
        action="append",
        default=None,
        help="Memory id to delete. Repeat for multiple.",
    )
    forget.add_argument(
        "--filter", default=None, help='JSON filter object (e.g. \'{"user_id":"x"}\').'
    )
    forget.add_argument(
        "--hard", action="store_true", help="Perform a hard-delete instead of soft-delete."
    )
    forget.add_argument("--reason", default=None, help="Optional reason string for the audit log.")
    _add_common_flags(forget)

    return parser


def _add_common_flags(sub: argparse.ArgumentParser) -> None:
    """Attach ``--agent`` / ``--store`` to a subcommand parser."""
    sub.add_argument(
        "--agent",
        dest="agent_id",
        default=_DEFAULT_AGENT,
        help="agent_id scope (default: amp-cli).",
    )
    sub.add_argument(
        "--store",
        dest="stores",
        action="append",
        default=None,
        help="Store URL. Repeat for multi-store recall (default: sqlite-vec://./amp-cli.db).",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_logging(args: argparse.Namespace) -> None:
    """Apply ``--verbose`` / ``--quiet`` to the root logger.

    Keeps the configuration idempotent so test runs don't accumulate
    handlers when ``main`` is called multiple times in-process.
    """
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.WARNING
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s", force=True)


def _resolve_stores(args: argparse.Namespace) -> list[str]:
    """Return the list of store URLs for this invocation (default-applied)."""
    return list(args.stores) if args.stores else [_DEFAULT_STORE]


def _parse_json_obj(raw: str, field_label: str) -> dict[str, Any]:
    """Parse a JSON object literal or raise the canonical user-error.

    Returns a ``dict[str, Any]`` and rejects any other top-level shape.
    """
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _UserError(f"--{field_label} is not valid JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise _UserError(f"--{field_label} must be a JSON object")
    return decoded


def _truncate(text: str, limit: int = 80) -> str:
    """Single-line elision for the human-readable recall output."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


class _UserError(Exception):
    """Raised by handlers for bad-input / malformed-request conditions.

    Translated to exit code ``1`` in :func:`main`. Backend exceptions
    (anything other than this) translate to exit code ``2``.
    """


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


async def _handle_remember(args: argparse.Namespace) -> int:
    """Implement ``amp remember <content>``."""
    metadata: dict[str, Any] | None = None
    if args.metadata is not None:
        metadata = _parse_json_obj(args.metadata, "metadata")

    mem = Memory(agent_id=args.agent_id, stores=_resolve_stores(args))
    try:
        resp = await mem.remember(
            args.content,
            type=MemoryType(args.type),
            user_id=args.user_id,
            metadata=metadata,
            confidence=args.confidence,
        )
    finally:
        await mem.close()

    print(f"id={resp.id}")
    return 0


async def _handle_recall(args: argparse.Namespace) -> int:
    """Implement ``amp recall <query>``."""
    types: list[MemoryType] | None = None
    if args.types:
        types = [MemoryType(t) for t in args.types]

    mem = Memory(agent_id=args.agent_id, stores=_resolve_stores(args))
    try:
        hits = await mem.recall(args.query, k=args.k, types=types)
    finally:
        await mem.close()

    if args.json_out:
        payload = {"results": [h.model_dump(mode="json", exclude_none=True) for h in hits]}
        print(json.dumps(payload))
    else:
        for hit in hits:
            # Render content compactly; dict content (procedural FSM) is
            # JSON-encoded inline for terminal readability.
            content_str = hit.content if isinstance(hit.content, str) else json.dumps(hit.content)
            print(
                f"score={hit.score:.4f} type={hit.type.value} id={hit.id} "
                f"content={_truncate(content_str)}"
            )
    return 0


async def _handle_forget(args: argparse.Namespace) -> int:
    """Implement ``amp forget``."""
    if not args.ids and not args.filter:
        raise _UserError("forget requires --id or --filter")

    filter_obj: dict[str, Any] | None = None
    if args.filter is not None:
        filter_obj = _parse_json_obj(args.filter, "filter")

    mem = Memory(agent_id=args.agent_id, stores=_resolve_stores(args))
    try:
        resp = await mem.forget(
            ids=args.ids,
            filter=filter_obj,
            hard_delete=args.hard,
            reason=args.reason,
        )
    finally:
        await mem.close()

    print(f"forgotten={len(resp.forgotten_ids)}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_HANDLERS = {
    "remember": _handle_remember,
    "recall": _handle_recall,
    "forget": _handle_forget,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``amp`` CLI. Returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args)

    if not args.command:
        parser.print_help()
        return 0

    handler = _HANDLERS.get(args.command)
    if handler is None:
        # argparse should already have caught this with `choices`, but the
        # extra guard keeps mypy happy and the error message clean.
        print(f"amp: unknown command: {args.command}", file=sys.stderr)
        return 1

    try:
        return asyncio.run(handler(args))
    except _UserError as exc:
        print(f"amp: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        # pydantic ValidationError is a subclass of ValueError. Bad request
        # shape is a user error per the contract above.
        print(f"amp: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Backend / store failure — exit 2 per the spec contract. We keep
        # the message terse; ``--verbose`` enables DEBUG logging if the
        # operator needs a stack trace.
        logger.debug("backend failure", exc_info=True)
        print(f"amp: backend error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
