"""amp command-line entry point.

The full CLI (``amp remember``/``amp recall``/``amp forget``) is implemented in
Phase 5. This stub keeps the entry point installable so ``pip install -e .``
exposes the ``amp`` script.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from amp import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``amp`` CLI. Returns the process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in {"-h", "--help"}:
        _print_usage()
        return 0
    if args[0] in {"-V", "--version"}:
        print(f"amp {__version__}")
        return 0

    cmd = args[0]
    print(
        f"amp: command '{cmd}' is not yet implemented (Phase 5 deliverable).",
        file=sys.stderr,
    )
    return 1


def _print_usage() -> None:
    print(f"amp {__version__} — Agent Memory Protocol CLI")
    print()
    print("Usage:")
    print("  amp remember <text> [--type TYPE] [--user USER]")
    print("  amp recall   <query> [-k N] [--type TYPE]")
    print("  amp forget   --filter EXPR")
    print()
    print("The full CLI ships in Phase 5; see docs/spec/v0.md for the protocol.")


if __name__ == "__main__":
    raise SystemExit(main())
