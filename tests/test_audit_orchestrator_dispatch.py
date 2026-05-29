"""tests/test_audit_orchestrator_dispatch.py — Tests for audit_orchestrator_dispatch.py.

Tests the one-orchestrator-per-wave anti-pattern scanner using fixture run
directories.  The scanner is warn-only (always exits 0), so tests assert on
WARNING lines in output rather than exit codes.

The anti-pattern: multiple run-dirs each containing status files for different
waves, all written within the same hour.  This suggests one orchestrator session
per wave rather than one session per batch.

The correct pattern: one run-dir contains status files for ALL waves in a batch.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "audit_orchestrator_dispatch.py"


def _py() -> str:
    """Return Python interpreter path, preferring the project venv."""
    venv_py = REPO / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _run(repo_path: Path) -> tuple[int, str]:
    """Run the scanner against a fixture repo and return (rc, combined output)."""
    result = subprocess.run(
        [_py(), str(SCRIPT), "--repo", str(repo_path)],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout + result.stderr


def _make_status_file(
    run_dir: Path,
    wave_name: str,
    started: str,
) -> None:
    """Write a minimal status file into <run_dir>/status/<wave_name>.md."""
    status_dir = run_dir / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        # {wave_name} status
        **Last updated:** {started}
        **Wave branch:** wave/{wave_name.lower()} @ abc1234

        ## Result headline
        COMPLETE.
    """)
    (status_dir / f"{wave_name}.md").write_text(content, encoding="utf-8")


def _load_module():
    """Dynamically import the tool module for unit-level function tests."""
    spec = importlib.util.spec_from_file_location("audit_orchestrator_dispatch", SCRIPT)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Tests: exit code is always 0
# ---------------------------------------------------------------------------

def test_script_exits_0_always(tmp_path: Path) -> None:
    """Scanner must exit 0 regardless of findings (warn-only contract)."""
    rc, _ = _run(tmp_path)
    assert rc == 0


def test_no_archive_exits_0(tmp_path: Path) -> None:
    """No .claude/run-archive/ dir — exits 0 cleanly, no warnings."""
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "WARNING" not in out


# ---------------------------------------------------------------------------
# Tests: clean-pass cases (no anti-pattern)
# ---------------------------------------------------------------------------

def test_single_wave_per_run_no_warning(tmp_path: Path) -> None:
    """A run with one wave status file should not produce any WARNING."""
    archive = tmp_path / ".claude" / "run-archive"
    run = archive / "2026-05-29-batch4"
    _make_status_file(run, "S-58", "2026-05-29T05:41:11Z")

    rc, out = _run(tmp_path)
    assert rc == 0
    assert "WARNING" not in out


def test_multiple_waves_same_run_no_warning(tmp_path: Path) -> None:
    """Multiple waves in the SAME run-dir — one-orchestrator-per-batch (correct)."""
    archive = tmp_path / ".claude" / "run-archive"
    run = archive / "2026-05-29-batch4"
    # All waves within the same run-dir and same hour — this is the CORRECT pattern
    _make_status_file(run, "S-58", "2026-05-29T05:41:11Z")
    _make_status_file(run, "S-60", "2026-05-29T05:41:11Z")
    _make_status_file(run, "S-61", "2026-05-29T05:41:11Z")
    _make_status_file(run, "S-62", "2026-05-29T05:41:11Z")

    rc, out = _run(tmp_path)
    assert rc == 0
    assert "WARNING" not in out


def test_different_runs_different_hours_no_warning(tmp_path: Path) -> None:
    """Different batches running at different hours — no anti-pattern."""
    archive = tmp_path / ".claude" / "run-archive"
    _make_status_file(archive / "2026-05-28-batch3", "S-55", "2026-05-28T08:00:00Z")
    _make_status_file(archive / "2026-05-29-batch4", "S-58", "2026-05-29T05:00:00Z")

    rc, out = _run(tmp_path)
    assert rc == 0
    assert "WARNING" not in out


def test_non_wave_files_skipped(tmp_path: Path) -> None:
    """BATCH-N-COMPLETE.md and ROUND-N-COMPLETE.md are not counted as waves."""
    archive = tmp_path / ".claude" / "run-archive"
    run = archive / "2026-05-29-batch4"
    status = run / "status"
    status.mkdir(parents=True, exist_ok=True)

    # These should be ignored by the wave-file regex
    (status / "BATCH-4-COMPLETE.md").write_text(
        "**Last updated:** 2026-05-29T05:00:00Z\n", encoding="utf-8"
    )
    (status / "NEXT-BATCH-COMPLETE.md").write_text(
        "**Last updated:** 2026-05-29T05:01:00Z\n", encoding="utf-8"
    )
    # One real wave file — single wave, no warning
    _make_status_file(run, "S-58", "2026-05-29T05:30:00Z")

    rc, out = _run(tmp_path)
    assert rc == 0
    assert "WARNING" not in out


def test_same_wave_in_different_runs_no_warning(tmp_path: Path) -> None:
    """Same wave appears in two different run-archive entries (e.g. retry batch).

    Two runs covering the SAME wave at the same hour is not the anti-pattern;
    the anti-pattern is one run-per-wave for DIFFERENT waves.
    """
    archive = tmp_path / ".claude" / "run-archive"
    _make_status_file(archive / "2026-05-29-batch4a", "S-60", "2026-05-29T05:10:00Z")
    _make_status_file(archive / "2026-05-29-batch4b", "S-60", "2026-05-29T05:40:00Z")

    rc, out = _run(tmp_path)
    assert rc == 0
    assert "WARNING" not in out


# ---------------------------------------------------------------------------
# Tests: warn cases (anti-pattern detected)
# ---------------------------------------------------------------------------

def test_two_waves_in_separate_run_dirs_same_hour_warns(tmp_path: Path) -> None:
    """Two separate run-dirs each covering a different wave in the same hour → WARNING.

    This is the canonical one-orchestrator-per-wave anti-pattern: instead of
    one run-dir with both S-60 and S-61, there are two separate runs, one for each.
    """
    archive = tmp_path / ".claude" / "run-archive"
    _make_status_file(archive / "2026-05-29-batch-a", "S-60", "2026-05-29T05:10:00Z")
    _make_status_file(archive / "2026-05-29-batch-b", "S-61", "2026-05-29T05:40:00Z")

    rc, out = _run(tmp_path)
    assert rc == 0  # still exits 0
    assert "WARNING" in out
    assert "S-60" in out
    assert "S-61" in out


def test_three_waves_in_separate_run_dirs_warns(tmp_path: Path) -> None:
    """Three separate run-dirs each covering a different wave in the same hour."""
    archive = tmp_path / ".claude" / "run-archive"
    _make_status_file(archive / "2026-05-29-run-a", "S-60", "2026-05-29T05:05:00Z")
    _make_status_file(archive / "2026-05-29-run-b", "S-61", "2026-05-29T05:25:00Z")
    _make_status_file(archive / "2026-05-29-run-c", "S-62", "2026-05-29T05:50:00Z")

    rc, out = _run(tmp_path)
    assert rc == 0
    warnings = [line for line in out.splitlines() if line.startswith("WARNING")]
    assert len(warnings) >= 1
    assert "S-60" in out and "S-61" in out and "S-62" in out


def test_anti_pattern_in_one_hour_only(tmp_path: Path) -> None:
    """Anti-pattern in one hour does not affect clean hours."""
    archive = tmp_path / ".claude" / "run-archive"

    # Clean batch at 08:00: two waves in same run-dir
    clean_run = archive / "2026-05-28-batch3"
    _make_status_file(clean_run, "S-55", "2026-05-28T08:00:00Z")
    _make_status_file(clean_run, "S-56", "2026-05-28T08:10:00Z")

    # Anti-pattern at 05:00: two separate run-dirs, one wave each
    _make_status_file(archive / "2026-05-29-run-a", "S-60", "2026-05-29T05:10:00Z")
    _make_status_file(archive / "2026-05-29-run-b", "S-61", "2026-05-29T05:40:00Z")

    rc, out = _run(tmp_path)
    assert rc == 0
    warnings = [line for line in out.splitlines() if line.startswith("WARNING")]
    assert len(warnings) == 1
    assert "run-a" in warnings[0] or "run-b" in warnings[0] or "05:10" in out or "S-60" in out


def test_date_only_timestamp_separate_runs_no_warning(tmp_path: Path) -> None:
    """Status files with date-only timestamps are skipped — not enough precision.

    When only the date is known (no hour), we cannot determine whether two
    status files from different run-dirs were written in the same hour.
    The scanner skips '??' buckets to avoid false positives.
    """
    archive = tmp_path / ".claude" / "run-archive"
    run_a = archive / "2026-05-29-run-a"
    run_b = archive / "2026-05-29-run-b"
    (run_a / "status").mkdir(parents=True, exist_ok=True)
    (run_b / "status").mkdir(parents=True, exist_ok=True)

    (run_a / "status" / "S-60.md").write_text(
        "# S-60 status\n**Started:** 2026-05-29\n\nCOMPLETE.\n", encoding="utf-8"
    )
    (run_b / "status" / "S-61.md").write_text(
        "# S-61 status\n**Started:** 2026-05-29\n\nCOMPLETE.\n", encoding="utf-8"
    )

    rc, out = _run(tmp_path)
    assert rc == 0
    # Date-only timestamps give insufficient precision — no warning emitted
    assert "WARNING" not in out


def test_no_timestamp_status_file_does_not_crash(tmp_path: Path) -> None:
    """Status files without any timestamp are placed in 'unknown' bucket — no crash."""
    archive = tmp_path / ".claude" / "run-archive"
    run = archive / "2026-05-29-batch4"
    status = run / "status"
    status.mkdir(parents=True, exist_ok=True)
    (status / "S-58.md").write_text(
        "# S-58 status\nNo timestamp here.\n", encoding="utf-8"
    )

    rc, _out = _run(tmp_path)
    assert rc == 0  # must not crash


def test_real_repo_scans_without_warnings(tmp_path: Path) -> None:
    """The real repo's run-archive should not trigger any warnings.

    The existing archive shows correct ONE-orchestrator-per-batch usage
    (all waves within a batch share the same run-dir).
    """
    rc, out = _run(REPO)
    assert rc == 0
    # The real archive should be clean — if this fails it means the actual
    # run history shows the anti-pattern and should be investigated.
    assert "WARNING" not in out, (
        "Real run-archive contains possible one-orchestrator-per-wave anti-pattern:\n" + out
    )


# ---------------------------------------------------------------------------
# Tests: import-level correctness (pure-Python unit checks)
# ---------------------------------------------------------------------------

class TestParseHourBucket:
    """Unit tests for _parse_hour_bucket without subprocess."""

    def test_iso_timestamp(self) -> None:
        mod = _load_module()
        text = "**Last updated:** 2026-05-29T05:41:11Z\n"
        assert mod._parse_hour_bucket(text) == "2026-05-29 05"

    def test_spaced_timestamp(self) -> None:
        mod = _load_module()
        text = "**Started:** 2026-05-28 10:30:00\n"
        assert mod._parse_hour_bucket(text) == "2026-05-28 10"

    def test_date_only(self) -> None:
        mod = _load_module()
        text = "**Last updated:** 2026-05-28\n"
        assert mod._parse_hour_bucket(text) == "2026-05-28 ??"

    def test_no_timestamp(self) -> None:
        mod = _load_module()
        assert mod._parse_hour_bucket("No timestamp here.") == "unknown"
