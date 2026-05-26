"""tests/test_mypy_clean.py — Step 1.2 enforcement test for Core Rule 5.20.

Two tests (formerly @pytest.mark.slow — removed 2026-05-25, mypy runs ~20s):

  test_mypy_strict_clean         — happy path: backend/ passes mypy --strict
  test_mypy_catches_real_error   — negative path (Core Rule 2.2): verifies
                                    mypy actually catches a deliberate error,
                                    so a silently-broken mypy.ini doesn't
                                    pass everything by default.

Strategy ref: STEP_1_2_MYPY_STRATEGY.md §7; step 1.2.h.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_mypy_strict_clean() -> None:
    """backend/ passes mypy --strict cleanly with project config."""
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "backend/",
         "--config-file", str(REPO / "mypy.ini")],
        capture_output=True, text=True, cwd=str(REPO), timeout=120,
    )
    assert result.returncode == 0, (
        f"mypy reported errors:\n{result.stdout}\n{result.stderr}"
    )


def test_mypy_catches_real_error(tmp_path: Path) -> None:
    """Negative test: confirms mypy actually catches errors (Core Rule 2.2).

    Without this test, a misconfigured mypy.ini that silently passes
    everything would never be detected — the happy-path test above would
    pass spuriously and we would lose the safety net.
    """
    bad = tmp_path / "broken.py"
    bad.write_text(textwrap.dedent("""
        def add(a: int, b: int) -> int:
            return a + b

        result: int = add("not", "int")  # deliberate type error
    """).strip())
    result = subprocess.run(
        [sys.executable, "-m", "mypy", str(bad), "--strict"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0, (
        "mypy did not catch a deliberate type error; mypy.ini may be misconfigured"
    )
    assert "error" in result.stdout.lower()
