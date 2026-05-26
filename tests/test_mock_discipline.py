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

    `ok` is True by construction (the check is warning-only — it cannot
    block), so we don't bother asserting on it. Instead we pin the
    *message contract* so a regression in the header format, the
    threshold phrasing, or the ADR pointer is surfaced.
    """
    module = _load_ms_enforce()
    result = module.check_mock_discipline()
    assert isinstance(result, tuple) and len(result) == 2
    ok, msg = result
    assert isinstance(ok, bool)
    assert isinstance(msg, str) and msg
    # Message header is the rule contract: "<n> test(s) stack more than 3
    # internal mocks (boundary mocks are fine; see docs/adr/0002-mocking-policy.md)".
    # If any of these phrases drift, ms-enforce output formatting has changed
    # and Tier 2 dashboards/log scrapers will silently miss the warning.
    assert "more than 3 internal mocks" in msg
    assert "boundary mocks are fine" in msg
    assert "docs/adr/0002-mocking-policy.md" in msg


def test_check_mock_discipline_threshold_documented() -> None:
    """The threshold of 3 is documented in ADR 0002 — verify the source
    pins the literal AND the canonical comparison so a silent loosening
    (e.g. bumping to 5 with no ADR update) trips this test.

    Replaces an earlier `" 3" in src` substring check that matched any
    space-3 sequence anywhere in the file — vacuous by construction.
    """
    module = _load_ms_enforce()
    assert module.__file__, "ms-enforce module has no __file__"
    src = Path(module.__file__).read_text()
    assert "threshold = 3" in src, "threshold literal `threshold = 3` missing"
    assert "if internal > threshold" in src, (
        "canonical `if internal > threshold` comparison missing — "
        "if you loosened the comparison, update ADR 0002 too"
    )
    assert "Rule 4.12" in src, "Rule 4.12 ADR attribution missing from ms-enforce"
