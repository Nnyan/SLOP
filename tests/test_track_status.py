"""tests/test_track_status.py — tests for tools/check_track_status.py

Uses a temporary git repository to test the untracked-file invariant gate.
Test cases:
  - Tracked file → pass (no violation)
  - Gitignored file → pass
  - Allowlisted file (with reason) → pass
  - Allowlisted file (no reason comment) → check itself errors with a clear message
  - Untracked-not-ignored-not-allowlisted file → fail with path listed in output
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Allow importing the script from the tools/ directory
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from check_track_status import is_allowlisted, main, parse_allowlist  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo in tmp_path and return the root."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    return tmp_path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


def _write_allowlist(repo: Path, contents: str) -> None:
    (repo / ".track-allowlist").write_text(contents, encoding="utf-8")


def _add_tracked(repo: Path, filename: str, content: str = "data\n") -> None:
    """Write a file and git-add + commit it so it is tracked."""
    f = repo / filename
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", f"add {filename}")


def _run_check(repo: Path) -> tuple[int, str, str]:
    """Run main() via subprocess so we capture stdout/stderr independently."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "check_track_status.py"), "--repo", str(repo)],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTrackedFile:
    """A file that is git-tracked must never appear as a violation."""

    def test_tracked_file_passes(self, tmp_git_repo: Path) -> None:
        _write_allowlist(tmp_git_repo, "")
        _git(tmp_git_repo, "add", ".track-allowlist")
        _git(tmp_git_repo, "commit", "-m", "init")

        _add_tracked(tmp_git_repo, "tracked.txt")

        rc, out, err = _run_check(tmp_git_repo)
        assert rc == 0, f"Expected pass; stderr={err!r}, stdout={out!r}"


class TestGitIgnoredFile:
    """A file matching .gitignore is not untracked from git's perspective
    (git --exclude-standard hides it). The gate must pass."""

    def test_gitignored_file_passes(self, tmp_git_repo: Path) -> None:
        _write_allowlist(tmp_git_repo, "")
        (tmp_git_repo / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
        _git(tmp_git_repo, "add", ".track-allowlist", ".gitignore")
        _git(tmp_git_repo, "commit", "-m", "init")

        # Create the ignored file — git ls-files --others --exclude-standard won't see it
        (tmp_git_repo / "ignored.log").write_text("noise\n", encoding="utf-8")

        rc, out, err = _run_check(tmp_git_repo)
        assert rc == 0, f"Gitignored file should not trigger failure; stderr={err!r}"


class TestAllowlistedWithReason:
    """A file matching an allowlist entry that has a reason comment passes."""

    def test_allowlisted_with_reason_passes(self, tmp_git_repo: Path) -> None:
        _write_allowlist(
            tmp_git_repo,
            "scratch/**  # reason: developer scratch files, never tracked\n",
        )
        _git(tmp_git_repo, "add", ".track-allowlist")
        _git(tmp_git_repo, "commit", "-m", "init")

        # Create an untracked scratch file
        (tmp_git_repo / "scratch").mkdir()
        (tmp_git_repo / "scratch" / "notes.txt").write_text("temp\n", encoding="utf-8")

        rc, out, err = _run_check(tmp_git_repo)
        assert rc == 0, f"Allowlisted file should pass; stderr={err!r}, stdout={out!r}"


class TestAllowlistedMissingReason:
    """An allowlist entry without '# reason:' is a configuration error.
    The check itself must exit non-zero with a clear diagnostic message."""

    def test_missing_reason_is_an_error(self, tmp_git_repo: Path) -> None:
        # Write a malformed allowlist entry (no reason comment)
        _write_allowlist(
            tmp_git_repo,
            "scratch/**\n",  # deliberately missing # reason:
        )
        _git(tmp_git_repo, "add", ".track-allowlist")
        _git(tmp_git_repo, "commit", "-m", "init")

        rc, out, err = _run_check(tmp_git_repo)
        assert rc != 0, "Should fail on malformed allowlist"
        combined = out + err
        assert "reason" in combined.lower(), (
            f"Error message should mention 'reason'; got stdout={out!r}, stderr={err!r}"
        )
        assert "ALLOWLIST ERROR" in combined or "error" in combined.lower(), (
            f"Should print an error diagnostic; got stdout={out!r}, stderr={err!r}"
        )

    def test_missing_reason_message_names_line(self, tmp_git_repo: Path) -> None:
        """Error message should identify the problematic allowlist entry."""
        _write_allowlist(
            tmp_git_repo,
            "badglob/**\n",
        )
        _git(tmp_git_repo, "add", ".track-allowlist")
        _git(tmp_git_repo, "commit", "-m", "init")

        rc, out, err = _run_check(tmp_git_repo)
        assert rc != 0
        combined = out + err
        assert "badglob" in combined, (
            f"Error should name the offending glob; got {combined!r}"
        )


class TestUntrackedNotAllowlisted:
    """A file that is untracked, not gitignored, and not allowlisted must
    cause exit 1 with the file path listed in output."""

    def test_violation_causes_failure(self, tmp_git_repo: Path) -> None:
        _write_allowlist(tmp_git_repo, "")
        _git(tmp_git_repo, "add", ".track-allowlist")
        _git(tmp_git_repo, "commit", "-m", "init")

        # Drop a file with no coverage
        (tmp_git_repo / "orphan.py").write_text("# orphan\n", encoding="utf-8")

        rc, out, err = _run_check(tmp_git_repo)
        assert rc == 1, f"Expected failure for untracked file; stdout={out!r}"

    def test_violation_names_the_file(self, tmp_git_repo: Path) -> None:
        _write_allowlist(tmp_git_repo, "")
        _git(tmp_git_repo, "add", ".track-allowlist")
        _git(tmp_git_repo, "commit", "-m", "init")

        (tmp_git_repo / "mystery.txt").write_text("mystery\n", encoding="utf-8")

        rc, out, err = _run_check(tmp_git_repo)
        assert rc == 1
        assert "mystery.txt" in out, (
            f"Output should name the violating file; stdout={out!r}"
        )

    def test_guidance_string_in_output(self, tmp_git_repo: Path) -> None:
        """Violation output must include the 'Add to .gitignore...' guidance."""
        _write_allowlist(tmp_git_repo, "")
        _git(tmp_git_repo, "add", ".track-allowlist")
        _git(tmp_git_repo, "commit", "-m", "init")

        (tmp_git_repo / "leaked.conf").write_text("secret=x\n", encoding="utf-8")

        rc, out, err = _run_check(tmp_git_repo)
        assert rc == 1
        assert ".gitignore" in out or ".track-allowlist" in out, (
            f"Guidance should mention .gitignore or .track-allowlist; stdout={out!r}"
        )


# ---------------------------------------------------------------------------
# Unit tests for helper functions (no git subprocess needed)
# ---------------------------------------------------------------------------


class TestParseAllowlist:
    def test_empty_file_returns_no_entries(self, tmp_path: Path) -> None:
        (tmp_path / ".track-allowlist").write_text("", encoding="utf-8")
        entries, errors = parse_allowlist(tmp_path)
        assert entries == []
        assert errors == []

    def test_comment_only_lines_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / ".track-allowlist").write_text(
            "# this is a comment\n\n# another comment\n", encoding="utf-8"
        )
        entries, errors = parse_allowlist(tmp_path)
        assert entries == []
        assert errors == []

    def test_valid_entry_parsed(self, tmp_path: Path) -> None:
        (tmp_path / ".track-allowlist").write_text(
            "foo/**  # reason: scratch dir\n", encoding="utf-8"
        )
        entries, errors = parse_allowlist(tmp_path)
        assert len(entries) == 1
        assert entries[0][0] == "foo/**"
        assert "scratch dir" in entries[0][1]
        assert errors == []

    def test_missing_reason_is_error(self, tmp_path: Path) -> None:
        (tmp_path / ".track-allowlist").write_text("foo/**\n", encoding="utf-8")
        entries, errors = parse_allowlist(tmp_path)
        assert entries == []
        assert len(errors) == 1
        assert "reason" in errors[0].lower()

    def test_nonexistent_allowlist_returns_empty(self, tmp_path: Path) -> None:
        entries, errors = parse_allowlist(tmp_path)
        assert entries == []
        assert errors == []


class TestIsAllowlisted:
    def test_simple_glob_match(self) -> None:
        entries = [("*.log", "log files")]
        assert is_allowlisted("app.log", entries)
        assert not is_allowlisted("app.py", entries)

    def test_path_glob_match(self) -> None:
        entries = [("scratch/**", "temp files")]
        assert is_allowlisted("scratch/notes.txt", entries)
        assert not is_allowlisted("other/notes.txt", entries)

    def test_no_entries_means_no_match(self) -> None:
        assert not is_allowlisted("anything.txt", [])
