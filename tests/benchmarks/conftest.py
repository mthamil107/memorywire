"""Shared conftest for the benchmark suite.

Some benchmark tests import from ``scripts.lib.eval_common``. The pyproject
``[tool.pytest.ini_options].pythonpath`` directive is the documented way to
make the repo root importable, but in practice it doesn't reliably trigger
before pytest collects test modules on every runner (notably Windows CI),
so we inject the repo root into ``sys.path`` here belt-and-braces. This
runs before any test module in this directory is imported, so the
``from scripts.lib.eval_common import ...`` line at the top of
``test_eval_harness.py`` resolves cleanly even on a cold runner.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_STR = str(_REPO_ROOT)

if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)
