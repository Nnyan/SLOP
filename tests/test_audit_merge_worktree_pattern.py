"""tests/test_audit_merge_worktree_pattern.py — Tests for audit_merge_worktree_pattern.py.

Verifies tools/audit_merge_worktree_pattern.py using fixture run-archive trees:
  - Compliant run: merges performed in dedicated .claude/worktrees/merge-* → no WARNING.
  - Violation run: merge clearly done in shared working tree → WARNING [violation].
  - Mixed batch: compliance fix present alongside the collision description → no WARNING.
  - Low-confidence: merge outcome described with no worktree procedure detail → WARNING [low-confidence].
  - Empty archive: no run-archive directory → exits 0, no WARNING.
  - ms-enforce registration: check_merge_worktree_pattern present + registered in TIER_1.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO / "tools" / "audit_merge_worktree_pattern.py"


def _py() -> str:
    """Return path to Python interpreter, preferring the project venv."""
    venv_py = REPO / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _run_script(repo: Path) -> tuple[int, str]:
    """Run the scanner against a fixture repo and return (returncode, combined output)."""
    result = subprocess.run(
        [_py(), str(AUDIT_SCRIPT), "--repo", str(repo)],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout + result.stderr


def _make_run_archive(repo: Path, batch: str = "2026-05-28") -> tuple[Path, Path]:
    """Create a minimal run-archive structure; return (status_dir, decisions_dir)."""
    status_dir   = repo / ".claude" / "run-archive" / batch / "status"
    decisions_dir = repo / ".claude" / "run-archive" / batch / "decisions"
    status_dir.mkdir(parents=True)
    decisions_dir.mkdir(parents=True)
    return status_dir, decisions_dir


# ---------------------------------------------------------------------------
# Exit code is always 0
# ---------------------------------------------------------------------------

class TestExitCodeAlwaysZero:
    def test_no_archive_exits_zero(self, tmp_path: Path) -> None:
        """Missing run-archive directory exits 0."""
        rc, _ = _run_script(tmp_path)
        assert rc == 0

    def test_violation_present_still_exits_zero(self, tmp_path: Path) -> None:
        """Even with violation evidence, exit code must be 0 (warn-only)."""
        status_dir, _ = _make_run_archive(tmp_path)
        (status_dir / "S-99.md").write_text(textwrap.dedent("""\
            # S-99 status
            Root cause: the shared main worktree was checked out on wave/S-99
            when the operator committed. This caused a cross-session HEAD collision.
            """))
        rc, _ = _run_script(tmp_path)
        assert rc == 0

    def test_low_confidence_still_exits_zero(self, tmp_path: Path) -> None:
        """Low-confidence warnings also exit 0."""
        status_dir, _ = _make_run_archive(tmp_path)
        (status_dir / "S-55.md").write_text(textwrap.dedent("""\
            # S-55 status
            ## Streams (3, all parallel) — ALL MERGED
            - A — MERGED (commit abc1234) — 22 tests
            - B — MERGED (commit def5678) — 24 tests
            """))
        rc, _ = _run_script(tmp_path)
        assert rc == 0


# ---------------------------------------------------------------------------
# Compliant run: dedicated merge worktrees — no WARNING
# ---------------------------------------------------------------------------

class TestCompliantRun:
    def test_status_with_merge_worktree_reference_not_warned(self, tmp_path: Path) -> None:
        """A status file that mentions worktrees/merge-* is compliant → no WARNING."""
        status_dir, _ = _make_run_archive(tmp_path)
        (status_dir / "S-60.md").write_text(textwrap.dedent("""\
            # S-60 status
            Streams (2, all parallel) — ALL MERGED
            - A — MERGED (commit abc1234) — 15 tests
            - B — MERGED (commit def5678) — 12 tests
            All merges performed in .claude/worktrees/merge-S-60 with detached HEAD.
            """))
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out, f"Compliant run should produce no WARNING, got: {out}"

    def test_decision_with_dedicated_worktree_description_not_warned(self, tmp_path: Path) -> None:
        """Decision file describing merge in a dedicated worktree is compliant."""
        _, decisions_dir = _make_run_archive(tmp_path)
        (decisions_dir / "S-60-MERGE-1.md").write_text(textwrap.dedent("""\
            ---
            wave: S-60
            type: decision
            ---
            ## Merge procedure
            Merging Stream A on top of Stream B in dedicated worktree.
            Used git worktree add .claude/worktrees/merge-S-60 to isolate the merge.
            No collision risk as main worktree is on detached HEAD.
            Merge commit abc1234.
            """))
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out

    def test_no_archive_exits_clean(self, tmp_path: Path) -> None:
        """No run-archive directory → clean output, no WARNING."""
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out


# ---------------------------------------------------------------------------
# Violation run: merge in shared main worktree
# ---------------------------------------------------------------------------

class TestViolationRun:
    def test_explicit_collision_without_fix_flagged(self, tmp_path: Path) -> None:
        """A decision file describing a HEAD collision without the fix is flagged as violation."""
        _, decisions_dir = _make_run_archive(tmp_path)
        (decisions_dir / "S-99-collision.md").write_text(textwrap.dedent("""\
            ---
            wave: S-99
            type: decision
            ---
            ## Collision
            Root cause: the shared main worktree was checked out on wave/S-99
            when the operator made a commit. The commit attached to wave/S-99.
            """))
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" in out
        assert "[violation]" in out
        assert "S-99-collision.md" in out

    def test_cross_session_head_collision_flagged(self, tmp_path: Path) -> None:
        """A file describing a cross-session HEAD collision without fix is flagged."""
        _, decisions_dir = _make_run_archive(tmp_path)
        (decisions_dir / "BATCH-99-collision.md").write_text(textwrap.dedent("""\
            # Batch collision
            This run experienced a cross-session HEAD collision.
            The orchestrator checked out a wave branch and the operator committed.
            """))
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" in out
        assert "[violation]" in out

    def test_violation_severity_label_present(self, tmp_path: Path) -> None:
        """Violation output must use [violation] label, not just WARNING."""
        _, decisions_dir = _make_run_archive(tmp_path)
        (decisions_dir / "bad-merge.md").write_text(
            "The main worktree was checked out on wave/S-88 during the merge commit.\n"
            "This caused a cross-session HEAD collision.\n"
        )
        _, out = _run_script(tmp_path)
        assert "[violation]" in out


# ---------------------------------------------------------------------------
# Compliant: collision documented WITH fix (batch-5 pattern)
# ---------------------------------------------------------------------------

class TestCollisionWithFixIsCompliant:
    def test_batch5_pattern_file_not_warned(self, tmp_path: Path) -> None:
        """A file documenting the collision AND the dedicated-worktree fix is compliant."""
        _, decisions_dir = _make_run_archive(tmp_path, batch="2026-05-29-batch5")
        (decisions_dir / "S-63-operator-commit-collision.md").write_text(textwrap.dedent("""\
            ---
            wave: S-63
            type: decision
            ---
            ## Root cause
            The shared main worktree was checked out on wave/S-63 when the operator
            committed. This caused a cross-session HEAD collision.

            ## Fix applied
            Did all subsequent wave merges in dedicated worktrees (.claude/worktrees/merge-*)
            to avoid recurrence. Detached main worktree to HEAD SHA so no branch was active.
            """))
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "[violation]" not in out, (
            "File documenting both collision AND fix should not be flagged as violation"
        )

    def test_batch_complete_with_fix_description_not_warned(self, tmp_path: Path) -> None:
        """BATCH-COMPLETE file describing the fix is compliant."""
        status_dir, _ = _make_run_archive(tmp_path, batch="2026-05-29-batch5")
        (status_dir / "BATCH-5-COMPLETE.md").write_text(textwrap.dedent("""\
            # BATCH-5 COMPLETE
            TWO cross-session collisions this run, both from sharing the main worktree HEAD.
            Fix: Did all subsequent wave merges in dedicated worktrees (.claude/worktrees/merge-*)
            and kept the main worktree on a detached HEAD. Candidate AUTONOMOUS-DEFAULTS entry.
            """))
        rc, out = _run_script(tmp_path)
        assert rc == 0
        # Should not flag as violation — the fix is documented
        assert "[violation]" not in out


# ---------------------------------------------------------------------------
# Low-confidence: merge outcome described without procedure detail
# ---------------------------------------------------------------------------

class TestLowConfidenceWarning:
    def test_status_file_with_merged_commits_no_worktree_flagged(self, tmp_path: Path) -> None:
        """Status file describing MERGED commit SHAs without worktree context → low-confidence."""
        status_dir, _ = _make_run_archive(tmp_path, batch="2026-05-28")
        (status_dir / "S-46.md").write_text(textwrap.dedent("""\
            # S-46 status
            ## Streams (2) — ALL MERGED
            Merging Stream A on top of Stream B.
            - A — MERGED (commit abc1234) — 10 tests
            - B — MERGED (commit def5678) — 8 tests
            """))
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" in out
        assert "[low-confidence]" in out
        assert "S-46.md" in out

    def test_low_confidence_label_not_violation(self, tmp_path: Path) -> None:
        """Pre-pattern runs are low-confidence, not full violations."""
        status_dir, _ = _make_run_archive(tmp_path, batch="2026-05-28")
        (status_dir / "S-47.md").write_text(
            "## Streams — ALL MERGED\n"
            "- A — MERGED (commit aaa1111) — 5 tests\n"
        )
        _, out = _run_script(tmp_path)
        # Should be low-confidence, not violation
        assert "[violation]" not in out or "[low-confidence]" in out


# ---------------------------------------------------------------------------
# ms-enforce registration
# ---------------------------------------------------------------------------

class TestMsEnforceRegistration:
    def test_function_defined_in_ms_enforce(self) -> None:
        """check_merge_worktree_pattern function must be defined in ms-enforce."""
        ms_enforce = REPO / "ms-enforce"
        assert ms_enforce.exists(), "ms-enforce must exist"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "def check_merge_worktree_pattern" in text, \
            "check_merge_worktree_pattern must be defined in ms-enforce"

    def test_function_registered_in_tier1(self) -> None:
        """check_merge_worktree_pattern must appear in the TIER_1 list."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "check_merge_worktree_pattern" in text, \
            "check_merge_worktree_pattern must be registered in TIER_1"
        # Verify it appears in the TIER_1 section
        tier1_start = text.find("TIER_1: list[")
        tier2_start = text.find("TIER_2: list[")
        assert tier1_start != -1, "TIER_1 list must exist"
        tier1_section = text[tier1_start:tier2_start] if tier2_start != -1 else text[tier1_start:]
        assert "check_merge_worktree_pattern" in tier1_section, \
            "check_merge_worktree_pattern must be in the TIER_1 list, not elsewhere"

    def test_registration_label_present(self) -> None:
        """The human-readable label for the check must be present in ms-enforce."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "Merge-worktree pattern" in text, \
            "TIER_1 registration must include a human-readable label for check_merge_worktree_pattern"

    def test_ms_enforce_imports_script_correctly(self) -> None:
        """The check function in ms-enforce references the scanner script by name."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "audit_merge_worktree_pattern" in text, \
            "check_merge_worktree_pattern in ms-enforce must reference the scanner script"
