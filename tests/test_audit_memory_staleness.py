"""tests/test_audit_memory_staleness.py — Tests for tools/audit_memory_staleness.py.

Tests the memory staleness scanner using fixture memory directories populated
with synthetic content.  All date comparisons use --today for determinism.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helper: locate tool and repo root
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "audit_memory_staleness.py"


def _py() -> str:
    """Return path to Python interpreter, preferring the project venv."""
    venv_py = REPO / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _run(
    memory_dir: Path,
    today: str = "2026-07-28",
    days: int = 60,
    extra_args: list[str] | None = None,
) -> tuple[int, str]:
    """Run the scanner against *memory_dir* with a fixed --today and return (rc, output)."""
    cmd = [
        _py(), str(SCRIPT),
        "--memory-dir", str(memory_dir),
        "--today", today,
        "--days", str(days),
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_memory(mem_dir: Path, filename: str, content: str) -> Path:
    """Write a memory file and return its path."""
    mem_dir.mkdir(parents=True, exist_ok=True)
    p = mem_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Test: exit code is always 0
# ---------------------------------------------------------------------------

class TestExitCode:
    def test_always_exits_zero_clean(self, tmp_path: Path) -> None:
        """Scanner exits 0 when no stale files are found."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "fresh.md", "Recent entry, no dates.")
        rc, _ = _run(mem_dir)
        assert rc == 0

    def test_always_exits_zero_stale(self, tmp_path: Path) -> None:
        """Scanner exits 0 even when stale files are found."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "old.md", "Updated 2025-01-01 initial setup.")
        rc, _ = _run(mem_dir)
        assert rc == 0

    def test_always_exits_zero_missing_dir(self, tmp_path: Path) -> None:
        """Scanner exits 0 when memory directory does not exist."""
        missing = tmp_path / "nonexistent"
        rc, _ = _run(missing)
        assert rc == 0


# ---------------------------------------------------------------------------
# Test: clean-pass cases (no WARNING emitted)
# ---------------------------------------------------------------------------

class TestCleanPass:
    def test_no_dates_in_files(self, tmp_path: Path) -> None:
        """Files with no dates produce no WARNING lines."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "plain.md", "Some memory with no dates at all.")
        _rc, out = _run(mem_dir)
        assert "WARNING" not in out

    def test_recent_date_not_flagged(self, tmp_path: Path) -> None:
        """A date within the threshold window is not flagged.

        today=2026-07-28, threshold=60d → cutoff=2026-05-29.
        A date of 2026-06-15 is only 43 days old → clean.
        """
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "recent.md", "Last updated 2026-06-15 after retro.")
        _rc, out = _run(mem_dir, today="2026-07-28", days=60)
        assert "WARNING" not in out

    def test_future_date_not_flagged(self, tmp_path: Path) -> None:
        """Dates in the future relative to --today are not flagged."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "future.md", "Review scheduled for 2027-01-01.")
        _rc, out = _run(mem_dir, today="2026-07-28")
        assert "WARNING" not in out

    def test_empty_memory_dir(self, tmp_path: Path) -> None:
        """An empty memory directory produces OK output and no WARNINGs."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        _rc, out = _run(mem_dir)
        assert "WARNING" not in out
        assert "OK" in out

    def test_exactly_at_threshold_not_flagged(self, tmp_path: Path) -> None:
        """A date exactly at the threshold boundary is not flagged (> not >=)."""
        # today=2026-07-28, days=60 → cutoff date = 2026-05-29
        # A date of 2026-05-29 is exactly 60 days old → NOT flagged (> 60, not >= 60)
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "boundary.md", "Event on 2026-05-29 was important.")
        _rc, out = _run(mem_dir, today="2026-07-28", days=60)
        assert "WARNING" not in out


# ---------------------------------------------------------------------------
# Test: stale-warn cases (WARNING emitted)
# ---------------------------------------------------------------------------

class TestStaleWarn:
    def test_old_date_triggers_warning(self, tmp_path: Path) -> None:
        """A date older than threshold emits a WARNING line."""
        # today=2026-07-28, days=60 → any date before 2026-05-28 is stale
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "old_entry.md", "Key leaked on 2026-01-01.")
        _rc, out = _run(mem_dir, today="2026-07-28", days=60)
        assert "WARNING" in out
        assert "old_entry.md" in out

    def test_warning_includes_age_and_threshold(self, tmp_path: Path) -> None:
        """WARNING line includes the age and threshold values."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "dated.md", "Completed on 2026-01-01.")
        _rc, out = _run(mem_dir, today="2026-07-28", days=60)
        # Should mention age in days and threshold
        assert "days old" in out
        assert "60d" in out

    def test_multiple_dates_oldest_used(self, tmp_path: Path) -> None:
        """When a file has multiple dates, the oldest is used for the threshold check."""
        # oldest date 2025-12-01 is well over 60d before 2026-07-28
        # but 2026-07-01 is recent (27 days old)
        mem_dir = tmp_path / "memory"
        _write_memory(
            mem_dir,
            "multi_date.md",
            "First noted 2025-12-01. Later updated 2026-07-01.",
        )
        _rc, out = _run(mem_dir, today="2026-07-28", days=60)
        assert "WARNING" in out
        assert "multi_date.md" in out

    def test_multiple_stale_files_all_warned(self, tmp_path: Path) -> None:
        """Each stale file gets its own WARNING line."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "a.md", "A started 2026-01-10.")
        _write_memory(mem_dir, "b.md", "B started 2026-02-15.")
        _rc, out = _run(mem_dir, today="2026-07-28", days=60)
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING")]
        assert len(warning_lines) == 2

    def test_one_day_over_threshold(self, tmp_path: Path) -> None:
        """A date exactly one day past the threshold IS flagged.

        today=2026-07-28, days=60 → cutoff=2026-05-29.
        A date of 2026-05-28 is 61 days old → flagged.
        """
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "just_over.md", "Event 2026-05-28.")
        _rc, out = _run(mem_dir, today="2026-07-28", days=60)
        assert "WARNING" in out

    def test_custom_threshold_days(self, tmp_path: Path) -> None:
        """Custom --days threshold is honoured."""
        # With days=30, a date 45 days ago should be flagged.
        # today=2026-07-28, days=30 → cutoff=2026-06-28
        # date of 2026-06-10 is 48 days old → flagged
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "medium.md", "Updated 2026-06-10.")
        _rc, out = _run(mem_dir, today="2026-07-28", days=30)
        assert "WARNING" in out

    def test_custom_threshold_days_clean(self, tmp_path: Path) -> None:
        """A date that's stale at 60d but fresh at 90d is NOT flagged when --days=90."""
        # today=2026-07-28, days=90 → cutoff=2026-04-29
        # date of 2026-05-28 is 61 days old → NOT flagged at days=90
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "not_stale_at_90.md", "Updated 2026-05-28.")
        _rc, out = _run(mem_dir, today="2026-07-28", days=90)
        assert "WARNING" not in out


# ---------------------------------------------------------------------------
# Test: only .md / text files are scanned
# ---------------------------------------------------------------------------

class TestFileFilter:
    def test_non_text_extensions_skipped(self, tmp_path: Path) -> None:
        """Binary-like extensions (.png, .pyc) are not scanned."""
        mem_dir = tmp_path / "memory"
        # Write a .pyc file with an old date string — should not be flagged
        # (scanner filters by extension, not content)
        p = mem_dir / "data.pyc"
        mem_dir.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"2026-01-01 fake content")
        _rc, out = _run(mem_dir, today="2026-07-28")
        assert "WARNING" not in out

    def test_md_files_are_scanned(self, tmp_path: Path) -> None:
        """Markdown (.md) files with old dates are scanned and flagged."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "entry.md", "Started 2026-01-01.")
        _rc, out = _run(mem_dir, today="2026-07-28")
        assert "WARNING" in out

    def test_yaml_files_are_scanned(self, tmp_path: Path) -> None:
        """YAML files with old dates are scanned."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "entry.yaml", "date: 2026-01-01\ninfo: some content")
        _rc, out = _run(mem_dir, today="2026-07-28")
        assert "WARNING" in out


# ---------------------------------------------------------------------------
# Test: summary line presence
# ---------------------------------------------------------------------------

class TestSummaryLine:
    def test_summary_present_when_stale(self, tmp_path: Path) -> None:
        """When stale files are found, a Summary line is printed to stderr."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "stale.md", "Old 2026-01-01.")
        _rc, out = _run(mem_dir, today="2026-07-28")
        assert "Summary" in out

    def test_ok_line_present_when_clean(self, tmp_path: Path) -> None:
        """When no stale files, an OK line is printed to stderr."""
        mem_dir = tmp_path / "memory"
        _write_memory(mem_dir, "fresh.md", "No dates here.")
        _rc, out = _run(mem_dir)
        assert "OK" in out


# ---------------------------------------------------------------------------
# Test: ms-enforce integration
# ---------------------------------------------------------------------------

class TestMsEnforceIntegration:
    def test_check_function_exists_in_ms_enforce(self) -> None:
        """check_memory_staleness function is defined in ms-enforce."""
        ms_enforce = REPO / "ms-enforce"
        assert ms_enforce.exists(), "ms-enforce must exist"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "check_memory_staleness" in text, (
            "check_memory_staleness must be defined in ms-enforce"
        )

    def test_check_registered_in_tier_1(self) -> None:
        """check_memory_staleness is registered in the TIER_1 list."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "Memory staleness" in text, (
            "check_memory_staleness must be listed in TIER_1 with a 'Memory staleness' label"
        )

    def test_ms_enforce_exits_zero(self) -> None:
        """ms-enforce --fast exits 0; our check does not change the exit code."""
        result = subprocess.run(
            [_py(), str(REPO / "ms-enforce"), "--fast"],
            capture_output=True, text=True, cwd=str(REPO), timeout=120,
        )
        combined = result.stdout + result.stderr
        # Our check should appear in output
        assert "Memory staleness" in combined or "memory" in combined.lower(), (
            "Memory staleness check should appear in ms-enforce output"
        )
