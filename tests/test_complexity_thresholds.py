"""tests/test_complexity_thresholds.py — Step 1.4 enforcement test for Core Rule 5.22 / 8.1.

Validates that backend/ stays within the configured complexity threshold (15
per ruff.toml [lint.mccabe] max-complexity) on every test run. Catches drift
from new code that bypasses the pre-commit ruff check (--no-verify, manual
rebase). Per-file-ignores in ruff.toml are honored by ruff itself.

Strategy ref: STEP_1_4_COMPLEXITY_STRATEGY.md §5; step 1.4.f.
"""
from __future__ import annotations

import json
import subprocess
import sys


def test_no_new_c901_violations() -> None:
    """ruff --select C901 must report no findings (per-file-ignores honored)."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "backend/", "backend/scripts/",
         "--select", "C901", "--output-format=json"],
        capture_output=True, text=True,
    )
    findings: list[dict] = (
        json.loads(result.stdout) if result.stdout.strip().startswith("[") else []
    )
    assert not findings, (
        f"{len(findings)} C901 violations found above threshold "
        f"(see ruff.toml [lint.mccabe] max-complexity and [lint.per-file-ignores]). "
        f"Refactor the function or add a per-file-ignore with a backlog TODO entry. "
        f"First 5:\n"
        + "\n".join(
            f"  {f['filename']}:{f['location']['row']} {f['message']}"
            for f in findings[:5]
        )
    )
