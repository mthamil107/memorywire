"""Validate every worked example in ``docs/spec/examples`` against its JSON Schema.

Each example file is a JSON object of the shape::

    {
      "description": "...",
      "_schema": "operations/remember",   # path under src/memorywire/schemas/, no .json
      "request":  { ... },                # the payload to validate
      "response": { ... }                 # optional, ignored here
    }

If ``_schema`` is omitted the script infers it from the example's parent
directory (e.g. ``docs/spec/examples/operations/remember/foo.json`` ->
``operations/remember``).

Exit codes:

* ``0`` — every example validated.
* ``1`` — at least one example failed (schema not found, JSON parse error,
  or schema validation error).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SCHEMAS_ROOT: Path = REPO_ROOT / "src" / "memorywire" / "schemas"
DEFAULT_EXAMPLES_ROOT: Path = REPO_ROOT / "docs" / "spec" / "examples"

# ANSI color codes; disabled automatically when stdout is not a TTY.
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _supports_color(stream: Any) -> bool:
    return bool(getattr(stream, "isatty", lambda: False)())


@dataclass(frozen=True)
class ExampleResult:
    """Outcome of validating a single example file."""

    path: Path
    schema_ref: str | None
    ok: bool
    error: str | None


def _iter_example_files(root: Path) -> Iterable[Path]:
    """Yield every ``*.json`` file under ``root`` recursively, sorted."""
    yield from sorted(p for p in root.rglob("*.json") if p.is_file())


def _infer_schema_ref(example_path: Path, examples_root: Path) -> str | None:
    """Infer a schema reference from the example's directory layout.

    For ``docs/spec/examples/operations/remember/basic.json`` returns
    ``operations/remember``. Returns ``None`` if the path is not nested
    deep enough under ``examples_root``.
    """
    try:
        rel = example_path.relative_to(examples_root)
    except ValueError:
        return None
    parts = rel.parts[:-1]  # drop filename
    if len(parts) < 2:
        return None
    return "/".join(parts[:2])


def _schema_path_for(ref: str) -> Path:
    """Map a schema reference like ``operations/remember`` to a JSON file."""
    return SCHEMAS_ROOT / f"{ref}.json"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _validate_one(example_path: Path, examples_root: Path) -> ExampleResult:
    """Validate a single example file and return a result record."""
    try:
        payload = _load_json(example_path)
    except (OSError, json.JSONDecodeError) as exc:
        return ExampleResult(example_path, None, False, f"failed to read example: {exc}")

    if not isinstance(payload, dict):
        return ExampleResult(
            example_path,
            None,
            False,
            "example root must be a JSON object",
        )

    ref_raw = payload.get("_schema") or payload.get("$schema")
    schema_ref: str | None
    if isinstance(ref_raw, str) and ref_raw and not ref_raw.startswith("http"):
        # Local-style ref ("operations/remember"); strip an optional .json suffix.
        schema_ref = ref_raw.removesuffix(".json")
    else:
        schema_ref = _infer_schema_ref(example_path, examples_root)

    if schema_ref is None:
        return ExampleResult(
            example_path,
            None,
            False,
            "could not determine schema (no '_schema' key and directory layout too shallow)",
        )

    schema_path = _schema_path_for(schema_ref)
    if not schema_path.is_file():
        return ExampleResult(
            example_path,
            schema_ref,
            False,
            f"schema file not found: {schema_path}",
        )

    try:
        schema = _load_json(schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        return ExampleResult(
            example_path, schema_ref, False, f"failed to read schema {schema_path}: {exc}"
        )

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # jsonschema raises SchemaError but be defensive
        return ExampleResult(example_path, schema_ref, False, f"schema is itself invalid: {exc}")

    if "request" not in payload:
        return ExampleResult(
            example_path,
            schema_ref,
            False,
            "example is missing required 'request' field",
        )

    instance = payload["request"]
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if errors:
        first: ValidationError = errors[0]
        loc = "/".join(str(p) for p in first.absolute_path) or "<root>"
        return ExampleResult(
            example_path,
            schema_ref,
            False,
            f"validation error at {loc}: {first.message}",
        )

    return ExampleResult(example_path, schema_ref, True, None)


def _print_result(
    result: ExampleResult,
    examples_root: Path,
    *,
    quiet: bool,
    use_color: bool,
) -> None:
    if quiet and result.ok:
        return
    try:
        rel = result.path.relative_to(examples_root)
    except ValueError:
        rel = result.path

    if use_color:
        tag = f"{_GREEN}PASS{_RESET}" if result.ok else f"{_RED}FAIL{_RESET}"
        ref_str = f" {_DIM}[{result.schema_ref}]{_RESET}" if result.schema_ref else ""
    else:
        tag = "PASS" if result.ok else "FAIL"
        ref_str = f" [{result.schema_ref}]" if result.schema_ref else ""

    print(f"  {tag} {rel}{ref_str}")
    if not result.ok and result.error:
        prefix = f"       {_YELLOW}->{_RESET} " if use_color else "       -> "
        print(f"{prefix}{result.error}")


def _print_summary(
    results: Sequence[ExampleResult],
    *,
    use_color: bool,
) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    failed = total - passed
    if use_color:
        head = f"{_GREEN}OK{_RESET}" if failed == 0 else f"{_RED}FAIL{_RESET}"
    else:
        head = "OK" if failed == 0 else "FAIL"
    print(f"\n{head}  {passed}/{total} examples passed ({failed} failed)")


def run(examples_root: Path, *, quiet: bool, use_color: bool) -> int:
    """Validate every example under ``examples_root`` and return an exit code."""
    if not examples_root.is_dir():
        print(
            f"verify_spec: examples directory does not exist: {examples_root}",
            file=sys.stderr,
        )
        return 1

    files = list(_iter_example_files(examples_root))
    if not files:
        print(
            f"verify_spec: no example files found under {examples_root}",
            file=sys.stderr,
        )
        # No examples is treated as success (the examples-author agent may not
        # have landed yet); the orchestrator can fail the run separately if a
        # missing examples dir is unacceptable.
        return 0

    if not quiet:
        print(f"verify_spec: validating {len(files)} example(s) under {examples_root}")

    results = [_validate_one(p, examples_root) for p in files]
    for result in results:
        _print_result(result, examples_root, quiet=quiet, use_color=use_color)
    _print_summary(results, use_color=use_color)

    return 0 if all(r.ok for r in results) else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_spec",
        description=(
            "Validate memorywire worked examples under docs/spec/examples against the "
            "JSON Schemas in src/memorywire/schemas."
        ),
    )
    parser.add_argument(
        "--examples",
        type=Path,
        default=DEFAULT_EXAMPLES_ROOT,
        help=f"Directory of example files (default: {DEFAULT_EXAMPLES_ROOT}).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file PASS output; still print failures and the summary.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color output (also implicit when stdout is not a TTY).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    use_color = (not args.no_color) and _supports_color(sys.stdout)
    return run(args.examples.resolve(), quiet=bool(args.quiet), use_color=use_color)


if __name__ == "__main__":
    raise SystemExit(main())
