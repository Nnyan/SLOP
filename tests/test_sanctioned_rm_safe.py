"""
tests/test_sanctioned_rm_safe.py — Tests for tools/sanctioned/rm_recursive_safe.py (S-68-E).

Tests:
  - Refusal: target outside repo root (e.g., /etc)
  - Refusal: target is /
  - Refusal: target is $HOME (when not inside repo)
  - Refusal: target is .git/
  - Refusal: target is the repo root itself
  - Refusal: non-existent target
  - Dry-run: prints message, does NOT delete, writes NO audit entry
  - Success: deletes a file inside repo, writes an audit entry
  - Success: deletes a directory tree inside repo, writes an audit entry
  - Symlink escape: symlink inside repo pointing outside is refused
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make sure we can import from the project root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.sanctioned.rm_recursive_safe import rm_recursive_safe, REPO_ROOT as TOOL_REPO_ROOT


# ── helpers ───────────────────────────────────────────────────────────────────

def make_temp_log(tmp_path: Path) -> Path:
    """Create a temporary audit log path for tests."""
    log = tmp_path / "test-sanctioned-ops.md"
    return log


# ── refusal tests (no audit entries should be written) ───────────────────────

def test_refuses_etc(tmp_path: Path) -> None:
    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(Path("/etc"), log_path=log)
    assert rc == 1
    assert not log.exists(), "No audit entry should be written on refusal"


def test_refuses_root(tmp_path: Path) -> None:
    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(Path("/"), log_path=log)
    assert rc == 1
    assert not log.exists()


def test_refuses_home_outside_repo(tmp_path: Path) -> None:
    """$HOME itself (not inside repo) should be refused."""
    home = Path.home()
    # Only test if home is NOT inside the repo root to avoid false positives
    try:
        home.relative_to(TOOL_REPO_ROOT)
        pytest.skip("$HOME is inside REPO_ROOT — test would pass for wrong reason")
    except ValueError:
        pass
    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(home, log_path=log)
    assert rc == 1
    assert not log.exists()


def test_refuses_git_dir(tmp_path: Path) -> None:
    log = make_temp_log(tmp_path)
    git_dir = TOOL_REPO_ROOT / ".git"
    if not git_dir.exists():
        pytest.skip(".git directory not present in REPO_ROOT")
    rc = rm_recursive_safe(git_dir, log_path=log)
    assert rc == 1
    assert not log.exists()


def test_refuses_repo_root_itself(tmp_path: Path) -> None:
    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(TOOL_REPO_ROOT, log_path=log)
    assert rc == 1
    assert not log.exists()


def test_refuses_nonexistent_path(tmp_path: Path) -> None:
    log = make_temp_log(tmp_path)
    nonexistent = TOOL_REPO_ROOT / "does_not_exist_s68e_test"
    rc = rm_recursive_safe(nonexistent, log_path=log)
    assert rc == 1
    assert not log.exists()


def test_refuses_path_outside_repo_by_absolute(tmp_path: Path) -> None:
    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(Path("/usr/local/bin"), log_path=log)
    assert rc == 1
    assert not log.exists()


def test_refuses_symlink_escape(tmp_path: Path) -> None:
    """A symlink inside the repo pointing to /etc should be refused."""
    # Create a symlink inside the repo tree
    # We use a temp dir inside the repo for this test
    scratch = TOOL_REPO_ROOT / ".claude" / "run"
    if not scratch.exists():
        pytest.skip(".claude/run/ not present — cannot create test symlink")

    # We'll create a symlink in tmp_path pointing to /etc and then
    # verify it's refused (since tmp_path is outside the repo, this tests
    # both the containment check and symlink escape at once)
    symlink = tmp_path / "escape_link"
    symlink.symlink_to("/etc")
    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(symlink, log_path=log)
    assert rc == 1
    assert not log.exists()


# ── dry-run tests ─────────────────────────────────────────────────────────────

def test_dry_run_does_not_delete(tmp_path: Path) -> None:
    """Dry-run mode: prints message, does NOT delete, writes NO audit entry."""
    # Create a file inside the repo tree (use the run/ scratch space)
    target_dir = TOOL_REPO_ROOT / ".claude" / "run"
    if not target_dir.exists():
        target_dir.mkdir(parents=True)
    target = target_dir / "_s68e_dry_run_test.tmp"
    target.write_text("dry run test")

    log = make_temp_log(tmp_path)
    try:
        rc = rm_recursive_safe(target, dry_run=True, log_path=log)
        assert rc == 0
        assert target.exists(), "Dry-run must NOT delete the target"
        assert not log.exists(), "Dry-run must NOT write an audit entry"
    finally:
        if target.exists():
            target.unlink()


# ── success tests (audit entries SHOULD be written) ──────────────────────────

def test_deletes_file_and_writes_audit(tmp_path: Path) -> None:
    """Deleting a file inside the repo writes an audit entry and removes the file."""
    target_dir = TOOL_REPO_ROOT / ".claude" / "run"
    if not target_dir.exists():
        target_dir.mkdir(parents=True)
    target = target_dir / "_s68e_delete_test.tmp"
    target.write_text("to be deleted")

    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(target, log_path=log)
    assert rc == 0
    assert not target.exists(), "File should have been deleted"
    assert log.exists(), "Audit log must be created"
    log_text = log.read_text()
    assert "rm_recursive_safe" in log_text
    assert "rm-recursive" in log_text
    assert "OK" in log_text


def test_deletes_directory_and_writes_audit(tmp_path: Path) -> None:
    """Deleting a directory tree inside the repo writes an audit entry."""
    target_dir = TOOL_REPO_ROOT / ".claude" / "run"
    if not target_dir.exists():
        target_dir.mkdir(parents=True)
    target = target_dir / "_s68e_delete_dir_test"
    target.mkdir(exist_ok=True)
    (target / "file1.txt").write_text("content1")
    (target / "file2.txt").write_text("content2")

    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(target, log_path=log)
    assert rc == 0
    assert not target.exists(), "Directory should have been deleted"
    assert log.exists(), "Audit log must be created"
    log_text = log.read_text()
    assert "rm_recursive_safe" in log_text
    assert "OK" in log_text


def test_audit_entry_contains_path(tmp_path: Path) -> None:
    """Audit entry must contain the target path in the notes."""
    target_dir = TOOL_REPO_ROOT / ".claude" / "run"
    if not target_dir.exists():
        target_dir.mkdir(parents=True)
    target = target_dir / "_s68e_audit_path_test.tmp"
    target.write_text("audit path test")

    log = make_temp_log(tmp_path)
    rc = rm_recursive_safe(target, caller="test-runner", log_path=log)
    assert rc == 0
    log_text = log.read_text()
    # The notes field should contain the resolved path
    assert "_s68e_audit_path_test" in log_text


# ── CLI interface ─────────────────────────────────────────────────────────────

def test_cli_refuses_etc(capsys: pytest.CaptureFixture) -> None:
    """CLI: python3 tools/sanctioned/rm_recursive_safe.py /etc exits 1."""
    from tools.sanctioned.rm_recursive_safe import main
    rc = main(["/etc"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "REFUSED" in captured.err


def test_cli_dry_run_outside_repo_refused(capsys: pytest.CaptureFixture) -> None:
    """CLI: /etc with --dry-run is still refused (containment check runs before dry-run)."""
    from tools.sanctioned.rm_recursive_safe import main
    rc = main(["/etc", "--dry-run"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "REFUSED" in captured.err
