"""tests/test_audit_status_file_freshness.py — Tests for audit_status_file_freshness.py.

Covers:
  - clean pass: no run dir present
  - clean pass: run dir exists, status file updated after merges
  - clean pass: run dir exists, no merged streams
  - warn: status file started == last_updated with merged streams
  - warn: active run, status file exceeds max-stale-min threshold
  - clean: archived run, ignores wall-clock staleness
  - date-only timestamp handling (FP4 guard)
  - scanner exits 0 always
"""
from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

import pytest

# Allow importing the tool module directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import audit_status_file_freshness as freshness


# ---- Helpers ---------------------------------------------------------------

def _make_status_file(
    tmp_path: Path,
    name: str,
    started: str,
    last_updated: str,
    stream_lines: list,
    extra: str = "",
) -> Path:
    """Write a minimal status file to tmp_path/status/<name>.md."""
    status_dir = tmp_path / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    sf = status_dir / name
    lines = [
        f"# {name} status\n",
        f"**Started:** {started}  **Last updated:** {last_updated}\n",
        "\n",
        "## Streams\n",
    ]
    for sl in stream_lines:
        lines.append(f"{sl}\n")
    if extra:
        lines.append(extra)
    sf.write_text("".join(lines), encoding="utf-8")
    return sf


# ---- Timestamp parsing tests -----------------------------------------------

class TestParseTimestamp:
    def test_iso_full_with_z(self):
        dt, date_only = freshness._parse_timestamp("2026-05-29T05:41:11Z")
        assert dt == datetime.datetime(2026, 5, 29, 5, 41, 11)
        assert not date_only

    def test_iso_full_without_z(self):
        dt, date_only = freshness._parse_timestamp("2026-05-29T05:41:11")
        assert dt == datetime.datetime(2026, 5, 29, 5, 41, 11)
        assert not date_only

    def test_date_only(self):
        dt, date_only = freshness._parse_timestamp("2026-05-29")
        assert dt == datetime.datetime(2026, 5, 29, 0, 0, 0)
        assert date_only

    def test_unparseable_returns_none(self):
        dt, _ = freshness._parse_timestamp("robot start")
        assert dt is None

    def test_unparseable_partial(self):
        dt, _ = freshness._parse_timestamp("2026-05-29T")
        assert dt is None


# ---- Merged stream counting ------------------------------------------------

class TestCountMergedStreams:
    def test_no_merges(self):
        content = "- A (setup) -- DISPATCHED\n- B (run) -- COMPLETE\n"
        assert freshness._count_merged_streams(content) == 0

    def test_em_dash_merged(self):
        # U+2014 EM DASH as used in real status files
        content = "- A (verify.py)            — MERGED (04796ce; 9 tests)\n"
        assert freshness._count_merged_streams(content) == 1

    def test_arrow_merged(self):
        content = "- A (scrub.py)   — DISPATCHED → MERGED (0efd4d1; 55 tests)\n"
        # arrow pattern fires; em-dash fires too but same line
        assert freshness._count_merged_streams(content) == 1

    def test_multiple_merged(self):
        content = (
            "- A (verify.py)  — MERGED (04796ce)\n"
            "- B (backoff.py) — MERGED (9d84d75)\n"
            "- C (apply.py)   — MERGED (b438b1d)\n"
        )
        assert freshness._count_merged_streams(content) == 3

    def test_double_dash_merged(self):
        content = "- A (step) -- MERGED (abc1234)\n"
        assert freshness._count_merged_streams(content) == 1


# ---- audit_run_dir: clean passes -------------------------------------------

class TestAuditRunDirClean:
    def test_no_status_files(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "status").mkdir()
        result = freshness.audit_run_dir(run_dir, max_stale_min=60, is_active=True)
        assert result == []

    def test_status_file_updated_after_merges(self, tmp_path):
        """Last updated > Started: no stale-update warning (is_active=False to isolate check)."""
        _make_status_file(
            tmp_path,
            "S-60.md",
            started="2026-05-29T05:00:00Z",
            last_updated="2026-05-29T05:41:11Z",
            stream_lines=[
                "- A (verify.py)  — MERGED (04796ce; 9 tests)",
                "- B (backoff.py) — MERGED (9d84d75; 7 tests)",
            ],
        )
        # is_active=False: skip wall-clock check (archived run), only check started==updated
        result = freshness.audit_run_dir(tmp_path, max_stale_min=60, is_active=False)
        assert result == []

    def test_no_merged_streams_started_eq_updated(self, tmp_path):
        """Started == Last updated but no merges: no warning (run in progress)."""
        _make_status_file(
            tmp_path,
            "S-69.md",
            started="2026-05-29T17:01:52Z",
            last_updated="2026-05-29T17:01:52Z",
            stream_lines=["(pending dispatch)"],
        )
        result = freshness.audit_run_dir(tmp_path, max_stale_min=60, is_active=True)
        assert result == []

    def test_date_only_timestamps_no_wallclock_check(self, tmp_path):
        """Date-only timestamps skip the wall-clock check (FP4 guard)."""
        _make_status_file(
            tmp_path,
            "S-47.md",
            started="2026-05-27",
            last_updated="2026-05-27",
            stream_lines=[
                "- A (step) — MERGED (abc1234)",
            ],
        )
        # is_active=True but date-only -- no wall-clock warning
        result = freshness.audit_run_dir(tmp_path, max_stale_min=1, is_active=True)
        # The started==updated with merged check fires for date-only timestamps
        # only when BOTH are date-only (we skip that check per FP4)
        assert result == []

    def test_archived_run_no_wallclock_check(self, tmp_path):
        """Archive run (is_active=False) skips wall-clock check even for old timestamps."""
        _make_status_file(
            tmp_path,
            "S-50.md",
            started="2020-01-01T00:00:00Z",
            last_updated="2020-01-01T06:02:00Z",
            stream_lines=[
                "- A (step) — MERGED (aaa1111)",
                "- B (step) — MERGED (bbb2222)",
            ],
        )
        # is_active=False -- no wall-clock check, last_updated > started so no stale warning
        result = freshness.audit_run_dir(tmp_path, max_stale_min=60, is_active=False)
        assert result == []

    def test_no_last_updated_field(self, tmp_path):
        """Status file without 'Last updated' field: skipped gracefully."""
        status_dir = tmp_path / "status"
        status_dir.mkdir(parents=True, exist_ok=True)
        (status_dir / "S-old.md").write_text(
            "# S-old status\n**Started:** 2026-05-28 (robot start)  **Completed:** 2026-05-28\n"
            "- A (step) — MERGED (abc1234)\n",
            encoding="utf-8",
        )
        result = freshness.audit_run_dir(tmp_path, max_stale_min=60, is_active=False)
        assert result == []


# ---- audit_run_dir: warn cases ---------------------------------------------

class TestAuditRunDirWarn:
    def test_started_eq_updated_with_merged_streams(self, tmp_path):
        """Started == Last updated AND merged streams present: warning.

        Uses is_active=False to isolate the started==updated check from the
        wall-clock check (otherwise both would fire for a historical timestamp).
        """
        _make_status_file(
            tmp_path,
            "S-99.md",
            started="2026-05-29T10:00:00Z",
            last_updated="2026-05-29T10:00:00Z",
            stream_lines=[
                "- A (verify.py)  — MERGED (04796ce; 9 tests)",
                "- B (backoff.py) — MERGED (9d84d75; 7 tests)",
                "- C (apply.py)   — MERGED (b438b1d; 4 tests)",
            ],
        )
        # is_active=False: only the started==updated check fires, not wall-clock
        result = freshness.audit_run_dir(tmp_path, max_stale_min=60, is_active=False)
        assert len(result) == 1
        assert "WARNING" in result[0]
        assert "S-99.md" in result[0]
        assert "3 merged stream(s)" in result[0]
        assert "Started" in result[0]

    def test_active_run_stale_wallclock(self, tmp_path):
        """Active run where last_updated is older than max_stale_min: warning."""
        # Use a timestamp guaranteed to be in the past by >5 minutes
        _now_utc = datetime.datetime.now(datetime.timezone.utc)
        _now_naive = datetime.datetime(
            _now_utc.year, _now_utc.month, _now_utc.day,
            _now_utc.hour, _now_utc.minute, _now_utc.second,
        )
        stale_time = _now_naive - datetime.timedelta(minutes=10)
        ts_str = stale_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        _make_status_file(
            tmp_path,
            "S-active.md",
            started=ts_str,
            last_updated=ts_str,
            stream_lines=["(streams dispatched, waiting)"],
        )
        result = freshness.audit_run_dir(tmp_path, max_stale_min=5, is_active=True)
        assert len(result) == 1
        assert "WARNING" in result[0]
        assert "S-active.md" in result[0]
        assert "min ago" in result[0]

    def test_single_merged_stream_started_eq_updated(self, tmp_path):
        """Single merged stream but Started == Last updated: warning (FP1 known case)."""
        _make_status_file(
            tmp_path,
            "S-single.md",
            started="2026-05-29T09:00:00Z",
            last_updated="2026-05-29T09:00:00Z",
            stream_lines=[
                "- A (step) — MERGED (abc1234)",
            ],
        )
        result = freshness.audit_run_dir(tmp_path, max_stale_min=60, is_active=False)
        assert len(result) == 1
        assert "WARNING" in result[0]
        assert "1 merged stream(s)" in result[0]

    def test_multiple_status_files_mixed(self, tmp_path):
        """One stale file and one fresh file: only one warning."""
        # Fresh file: Last updated > Started
        _make_status_file(
            tmp_path,
            "S-fresh.md",
            started="2026-05-29T08:00:00Z",
            last_updated="2026-05-29T09:00:00Z",
            stream_lines=[
                "- A (step) — MERGED (aaa1111)",
            ],
        )
        # Stale file: Last updated == Started with merges
        _make_status_file(
            tmp_path,
            "S-stale.md",
            started="2026-05-29T08:00:00Z",
            last_updated="2026-05-29T08:00:00Z",
            stream_lines=[
                "- A (step) — MERGED (bbb2222)",
                "- B (step) — MERGED (ccc3333)",
            ],
        )
        result = freshness.audit_run_dir(tmp_path, max_stale_min=60, is_active=False)
        assert len(result) == 1
        assert "S-stale.md" in result[0]


# ---- Integration: scanner script invocation --------------------------------

class TestScannerScript:
    """Run the scanner as a subprocess to verify CLI behavior."""

    def _script_path(self):
        return str(
            Path(__file__).resolve().parent.parent / "tools" / "audit_status_file_freshness.py"
        )

    def test_no_run_dir_exits_zero(self, tmp_path):
        """No run dir -> exit 0, no output on stdout."""
        result = subprocess.run(
            [sys.executable, self._script_path(), "--repo", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""
        assert "clean pass" in result.stderr or "checked" in result.stderr

    def test_explicit_none_exits_zero(self, tmp_path):
        """--run-dir none -> exit 0."""
        result = subprocess.run(
            [sys.executable, self._script_path(),
             "--repo", str(tmp_path), "--run-dir", "none"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_clean_run_exits_zero(self, tmp_path):
        """Run dir with fresh status files -> exit 0, no WARNING on stdout."""
        run_dir = tmp_path / "run"
        _make_status_file(
            run_dir,
            "S-60.md",
            started="2026-05-29T05:00:00Z",
            last_updated="2026-05-29T05:41:11Z",
            stream_lines=[
                "- A (verify.py)  — MERGED (04796ce; 9 tests)",
            ],
        )
        result = subprocess.run(
            [sys.executable, self._script_path(),
             "--repo", str(tmp_path), "--run-dir", str(run_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        warnings = [ln for ln in result.stdout.splitlines() if ln.startswith("WARNING")]
        assert warnings == []

    def test_stale_run_exits_zero_with_warnings(self, tmp_path):
        """Stale status file -> exit 0 (warn-only) but WARNING printed to stdout."""
        run_dir = tmp_path / "run"
        _make_status_file(
            run_dir,
            "S-stale.md",
            started="2026-05-29T10:00:00Z",
            last_updated="2026-05-29T10:00:00Z",
            stream_lines=[
                "- A (step) — MERGED (abc1234)",
                "- B (step) — MERGED (def5678)",
            ],
        )
        result = subprocess.run(
            [sys.executable, self._script_path(),
             "--repo", str(tmp_path), "--run-dir", str(run_dir)],
            capture_output=True,
            text=True,
        )
        # Always exits 0
        assert result.returncode == 0
        warnings = [ln for ln in result.stdout.splitlines() if ln.startswith("WARNING")]
        assert len(warnings) == 1
        assert "S-stale.md" in warnings[0]

    def test_max_stale_min_parameter(self, tmp_path):
        """--max-stale-min controls the wall-clock threshold.

        Uses audit_run_dir() directly (with is_active=True) to test the
        threshold logic without relying on path-based active-run detection.
        """
        import datetime as _dt

        # Timestamp 3 minutes ago
        now_utc = _dt.datetime.now(_dt.timezone.utc)
        stale_ts = _dt.datetime(
            now_utc.year, now_utc.month, now_utc.day,
            now_utc.hour, now_utc.minute, now_utc.second,
        ) - _dt.timedelta(minutes=3)
        ts_str = stale_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        run_dir = tmp_path / "run"
        _make_status_file(
            run_dir,
            "S-timing.md",
            started=ts_str,
            last_updated=ts_str,
            stream_lines=["(dispatching)"],
        )

        # With 60 min threshold: no warning (3 min < 60 min)
        result_no_warn = freshness.audit_run_dir(run_dir, max_stale_min=60, is_active=True)
        wall_clock_warns = [w for w in result_no_warn if "min ago" in w]
        assert wall_clock_warns == []

        # With 1 min threshold: warning (3 min > 1 min)
        result_warn = freshness.audit_run_dir(run_dir, max_stale_min=1, is_active=True)
        wall_clock_warns = [w for w in result_warn if "min ago" in w]
        assert len(wall_clock_warns) == 1
        assert "WARNING" in wall_clock_warns[0]
        assert "S-timing.md" in wall_clock_warns[0]
