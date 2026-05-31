"""Phase 0 smoke tests — verify the package imports and the CLI is wired up."""

from __future__ import annotations

import subprocess
import sys


def test_import_memorywire() -> None:
    import memorywire

    assert isinstance(memorywire.__version__, str)
    assert memorywire.__version__


def test_cli_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "memorywire.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "memorywire" in result.stdout.lower()


def test_cli_version_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "memorywire.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "memorywire" in result.stdout.lower()
