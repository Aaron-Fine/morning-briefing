"""Run ruff linter as a pytest test.

This ensures lint issues (unused imports, undefined names, dead code) are caught
by the normal test suite rather than requiring a separate CI step or manual check.
"""

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_ruff_lint():
    """All Python files must pass ruff lint checks."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", str(_ROOT)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Show the full ruff output as the assertion message
        raise AssertionError(f"ruff found lint issues:\n{result.stdout}{result.stderr}")
