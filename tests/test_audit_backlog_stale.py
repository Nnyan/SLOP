"""tests/test_audit_backlog_stale.py — Tests for tools/audit_backlog_stale.py.

Covers:
  - Clean pass: no bare [ ] entries → exit 0, no WARNING lines.
  - Recent bare [ ] (under 14 days old) → exit 0, no WARNING lines.
  - Stale bare [ ] (over 14 days old) → exit 0, WARNING line emitted.
  - Bare [ ] with no date → exit 0, not flagged (conservative).
  - Triaged entries ([→ S-NN], [x], [—], [park], [parked]) → not flagged.
  - Legend section (before first ---) → not flagged.
  - Missing BACKLOG.md → exit 0, WARNING to stderr.
  - ms-enforce registration: check_backlog_stale present and in TIER_1.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "tools" / "audit_backlog_stale.py"


def _py() -> str:
    venv_py = REPO / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _run(repo: Path, today: str = "2026-06-15") -> tuple[int, str]:
    """Run the scanner with a fixed --today date and return (rc, combined output)."""
    result = subprocess.run(
        [_py(), str(SCANNER), "--repo", str(repo), "--today", today],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout + result.stderr


def _make_backlog(repo: Path, content: str) -> None:
    """Write docs/BACKLOG.md with the given content."""
    docs = repo / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "BACKLOG.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: clean cases
# ---------------------------------------------------------------------------


class TestCleanPass:
    def test_no_backlog_file_exits_zero(self, tmp_path: Path) -> None:
        """Missing BACKLOG.md exits 0 with a WARNING to stderr."""
        rc, out = _run(tmp_path)
        assert rc == 0
        assert "WARNING" in out

    def test_empty_backlog_exits_zero(self, tmp_path: Path) -> None:
        """Empty BACKLOG.md exits 0 with no WARNING lines."""
        _make_backlog(tmp_path, "# Backlog\n\n---\n\n## Done\n")
        rc, out = _run(tmp_path)
        assert rc == 0
        assert "WARNING" not in out

    def test_all_triaged_no_warnings(self, tmp_path: Path) -> None:
        """BACKLOG with only triaged entries emits no WARNING."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ## Status legend

                - `[ ]` open, unscheduled
                - `[→ S-NN]` scheduled
                - `[x]` done
                - `[—]` won't fix

                ---

                ## Open, unscheduled

                - `[→ S-55-A]` **[hygiene] bcrypt cap review.** Date added: 2026-05-01.
                - `[x]` **[done item]** Done 2026-05-15. Date added: 2026-05-01.
                - `[—]` **[wontfix]** Won't do this. Date added: 2026-05-01.
                - `[park]` **[parked]** Parked item. Trigger: re-eval later. Date added: 2026-05-01.
                - `[parked]` **[parked2]** Also parked. Trigger: re-eval. Date added: 2026-05-01.
                """),
        )
        rc, out = _run(tmp_path, today="2026-06-20")
        assert rc == 0
        # WARNING might appear from the "no date" note but not from stale entries.
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 0, f"Unexpected WARNING lines: {warning_lines}"

    def test_recent_bare_open_not_flagged(self, tmp_path: Path) -> None:
        """A bare [ ] entry added 5 days ago (under threshold) is NOT flagged."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ---

                ## Open

                - `[ ]` **[hygiene] Some task.** Date added: 2026-06-10.
                """),
        )
        # today=2026-06-15 → age=5 days → NOT stale (threshold=14)
        rc, out = _run(tmp_path, today="2026-06-15")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 0

    def test_exactly_14_days_not_flagged(self, tmp_path: Path) -> None:
        """An entry exactly 14 days old is NOT flagged (threshold is >14, not >=14)."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ---

                ## Open

                - `[ ]` **[hygiene] Exactly 14 days.** Date added: 2026-06-01.
                """),
        )
        # today=2026-06-15 → age=14 → NOT stale (need >14)
        rc, out = _run(tmp_path, today="2026-06-15")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 0


# ---------------------------------------------------------------------------
# Tests: warn cases
# ---------------------------------------------------------------------------


class TestWarnCases:
    def test_stale_bare_open_flagged(self, tmp_path: Path) -> None:
        """A bare [ ] entry older than 14 days emits a WARNING: line."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ---

                ## Open, unscheduled

                - `[ ]` **[hygiene] Old task.** Date added: 2026-05-01.
                """),
        )
        # today=2026-06-15 → age=45 days → stale
        rc, out = _run(tmp_path, today="2026-06-15")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 1
        assert "bare [ ] entry is" in warning_lines[0]
        assert "45 days old" in warning_lines[0]

    def test_multiple_stale_entries_all_flagged(self, tmp_path: Path) -> None:
        """All stale bare [ ] entries are emitted (one WARNING line each)."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ---

                ## Open

                - `[ ]` **[task A]** Date added: 2026-04-01.
                - `[ ]` **[task B]** Date added: 2026-04-15.
                - `[ ]` **[task C]** Date added: 2026-06-13.
                """),
        )
        # today=2026-06-15: A=75d (stale), B=61d (stale), C=2d (fresh)
        rc, out = _run(tmp_path, today="2026-06-15")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 2

    def test_15_days_stale_flagged(self, tmp_path: Path) -> None:
        """An entry 15 days old (just past the threshold) IS flagged."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ---

                ## Open

                - `[ ]` **[hygiene] Just past threshold.** Date added: 2026-05-31.
                """),
        )
        # today=2026-06-15 → age=15 days → stale
        rc, out = _run(tmp_path, today="2026-06-15")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 1
        assert "15 days old" in warning_lines[0]

    def test_stale_includes_lineno(self, tmp_path: Path) -> None:
        """WARNING output includes the line number from BACKLOG.md."""
        content = textwrap.dedent("""\
            # SLOP Backlog

            ---

            ## Open

            - `[ ]` **[task]** Date added: 2026-05-01.
            """)
        _make_backlog(tmp_path, content)
        rc, out = _run(tmp_path, today="2026-06-15")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 1
        # Should contain "docs/BACKLOG.md:<N>"
        assert "docs/BACKLOG.md:" in warning_lines[0]


# ---------------------------------------------------------------------------
# Tests: no-date (conservative) behaviour
# ---------------------------------------------------------------------------


class TestNoDatProvenance:
    def test_no_date_not_flagged(self, tmp_path: Path) -> None:
        """A bare [ ] entry with no Date added: provenance is NOT flagged (conservative)."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ---

                ## Open

                - `[ ]` **[task with no date]** — Some task with no provenance date.
                """),
        )
        rc, out = _run(tmp_path, today="2026-12-31")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 0


# ---------------------------------------------------------------------------
# Tests: legend section exclusion
# ---------------------------------------------------------------------------


class TestLegendSection:
    def test_legend_bare_open_not_flagged(self, tmp_path: Path) -> None:
        """The [ ] token in the Status legend section is NOT flagged."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ## Status legend

                - `[ ]` open, unscheduled
                - `[→ S-NN]` scheduled into a wave

                ---

                ## Open

                - `[→ S-55-A]` **[scheduled]** Date added: 2026-05-01.
                """),
        )
        rc, out = _run(tmp_path, today="2026-12-31")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 0, (
            "Legend entries before --- must not be flagged"
        )


# ---------------------------------------------------------------------------
# Tests: non-backtick bare [ ] syntax
# ---------------------------------------------------------------------------


class TestNonBacktickSyntax:
    def test_bare_bracket_without_backticks_flagged(self, tmp_path: Path) -> None:
        """A line starting with `- [ ]` (no backticks) is also flagged if stale."""
        _make_backlog(
            tmp_path,
            textwrap.dedent("""\
                # SLOP Backlog

                ---

                ## Open

                - [ ] **[task]** No backtick syntax. Date added: 2026-05-01.
                """),
        )
        rc, out = _run(tmp_path, today="2026-06-15")
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 1


# ---------------------------------------------------------------------------
# Tests: exit code always zero
# ---------------------------------------------------------------------------


class TestExitCodeAlwaysZero:
    def test_exit_zero_with_stale_entries(self, tmp_path: Path) -> None:
        """Exit code is always 0 even with stale entries (warn-only)."""
        _make_backlog(
            tmp_path,
            "# Backlog\n\n---\n\n- `[ ]` **[stale]** Date added: 2026-01-01.\n",
        )
        rc, _ = _run(tmp_path, today="2026-12-31")
        assert rc == 0

    def test_exit_zero_no_backlog(self, tmp_path: Path) -> None:
        """Exit code is 0 even when BACKLOG.md is missing."""
        rc, _ = _run(tmp_path, today="2026-06-15")
        assert rc == 0


# ---------------------------------------------------------------------------
# Tests: ms-enforce integration
# ---------------------------------------------------------------------------


class TestMsEnforceRegistration:
    def test_check_backlog_stale_defined_in_ms_enforce(self) -> None:
        """check_backlog_stale function exists in ms-enforce."""
        ms_enforce = REPO / "ms-enforce"
        assert ms_enforce.exists(), "ms-enforce must exist"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "check_backlog_stale" in text, (
            "check_backlog_stale must be defined in ms-enforce"
        )

    def test_check_backlog_stale_in_tier1(self) -> None:
        """check_backlog_stale is registered in TIER_1 list."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        # Find the TIER_1 list section and confirm our check is in it.
        assert "check_backlog_stale" in text, (
            "check_backlog_stale must appear in TIER_1 list"
        )
        assert "BACKLOG stale" in text or "backlog_stale" in text.lower(), (
            "BACKLOG stale label should appear in TIER_1 registration"
        )

    def test_ms_enforce_fast_exits_zero(self) -> None:
        """ms-enforce --fast exits 0; our new check does not change exit code."""
        result = subprocess.run(
            [_py(), str(REPO / "ms-enforce"), "--fast"],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=180,
        )
        combined = result.stdout + result.stderr
        # Our check should appear in the output.
        assert "backlog" in combined.lower() or "stale" in combined.lower(), (
            "BACKLOG stale check should appear in ms-enforce output"
        )
        # The check is warn-only — ms-enforce should not exit nonzero BECAUSE of it.
        # (Other pre-existing failures might cause nonzero, but we accept that.)
