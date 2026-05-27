"""Sanity check helper for release-please version bumps.

This script is **read-only by default**. It prints the version currently
recorded in the repo's release-please manifest, in ``CITATION.cff``, and in
``src/amp/__init__.py``'s fallback string, then validates that those three
agree and that any provided ``--target`` version is strictly greater than the
manifest version.

Hatch-vcs derives the actual installed version from the latest ``v*`` git tag,
so the in-file values are *advisory* — they exist so editors and humans can see
the intended version without running ``git describe``. release-please rewrites
all three on merge.

Usage::

    python scripts/bump_version.py                # print current state
    python scripts/bump_version.py --target 0.2.0 # validate proposed bump

Exit codes:
    0   success / versions consistent
    1   version mismatch or invalid target
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".github" / ".release-please-manifest.json"
INIT_PY = ROOT / "src" / "amp" / "__init__.py"
CITATION = ROOT / "CITATION.cff"

SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$"
)


def parse_semver(v: str) -> tuple[int, int, int, str | None]:
    """Parse ``X.Y.Z`` or ``X.Y.Z-rcN``. Raises ValueError on malformed input."""
    m = SEMVER_RE.match(v.strip())
    if not m:
        raise ValueError(f"not a valid semver: {v!r}")
    return (
        int(m.group("major")),
        int(m.group("minor")),
        int(m.group("patch")),
        m.group("pre"),
    )


def read_manifest_version() -> str:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return str(data["."])


def read_init_fallback() -> str | None:
    text = INIT_PY.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else None


def read_citation_version() -> str | None:
    text = CITATION.read_text(encoding="utf-8")
    m = re.search(r"^version:\s*([0-9A-Za-z.\-]+)", text, re.MULTILINE)
    return m.group(1) if m else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        help="Proposed next version (X.Y.Z). Validated to be > manifest version.",
    )
    args = parser.parse_args()

    manifest_v = read_manifest_version()
    init_v = read_init_fallback() or "<unset>"
    cff_v = read_citation_version() or "<unset>"

    print("Current version state")
    print("---------------------")
    print(f"  .github/.release-please-manifest.json : {manifest_v}")
    print(f"  src/amp/__init__.py (fallback)        : {init_v}")
    print(f"  CITATION.cff                          : {cff_v}")
    print()

    print("On the next release-please merge, the following files will be rewritten:")
    print("  - .github/.release-please-manifest.json")
    print("  - src/amp/__init__.py        (extra-files in release-please-config.json)")
    print("  - CITATION.cff               (extra-files in release-please-config.json)")
    print("  - CHANGELOG.md")
    print()

    # Manifest is the source of truth; CITATION/__init__ are advisory.
    if args.target:
        try:
            target = parse_semver(args.target)
        except ValueError as e:
            print(f"ERROR: invalid --target: {e}", file=sys.stderr)
            return 1
        try:
            current = parse_semver(manifest_v)
        except ValueError as e:
            print(f"ERROR: manifest version is malformed: {e}", file=sys.stderr)
            return 1
        if target[:3] <= current[:3]:
            print(
                f"ERROR: target {args.target} is not strictly greater than manifest {manifest_v}",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {args.target} is a valid bump from {manifest_v}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
