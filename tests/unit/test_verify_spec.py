"""Unit tests for ``scripts/verify_spec.py``.

These tests fabricate temporary example directories on disk and exercise
the script both via direct ``main()`` invocation and via subprocess so we
cover both paths developers actually use.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_spec.py"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _valid_remember_example() -> dict[str, object]:
    return {
        "description": "valid remember example",
        "_schema": "operations/remember",
        "request": {
            "agent_id": "test-agent",
            "type": "semantic",
            "content": "Alice is allergic to peanuts",
            "confidence": 0.9,
        },
        "response": {
            "id": "01HZK000000000000000000000",
            "stored_at": 1716700000000,
            "stores": ["sqlite-vec"],
            "pending_approval": False,
            "approval_url": None,
        },
    }


def _invalid_remember_example() -> dict[str, object]:
    # Missing required "type" and "content" fields.
    return {
        "description": "invalid remember example - missing required fields",
        "_schema": "operations/remember",
        "request": {"agent_id": "test-agent"},
    }


def _valid_recall_example_inferred_ref() -> dict[str, object]:
    # No _schema; ref should be inferred from "operations/recall" dir.
    return {
        "description": "valid recall example with inferred schema",
        "request": {
            "agent_id": "test-agent",
            "query": "what do I know about Alice?",
            "k": 3,
        },
    }


@pytest.fixture
def tmp_examples_dir(tmp_path: Path) -> Path:
    """Empty examples root inside a pytest temp dir."""
    root = tmp_path / "examples"
    root.mkdir()
    return root


# --- direct main() invocation -------------------------------------------------


def _import_main() -> object:
    """Import verify_spec.main() without requiring scripts/ to be a package."""
    import importlib.util

    name = "verify_spec_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec_module so dataclass annotation resolution can find
    # the module in sys.modules (Python 3.13 dataclasses use cls.__module__).
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_main_returns_zero_when_all_valid(tmp_examples_dir: Path) -> None:
    _write_json(
        tmp_examples_dir / "operations" / "remember" / "ok.json",
        _valid_remember_example(),
    )
    _write_json(
        tmp_examples_dir / "operations" / "recall" / "ok.json",
        _valid_recall_example_inferred_ref(),
    )

    module = _import_main()
    rc = module.main(["--examples", str(tmp_examples_dir), "--no-color"])  # type: ignore[attr-defined]
    assert rc == 0


def test_main_returns_one_when_any_invalid(tmp_examples_dir: Path) -> None:
    _write_json(
        tmp_examples_dir / "operations" / "remember" / "ok.json",
        _valid_remember_example(),
    )
    _write_json(
        tmp_examples_dir / "operations" / "remember" / "bad.json",
        _invalid_remember_example(),
    )

    module = _import_main()
    rc = module.main(["--examples", str(tmp_examples_dir), "--no-color"])  # type: ignore[attr-defined]
    assert rc == 1


def test_main_zero_on_empty_examples_dir(tmp_examples_dir: Path) -> None:
    module = _import_main()
    rc = module.main(["--examples", str(tmp_examples_dir), "--no-color"])  # type: ignore[attr-defined]
    assert rc == 0


def test_main_one_when_examples_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    module = _import_main()
    rc = module.main(["--examples", str(missing), "--no-color"])  # type: ignore[attr-defined]
    assert rc == 1


def test_main_one_when_schema_ref_unknown(tmp_examples_dir: Path) -> None:
    payload = _valid_remember_example()
    payload["_schema"] = "operations/no_such_op"
    _write_json(tmp_examples_dir / "operations" / "remember" / "bad-ref.json", payload)

    module = _import_main()
    rc = module.main(["--examples", str(tmp_examples_dir), "--no-color"])  # type: ignore[attr-defined]
    assert rc == 1


def test_main_one_when_request_missing(tmp_examples_dir: Path) -> None:
    payload = _valid_remember_example()
    del payload["request"]
    _write_json(tmp_examples_dir / "operations" / "remember" / "no-request.json", payload)

    module = _import_main()
    rc = module.main(["--examples", str(tmp_examples_dir), "--no-color"])  # type: ignore[attr-defined]
    assert rc == 1


# --- subprocess invocation ----------------------------------------------------


def test_subprocess_exit_zero_when_all_valid(tmp_examples_dir: Path) -> None:
    _write_json(
        tmp_examples_dir / "operations" / "remember" / "ok.json",
        _valid_remember_example(),
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--examples", str(tmp_examples_dir), "--no-color"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_subprocess_exit_one_when_invalid(tmp_examples_dir: Path) -> None:
    _write_json(
        tmp_examples_dir / "operations" / "remember" / "bad.json",
        _invalid_remember_example(),
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--examples", str(tmp_examples_dir), "--no-color"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL" in result.stdout
