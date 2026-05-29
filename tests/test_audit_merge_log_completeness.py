"""tests/test_audit_merge_log_completeness.py

Tests for tools/audit_merge_log_completeness.py

Strategy: build a temporary git repository with a controlled commit history
so the tests are fully deterministic and do not depend on the live repo's
history. Each test scenario sets up a specific git topology and verifies
whether the scanner emits (or does not emit) WARNING lines.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Make sure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.audit_merge_log_completeness import audit  # noqa: E402


# ─── Fixture helpers ──────────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> str:
    """Run a git command in repo. Returns stdout. Raises on error."""
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "git " + " ".join(args) + " failed:\n" + result.stderr.strip()
        )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    """Initialise a fresh git repo in tmp_path with a baseline commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    # Add an initial commit so HEAD is valid
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def _write_and_commit(repo: Path, filename: str, content: str, message: str) -> str:
    """Write a file and commit it. Returns the commit SHA."""
    (repo / filename).write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _make_merge_commit(
    repo: Path, branch_name: str, file_in_branch: str, merge_message: str
) -> str:
    """Create a branch with one commit, then merge it back to main.

    Returns the merge commit SHA.
    """
    # Create and switch to branch
    _git(repo, "checkout", "-b", branch_name)
    _write_and_commit(repo, file_in_branch, "content\n", "branch work")
    # Merge back to main
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", branch_name, "-m", merge_message)
    return _git(repo, "rev-parse", "HEAD")


def _introduce_merge_log(repo: Path) -> str:
    """Add docs/MERGE-LOG.md introduction commit. Returns SHA."""
    docs_dir = repo / "docs"
    docs_dir.mkdir(exist_ok=True)
    return _write_and_commit(
        repo, "docs/MERGE-LOG.md",
        "# Wave Merge Log\n\nAudit trail.\n",
        "audit: introduce docs/MERGE-LOG.md",
    )


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestCleanPass:
    """Scenarios where every merge has an audit trail → no warnings."""

    def test_no_merges(self, tmp_path: Path) -> None:
        """Repository with only non-merge commits → no warnings."""
        repo = _init_repo(tmp_path)
        _write_and_commit(repo, "a.txt", "a\n", "add a")
        _write_and_commit(repo, "b.txt", "b\n", "add b")
        result = audit(repo)
        assert result == [], f"Expected no warnings, got: {result}"

    def test_merge_followed_by_merge_log_update(self, tmp_path: Path) -> None:
        """Merge commit followed immediately by a MERGE-LOG update → clean."""
        repo = _init_repo(tmp_path)
        # Introduce the log so merge isn't pre-era
        _introduce_merge_log(repo)
        # Create a merge
        _make_merge_commit(
            repo, "feat/x", "x.txt", "merge: feat/x into main"
        )
        # Immediately add a MERGE-LOG entry after the merge
        docs_dir = repo / "docs"
        docs_dir.mkdir(exist_ok=True)
        _write_and_commit(
            repo, "docs/MERGE-LOG.md",
            "# Wave Merge Log\n\n## 2026-05-29 — feat/x merged\n\n- Method: operator\n",
            "audit: log feat/x merge to docs/MERGE-LOG.md",
        )
        result = audit(repo)
        assert result == [], f"Expected no warnings, got: {result}"

    def test_merge_message_references_merge_log(self, tmp_path: Path) -> None:
        """Merge commit message that references MERGE-LOG → clean (FP2 guard)."""
        repo = _init_repo(tmp_path)
        _introduce_merge_log(repo)
        _make_merge_commit(
            repo, "feat/y", "y.txt",
            "merge: feat/y into main — see docs/MERGE-LOG.md for audit entry"
        )
        result = audit(repo)
        assert result == [], f"Expected no warnings, got: {result}"

    def test_pre_merge_log_era_merge_excluded(self, tmp_path: Path) -> None:
        """Merge commits that predate MERGE-LOG introduction → excluded (FP1)."""
        repo = _init_repo(tmp_path)
        # Merge BEFORE the MERGE-LOG introduction
        _make_merge_commit(repo, "old/feat", "old.txt", "merge: old feature")
        # Now introduce the log
        _introduce_merge_log(repo)
        result = audit(repo)
        assert result == [], (
            "Pre-MERGE-LOG era merges must be excluded from warnings, got: "
            + str(result)
        )

    def test_audit_entry_in_preceding_commit(self, tmp_path: Path) -> None:
        """MERGE-LOG entry committed just before the merge commit → clean."""
        repo = _init_repo(tmp_path)
        _introduce_merge_log(repo)
        # Commit the audit entry before the merge (sibling pattern, FP3)
        _write_and_commit(
            repo, "docs/MERGE-LOG.md",
            "# Wave Merge Log\n\n## 2026-05-29 — pre-committed entry\n\n- Method: operator\n",
            "audit: pre-log merge entry",
        )
        _make_merge_commit(repo, "feat/z", "z.txt", "merge: feat/z into main")
        result = audit(repo)
        assert result == [], f"Expected no warnings, got: {result}"

    def test_audit_entry_within_window(self, tmp_path: Path) -> None:
        """MERGE-LOG entry within 3 commits of merge → clean even with spacing."""
        repo = _init_repo(tmp_path)
        _introduce_merge_log(repo)
        _make_merge_commit(repo, "feat/w", "w.txt", "merge: feat/w into main")
        # Add two unrelated commits, then the audit entry
        _write_and_commit(repo, "c1.txt", "c1\n", "chore: cleanup 1")
        _write_and_commit(repo, "c2.txt", "c2\n", "chore: cleanup 2")
        _write_and_commit(
            repo, "docs/MERGE-LOG.md",
            "# Wave Merge Log\n\n## 2026-05-29 — feat/w\n\n- Method: operator\n",
            "audit: log feat/w merge",
        )
        result = audit(repo, window=3)
        assert result == [], f"Expected no warnings, got: {result}"


class TestWarnCases:
    """Scenarios where a merge lacks an audit trail → warnings expected."""

    def test_merge_without_audit_entry(self, tmp_path: Path) -> None:
        """Merge commit with no MERGE-LOG update → warning emitted."""
        repo = _init_repo(tmp_path)
        _introduce_merge_log(repo)
        _make_merge_commit(repo, "feat/bad", "bad.txt", "merge: feat/bad into main")
        # No MERGE-LOG update follows
        result = audit(repo)
        assert len(result) == 1, (
            "Expected exactly 1 warning for the merge without audit entry, got: "
            + str(result)
        )
        sha7, subject = result[0]
        assert "feat/bad" in subject or len(sha7) == 7

    def test_audit_entry_outside_window(self, tmp_path: Path) -> None:
        """MERGE-LOG entry too far from merge (> window commits away) → warning."""
        repo = _init_repo(tmp_path)
        _introduce_merge_log(repo)
        _make_merge_commit(repo, "feat/far", "far.txt", "merge: feat/far into main")
        # Add 5 commits before the audit entry (window=3 → too far)
        for i in range(5):
            _write_and_commit(repo, f"gap{i}.txt", f"g{i}\n", f"chore: gap {i}")
        _write_and_commit(
            repo, "docs/MERGE-LOG.md",
            "# Wave Merge Log\n\n## 2026-05-29 — late entry\n\n- Method: operator\n",
            "audit: late merge log entry",
        )
        result = audit(repo, window=3)
        assert len(result) >= 1, (
            "Expected warning for merge with audit entry beyond window, got: "
            + str(result)
        )

    def test_multiple_merges_one_untracked(self, tmp_path: Path) -> None:
        """Two merges: one tracked, one not → exactly one warning.

        We separate the merges with enough non-audit commits so that the
        audit window of the untracked merge (window=2) does not overlap
        with the audit entry of the tracked merge.
        """
        repo = _init_repo(tmp_path)
        _introduce_merge_log(repo)

        # First merge — tracked
        _make_merge_commit(repo, "feat/tracked", "tracked.txt", "merge: feat/tracked")
        _write_and_commit(
            repo, "docs/MERGE-LOG.md",
            "# Wave Merge Log\n\n## 2026-05-29 — tracked\n\n- Method: operator\n",
            "audit: log tracked merge",
        )

        # Add gap commits so the untracked merge's window (window=2) doesn't
        # overlap the tracked-merge audit entry
        _write_and_commit(repo, "gap1.txt", "g\n", "chore: gap 1")
        _write_and_commit(repo, "gap2.txt", "g\n", "chore: gap 2")
        _write_and_commit(repo, "gap3.txt", "g\n", "chore: gap 3")

        # Second merge — not tracked (no audit entry)
        _make_merge_commit(repo, "feat/missing", "missing.txt", "merge: feat/missing")
        # No audit entry follows

        result = audit(repo, window=2)
        assert len(result) == 1, (
            "Expected exactly 1 warning (for the untracked merge), got: "
            + str(result)
        )
        _sha7, subject = result[0]
        assert "feat/missing" in subject


class TestEdgeCases:
    """Edge cases: empty repos, missing MERGE-LOG file, etc."""

    def test_empty_repo_no_commits(self, tmp_path: Path) -> None:
        """A repo with zero commits → no crash, no warnings."""
        repo = tmp_path / "empty"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@t.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "T"],
            capture_output=True,
        )
        # No commits — HEAD is unborn; audit should return empty gracefully
        result = audit(repo)
        assert result == [], f"Empty repo should produce no warnings, got: {result}"

    def test_no_merge_log_file_all_merges_flagged(self, tmp_path: Path) -> None:
        """When MERGE-LOG.md never existed, intro_sha=None → all merges are in-scope."""
        repo = _init_repo(tmp_path)
        # Do NOT introduce MERGE-LOG.md — so intro_sha = None, no FP1 exclusion
        _make_merge_commit(repo, "feat/nofile", "nf.txt", "merge: feat/nofile")
        result = audit(repo)
        # The merge exists and MERGE-LOG.md never existed → must warn
        assert len(result) == 1, (
            "With no MERGE-LOG.md, in-scope merges must be warned. Got: "
            + str(result)
        )

    def test_merge_log_reference_in_neighbour_message(self, tmp_path: Path) -> None:
        """Neighbour commit with 'MERGE-LOG' in its message → accepted as trail."""
        repo = _init_repo(tmp_path)
        _introduce_merge_log(repo)
        _make_merge_commit(repo, "feat/ref", "ref.txt", "merge: feat/ref")
        # The next commit references MERGE-LOG in its message
        _write_and_commit(
            repo, "notes.txt", "see MERGE-LOG\n",
            "docs: updated MERGE-LOG with batch notes"
        )
        result = audit(repo)
        assert result == [], f"Expected no warnings, got: {result}"
