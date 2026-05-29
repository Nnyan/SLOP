"""tests/test_validate_wave_file.py — Tests for the wave-file preflight validator.

Covers three scenarios:
  (a) A wave file with all valid claims → validator exits 0.
  (b) A wave file referencing a non-existent claimed-existing path → exits 1.
  (c) A wave file with a wrong inbound-ref count → exits 1.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the validator module directly (it has a hyphen in its name so we
# cannot use a regular import statement).
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parent.parent
_TOOL = _REPO / "tools" / "validate-wave-file.py"


def _load_vwf():
    """Import tools/validate-wave-file.py as a module."""
    spec = importlib.util.spec_from_file_location("validate_wave_file", _TOOL)
    assert spec and spec.loader, f"Could not load {_TOOL}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


vwf = _load_vwf()


# ---------------------------------------------------------------------------
# Helper: run the tool as a subprocess and return its exit code + stdout.
# ---------------------------------------------------------------------------


def _run_validator(wave_path: Path) -> tuple[int, str]:
    """Run validate-wave-file.py as a subprocess, return (returncode, output)."""
    result = subprocess.run(
        [sys.executable, str(_TOOL), str(wave_path)],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wave_dir(tmp_path: Path) -> Path:
    """Return a tmp directory acting as the repo root for fixture wave files."""
    return tmp_path


@pytest.fixture()
def existing_file(tmp_path: Path) -> Path:
    """Create a real file that wave files can reference as claimed-existing."""
    f = tmp_path / "real_existing_file.py"
    f.write_text("# placeholder\n")
    return f


# ---------------------------------------------------------------------------
# (a) All-valid wave file → exit 0
# ---------------------------------------------------------------------------


class TestValidWaveFile:
    """Validator exits 0 when all claimed-existing paths are present."""

    def test_valid_wave_exits_0(self, tmp_path: Path) -> None:
        """Wave file referencing only existing files and 'new' deliverables passes."""
        # Create a real file that will be referenced.
        real = tmp_path / "backend" / "platform" / "wizard.py"
        real.parent.mkdir(parents=True)
        real.write_text("# real file\n")

        wave = tmp_path / "test-wave-valid.md"
        wave.write_text(
            "# Test Wave\n\n"
            "## Context\n"
            "This wave modifies `backend/platform/wizard.py`.\n\n"
            "## Deliverables\n"
            "1. Build `tools/new-tool.py` (new).\n"
            "2. Add `tests/test_new_tool.py` with tests.\n\n"
            "## Verification\n"
            "1. Run tests, see pass.\n"
        )
        # The validator resolves paths from REPO (parent of 'tools/'), but
        # we call validate() directly to stay repo-root agnostic in tests.
        # We'll monkey-patch REPO for this test.
        original_repo = vwf.REPO
        try:
            vwf.REPO = tmp_path
            failures, warnings = vwf.validate(wave)
        finally:
            vwf.REPO = original_repo

        assert failures == [], f"Expected no failures, got: {failures}"

    def test_subprocess_valid_wave_exits_0(self, tmp_path: Path) -> None:
        """Subprocess invocation exits 0 on a wave with only valid paths."""
        # Create a minimal wave file that references only paths that exist
        # in the actual repo (the tool resolves from its own repo root).
        wave = tmp_path / "wave-all-valid.md"
        wave.write_text(
            "# Minimal Wave\n\n"
            "## Context\n"
            "Uses `backend/platform/wizard.py` which exists.\n\n"
            "## Deliverables\n"
            "1. Create `tools/new-future-tool.py` (new).\n"
            "2. Add `tests/test_new_future.py` tests.\n"
        )
        rc, output = _run_validator(wave)
        assert rc == 0, f"Expected exit 0, got {rc}. Output:\n{output}"


# ---------------------------------------------------------------------------
# (b) Wave file referencing a missing claimed-existing path → exit 1
# ---------------------------------------------------------------------------


class TestMissingPathFails:
    """Validator exits 1 when a claimed-existing path is missing."""

    def test_missing_claimed_existing_path_exits_1(self, tmp_path: Path) -> None:
        """Wave file referencing a non-existent path fails."""
        wave = tmp_path / "wave-bad-path.md"
        wave.write_text(
            "# Bad Wave\n\n"
            "## Context\n"
            "This wave modifies `backend/api/totally_nonexistent_router.py`.\n"
        )
        original_repo = vwf.REPO
        try:
            vwf.REPO = tmp_path
            failures, warnings = vwf.validate(wave)
        finally:
            vwf.REPO = original_repo

        assert any("backend/api/totally_nonexistent_router.py" in f for f in failures), (
            f"Expected failure for missing path, got: {failures}"
        )

    def test_subprocess_missing_path_exits_1(self, tmp_path: Path) -> None:
        """Subprocess invocation exits 1 when a claimed-existing path is missing."""
        wave = tmp_path / "wave-missing-path.md"
        wave.write_text(
            "# Missing Path Wave\n\n"
            "## Context\n"
            "References `backend/api/this_file_does_not_exist_at_all.py`.\n"
        )
        rc, output = _run_validator(wave)
        assert rc == 1, f"Expected exit 1, got {rc}. Output:\n{output}"
        assert "MISSING" in output or "FAIL" in output, (
            f"Expected MISSING/FAIL in output:\n{output}"
        )

    def test_new_path_keyword_suppresses_failure(self, tmp_path: Path) -> None:
        """A path on a line with 'new' keyword is treated as to-be-created, not existing."""
        wave = tmp_path / "wave-new-path.md"
        wave.write_text(
            "# Wave With New File\n\n"
            "## Deliverables\n"
            "1. Create new `tools/brand-new-tool.py` (new).\n"
        )
        original_repo = vwf.REPO
        try:
            vwf.REPO = tmp_path
            failures, warnings = vwf.validate(wave)
        finally:
            vwf.REPO = original_repo

        # Should NOT fail because 'new' keyword marks the path as to-be-created.
        assert failures == [], f"Expected no failures for new-path, got: {failures}"

    def test_command_invocation_path_not_claimed_existing(self, tmp_path: Path) -> None:
        """Paths inside backtick command invocations are not claimed-existing."""
        wave = tmp_path / "wave-command.md"
        wave.write_text(
            "# Wave With Command\n\n"
            "## Verification\n"
            "1. Run `python3 -m pytest tests/nonexistent_test.py -v` to verify.\n"
        )
        original_repo = vwf.REPO
        try:
            vwf.REPO = tmp_path
            failures, warnings = vwf.validate(wave)
        finally:
            vwf.REPO = original_repo

        # The path inside the command invocation should not be a failure
        # because it's inside a shell command context, not a path claim.
        assert failures == [], (
            f"Expected no failures for command-invocation path, got: {failures}"
        )


# ---------------------------------------------------------------------------
# (c) Wave file with wrong inbound-ref count → exit 1
# ---------------------------------------------------------------------------


class TestInboundRefMismatch:
    """Validator exits 1 when an inbound-ref count doesn't match reality."""

    def test_wrong_inbound_ref_count_exits_1(self, tmp_path: Path) -> None:
        """Wave file claiming 999 references for a unique string fails."""
        # Use a string that almost certainly has 0 references in the repo.
        unique_marker = "ZZZZ_UNIQUE_MARKER_THAT_DOES_NOT_EXIST_IN_REPO_ZZZZ"
        wave = tmp_path / "wave-bad-refcount.md"
        wave.write_text(
            f"# Bad Ref Count Wave\n\n"
            f"## Context\n"
            f"`{unique_marker}` is referenced 999 times in the codebase.\n"
        )
        original_repo = vwf.REPO
        try:
            vwf.REPO = tmp_path.parent  # Use actual repo root for grep
            failures, warnings = vwf.validate(wave)
        finally:
            vwf.REPO = original_repo

        assert any("INBOUND-REF MISMATCH" in f for f in failures), (
            f"Expected inbound-ref mismatch failure, got: {failures}"
        )

    def test_subprocess_wrong_refcount_exits_1(self, tmp_path: Path) -> None:
        """Subprocess invocation exits 1 when inbound-ref count is wrong."""
        unique_marker = "ZZZZ_SUBPROCESS_UNIQUE_MARKER_9876543210_ZZZZ"
        wave = tmp_path / "wave-wrong-refcount.md"
        wave.write_text(
            f"# Wrong Ref Count\n\n"
            f"## Context\n"
            f"`{unique_marker}` is referenced 42 times in the codebase.\n"
        )
        rc, output = _run_validator(wave)
        assert rc == 1, f"Expected exit 1, got {rc}. Output:\n{output}"
        assert "INBOUND-REF MISMATCH" in output or "MISMATCH" in output, (
            f"Expected MISMATCH in output:\n{output}"
        )

    def test_correct_inbound_ref_count_passes(self, tmp_path: Path) -> None:
        """A wave that claims the correct reference count passes.

        The marker string below appears exactly once in the real repo — inside
        this test file itself — so claiming "referenced 1 times" is correct and
        the validator should pass with no failures.

        Marker: ZZZZ_CORRECT_COUNT_MARKER_EXISTS_IN_TEST_ZZZZ
        """
        # This exact string is in this test file (the line just above).
        # grep -l finds exactly 1 file (this test file).
        unique_marker = "ZZZZ_CORRECT_COUNT_MARKER_EXISTS_IN_TEST_ZZZZ"
        wave = tmp_path / "wave-correct-refcount.md"
        wave.write_text(
            f"# Correct Ref Count\n\n"
            f"## Context\n"
            f"`{unique_marker}` is referenced 1 times in the codebase.\n"
        )
        # vwf.REPO is the actual repo root — grep will find the test file.
        failures, warnings = vwf.validate(wave)

        # Should pass: 1 claim matches reality (string appears once in the repo).
        assert failures == [], (
            f"Expected no failures for correct count claim, got: {failures}"
        )
