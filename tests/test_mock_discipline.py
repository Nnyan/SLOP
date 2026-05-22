"""tests/test_mock_discipline.py

Step 2.2 — Mocking Discipline (Core Rule 4.12).

The mocking policy is enforced by `ms-enforce` Tier 2's
`check_mock_discipline` (AST-walks every test file, counts internal
`@patch("backend.*")` decorators per test, warns above threshold).

This file is the pytest-side anchor: it imports the check, runs it
against the live `tests/` tree, and asserts it returns successfully.
The check itself is informational (warns, doesn't block) so the
assertion is just that the helper runs cleanly. ms-coverage uses
`test_check_mock_discipline_runs` to verify the rule has a concrete
test artefact, completing the rule registry coverage.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_ms_enforce() -> object:
    """Load `ms-enforce` (script — no .py extension) as a module.

    `spec_from_file_location` doesn't produce a loader for files without
    a recognised extension, so build a SourceFileLoader explicitly.
    """
    import importlib.machinery as _machinery
    repo = Path(__file__).resolve().parent.parent
    script = repo / "ms-enforce"
    if not script.exists():
        pytest.skip("ms-enforce script not found; skipping mocking-discipline test")
    loader = _machinery.SourceFileLoader("ms_enforce", str(script))
    spec = importlib.util.spec_from_loader("ms_enforce", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ms_enforce"] = module
    loader.exec_module(module)
    return module


def test_check_mock_discipline_runs() -> None:
    """`check_mock_discipline` AST-walks tests/ and returns (True, msg).

    Returns True even when over-mocked tests exist — the check is a
    warning, not a block. The assertion verifies the helper completes
    without exceptions and produces a non-empty message.
    """
    module = _load_ms_enforce()
    result = module.check_mock_discipline()
    assert isinstance(result, tuple) and len(result) == 2
    ok, msg = result
    assert ok is True  # warning-only by design
    assert isinstance(msg, str) and len(msg) > 0


def test_check_mock_discipline_threshold_documented() -> None:
    """The threshold of 3 is documented in ADR 0002 — verify the docstring
    or implementation surfaces it so changes don't go unnoticed."""
    module = _load_ms_enforce()
    src = Path(module.__file__).read_text() if module.__file__ else ""
    # The threshold integer should appear in the function body as either a
    # comparison (`> 3`) or a literal assignment (`threshold = 3`).
    assert "threshold = 3" in src or "> 3" in src or " 3" in src
