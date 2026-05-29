"""
tests/test_robot_retro.py — Tests for tools/robot-retro.py

Uses fixture run directories created under tmp_path (no real archive needed).
"""
import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

# Import tools/robot-retro.py — hyphen in filename requires importlib (not importable as a module name)
_TOOL_PATH = Path(__file__).parent.parent / "tools" / "robot-retro.py"
_spec = importlib.util.spec_from_file_location("robot_retro", _TOOL_PATH)
robot_retro = importlib.util.module_from_spec(_spec)
sys.modules["robot_retro"] = robot_retro
_spec.loader.exec_module(robot_retro)


# ── fixtures ─────────────────────────────────────────────────────────────────

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


@pytest.fixture()
def full_run_dir(tmp_path: Path) -> Path:
    """A fixture run dir with all subdirs populated."""
    run = tmp_path / "2026-05-28-test-run"

    # status/
    _write(run / "status" / "S-99.md", """\
        # S-99-WIDGET status — COMPLETE
        **Started:** 2026-05-28T10:00Z
        **Wave branch:** wave/S-99-widget

        ## Streams
        - A (widgets) — MERGED abc1234
        - B (gadgets) — MERGED def5678

        ## Final state
        COMPLETE.
    """)
    _write(run / "status" / "S-100.md", """\
        # S-100-BLOCKED status
        **Started:** 2026-05-28T11:00Z

        ## Streams
        - A (foo) — BLOCKED
    """)

    # decisions/ — one informational, one needs-judgment
    _write(run / "decisions" / "S-99-A-1.md", """\
        ---
        wave: S-99-WIDGET
        stream: A
        sequence: 1
        type: informational
        default-applied: PREFER_STDLIB_OVER_THIRD_PARTY
        timestamp: 2026-05-28T10:05:00Z
        ---

        ## Question / scenario
        Should I use stdlib or a third-party lib?

        ## Best guess applied
        Used stdlib as per default.

        ## Morning review action
        confirm and merge
    """)
    _write(run / "decisions" / "S-99-B-1.md", """\
        ---
        wave: S-99-WIDGET
        stream: B
        sequence: 1
        type: decision
        default-applied: none (not covered by AUTONOMOUS-DEFAULTS — candidate new entry)
        timestamp: 2026-05-28T10:10:00Z
        ---

        ## Question / scenario
        Novel situation never seen before.

        ## Best guess applied
        Applied judgment call.

        ## Morning review action
        requires human judgment — do not merge wave branch until decided
    """)

    # blockers/
    _write(run / "blockers" / "S-100-A.md", """\
        ---
        wave: S-100-BLOCKED
        stream: A
        type: blocker
        timestamp: 2026-05-28T11:30:00Z
        ---

        ## What blocked
        Import failed because of missing module.

        ## What I tried
        - pip install the module
        - alternative approach

        ## Why I stopped
        Robot rule 9 — one try on test failures.

        ## Morning action needed
        Add missing dependency to requirements.txt.
    """)

    # observations/
    _write(run / "observations" / "S-99-1.md", """\
        ---
        wave: S-99-WIDGET
        stream: A
        sequence: 1
        type: observation
        timestamp: 2026-05-28T10:15:00Z
        ---

        ## Finding
        Pre-existing TIER_2 failures found in test_legacy.py — 3 failures.

        ## Action
        Out of scope. Not fixed per Robot rule 10.
    """)
    _write(run / "observations" / "S-99-2.md", """\
        ---
        wave: S-99-WIDGET
        stream: B
        sequence: 1
        type: observation
        timestamp: 2026-05-28T10:20:00Z
        ---

        ## Finding
        pip-audit not installed in venv.
    """)

    # proposed-deletions/
    _write(run / "proposed-deletions" / "S-99-A-cleanup.txt", """\
        # Proposed deletions — approved at morning review
        # WARNING: review carefully before running
        git rm --cached backend/static/old-build.js
        git rm --cached data/legacy/stale.conf
    """)

    return run


@pytest.fixture()
def minimal_run_dir(tmp_path: Path) -> Path:
    """A fixture run dir with ONLY a status dir (no blockers/decisions/etc)."""
    run = tmp_path / "2026-06-01-minimal"
    _write(run / "status" / "S-101.md", """\
        # S-101-SIMPLE status — COMPLETE
        COMPLETE.
    """)
    return run


@pytest.fixture()
def empty_run_dir(tmp_path: Path) -> Path:
    """A fixture run dir with no subdirs at all."""
    run = tmp_path / "2026-06-02-empty"
    run.mkdir(parents=True)
    return run


# ── tests ─────────────────────────────────────────────────────────────────────

class TestScanStatus:
    def test_reads_complete_state(self, full_run_dir):
        result = robot_retro.scan_status(full_run_dir / "status")
        assert result["count"] == 2
        names = [e["file"] for e in result["files"]]
        assert "S-99.md" in names
        assert "S-100.md" in names

    def test_detects_complete(self, full_run_dir):
        result = robot_retro.scan_status(full_run_dir / "status")
        s99 = next(e for e in result["files"] if e["file"] == "S-99.md")
        assert s99["state"] == "complete"

    def test_detects_blocked(self, full_run_dir):
        result = robot_retro.scan_status(full_run_dir / "status")
        s100 = next(e for e in result["files"] if e["file"] == "S-100.md")
        assert s100["state"] == "blocked"

    def test_missing_dir_returns_empty(self, tmp_path):
        result = robot_retro.scan_status(tmp_path / "nonexistent")
        assert result["count"] == 0
        assert result["files"] == []


class TestScanDecisions:
    def test_count_total(self, full_run_dir):
        result = robot_retro.scan_decisions(full_run_dir / "decisions")
        assert result["count"] == 2

    def test_classifies_informational(self, full_run_dir):
        result = robot_retro.scan_decisions(full_run_dir / "decisions")
        info = result["informational"]
        assert len(info) == 1
        assert info[0]["file"] == "S-99-A-1.md"
        assert info[0]["default_applied"] == "PREFER_STDLIB_OVER_THIRD_PARTY"

    def test_classifies_needs_judgment(self, full_run_dir):
        result = robot_retro.scan_decisions(full_run_dir / "decisions")
        nj = result["needs_judgment"]
        assert len(nj) == 1
        assert nj[0]["file"] == "S-99-B-1.md"
        assert nj[0]["wave"] == "S-99-WIDGET"
        assert nj[0]["stream"] == "B"

    def test_missing_dir_returns_empty(self, tmp_path):
        result = robot_retro.scan_decisions(tmp_path / "nonexistent")
        assert result["count"] == 0
        assert result["informational"] == []
        assert result["needs_judgment"] == []


class TestScanBlockers:
    def test_reads_blocker(self, full_run_dir):
        result = robot_retro.scan_blockers(full_run_dir / "blockers")
        assert result["count"] == 1
        b = result["files"][0]
        assert b["file"] == "S-100-A.md"
        assert b["wave"] == "S-100-BLOCKED"
        assert b["stream"] == "A"

    def test_missing_dir_returns_empty(self, tmp_path):
        result = robot_retro.scan_blockers(tmp_path / "nonexistent")
        assert result["count"] == 0
        assert result["files"] == []


class TestScanObservations:
    def test_reads_two_observations(self, full_run_dir):
        result = robot_retro.scan_observations(full_run_dir / "observations")
        assert result["count"] == 2

    def test_observation_fields(self, full_run_dir):
        result = robot_retro.scan_observations(full_run_dir / "observations")
        obs = next(e for e in result["files"] if e["file"] == "S-99-1.md")
        assert obs["wave"] == "S-99-WIDGET"
        assert obs["stream"] == "A"
        assert "TIER_2" in obs["summary"] or "Pre-existing" in obs["summary"]

    def test_missing_dir_returns_empty(self, tmp_path):
        result = robot_retro.scan_observations(tmp_path / "nonexistent")
        assert result["count"] == 0


class TestScanProposedDeletions:
    def test_reads_file(self, full_run_dir):
        result = robot_retro.scan_proposed_deletions(
            full_run_dir / "proposed-deletions"
        )
        assert result["count"] == 1
        pd = result["files"][0]
        assert pd["file"] == "S-99-A-cleanup.txt"
        # Should extract non-comment lines
        assert any("git rm" in p for p in pd["candidate_paths"])

    def test_missing_dir_returns_empty(self, tmp_path):
        result = robot_retro.scan_proposed_deletions(tmp_path / "nonexistent")
        assert result["count"] == 0


class TestRenderReport:
    def test_report_not_empty(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert len(report) > 200

    def test_report_has_summary_section(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "## Summary" in report

    def test_report_has_status_section(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "## Per-Stream Status" in report

    def test_report_has_decisions_section(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "## Decisions" in report

    def test_report_has_blockers_section(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "## Blockers" in report

    def test_report_has_observations_section(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "## Observations" in report

    def test_report_has_proposed_deletions_section(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "## Proposed Deletions" in report

    def test_report_has_defaults_candidates_section(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "## Candidate AUTONOMOUS-DEFAULTS Updates" in report

    def test_report_counts_match(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        # status: 2, decisions-informational: 1, decisions-needs-judgment: 1
        # blockers: 1, observations: 2, proposed-deletions: 1
        assert "| Status files | 2 |" in report
        assert "| Decisions — informational | 1 |" in report
        assert "| Decisions — needs-judgment | 1 |" in report
        assert "| Blockers | 1 |" in report
        assert "| Observations | 2 |" in report
        assert "| Proposed deletions | 1 |" in report

    def test_report_includes_run_dir_name(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "2026-05-28-test-run" in report

    def test_report_flags_blocker(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "S-100-A.md" in report
        # Should show the warning about blockers
        assert "blocker" in report.lower()

    def test_minimal_run_missing_subdirs(self, minimal_run_dir):
        """A run with only status/ dir should not crash and should produce a report."""
        report = robot_retro.build_report(str(minimal_run_dir))
        assert "## Summary" in report
        assert "No blockers" in report
        assert "No observations" in report
        assert "No proposed deletions" in report

    def test_empty_run_dir(self, empty_run_dir):
        """An entirely empty run dir should produce a valid (all-zero) report."""
        report = robot_retro.build_report(str(empty_run_dir))
        assert "## Summary" in report
        assert "| Status files | 0 |" in report
        assert "| Blockers | 0 |" in report

    def test_needs_judgment_warning_in_decisions(self, full_run_dir):
        """Needs-judgment decisions should appear under the correct subsection."""
        report = robot_retro.build_report(str(full_run_dir))
        assert "Needs-Judgment" in report
        assert "S-99-B-1.md" in report

    def test_informational_decision_in_report(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "S-99-A-1.md" in report
        assert "PREFER_STDLIB_OVER_THIRD_PARTY" in report

    def test_proposed_deletion_paths_shown(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "git rm" in report

    def test_footer_has_commit_style(self, full_run_dir):
        report = robot_retro.build_report(str(full_run_dir))
        assert "robot: lessons from" in report

    def test_invalid_dir_raises_systemexit(self, tmp_path):
        with pytest.raises(SystemExit):
            robot_retro.build_report(str(tmp_path / "does-not-exist"))


class TestHelpers:
    def test_frontmatter_field_extracts_wave(self):
        text = "---\nwave: S-99-TEST\nstream: A\n---\n## Body"
        assert robot_retro._frontmatter_field(text, "wave") == "S-99-TEST"

    def test_frontmatter_field_missing_returns_empty(self):
        text = "No frontmatter here"
        assert robot_retro._frontmatter_field(text, "wave") == ""

    def test_extract_first_heading(self):
        text = "---\nfoo: bar\n---\n\n# My Heading\n\nBody text"
        assert robot_retro._extract_first_heading(text) == "My Heading"

    def test_extract_first_heading_missing(self):
        text = "No headings here"
        assert robot_retro._extract_first_heading(text) == ""

    def test_short_summary_skips_frontmatter(self):
        text = "---\nwave: X\n---\n\n## Section\n\nActual content here."
        result = robot_retro._short_summary(text)
        assert "Actual content" in result

    def test_classify_decision_informational(self):
        text = "## Morning review action\nconfirm and merge"
        assert robot_retro._classify_decision(text) == "informational"

    def test_classify_decision_needs_judgment(self):
        text = "## Morning review action\nrequires human judgment — do not merge"
        assert robot_retro._classify_decision(text) == "needs-judgment"

    def test_classify_decision_deviated(self):
        text = "DEVIATED from the strict abort default."
        assert robot_retro._classify_decision(text) == "needs-judgment"
