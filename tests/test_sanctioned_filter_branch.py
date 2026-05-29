"""
tests/test_sanctioned_filter_branch.py — Unit tests for
tools/sanctioned/filter_branch_secret_scrub.py.

Tests:
  - Dry-run mode: no rewrite executed, audit entry written with result=DRY-RUN
  - Audit entry written on success path
  - Deny restored after an error path (dirty tree, rewrite failure)
  - Dirty working tree rejection (require_clean=True by default)
  - Filter-branch failure: deny still restored, FAILED audit entry written
  - Audit entry includes tool name, path pattern, pre_sha

All tests operate on fixture/tmp repos and a tmp log — NEVER mutate the real
settings.local.json or the real log.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

# Make tools/ importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.sanctioned.filter_branch_secret_scrub import run, TOOL_NAME


# ── fixtures ──────────────────────────────────────────────────────────────────

FAKE_HEAD_SHA = "1111222233334444555566667777888899990000"
FAKE_POST_SHA = "aaaa1111bbbb2222cccc3333dddd4444eeee5555"


def _make_settings(tmp_path: Path) -> Path:
    """Create a fixture settings.local.json in tmp_path."""
    data = {
        "permissions": {
            "allow": ["Read", "Edit", "Write"],
            "deny": [
                "Bash(git push*)",
                "Bash(git push -f*)",
                "Bash(git checkout main*)",
                "Bash(git switch main*)",
                "Bash(sudo *)",
            ],
            "defaultMode": "bypassPermissions",
        }
    }
    path = tmp_path / "settings.local.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _make_profile(tmp_path: Path) -> Path:
    """Create a fixture settings-wave-mode-profile.json in same directory."""
    data = {
        "permissions": {
            "allow": ["Read", "Edit", "Write"],
            "deny": [
                "Bash(git push*)",
                "Bash(git push -f*)",
                "Bash(git checkout main*)",
                "Bash(git switch main*)",
                "Bash(sudo *)",
            ],
            "defaultMode": "bypassPermissions",
        }
    }
    path = tmp_path / "settings-wave-mode-profile.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _make_fixtures(tmp_path: Path):
    """Create settings + profile, return (settings_path, log_path)."""
    settings = _make_settings(tmp_path)
    _make_profile(tmp_path)
    log = tmp_path / "FILTER-OPS-LOG.md"
    return settings, log


def _load_settings(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── dry-run tests ─────────────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_writes_dry_run_audit_entry(self, tmp_path):
        """Dry-run must write audit entry with result=DRY-RUN."""
        settings, log = _make_fixtures(tmp_path)
        assert not log.exists()

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ):
            rc = run(
                path_pattern="path/to/secret.key",
                reason="test dry-run secret scrub",
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 0
        assert log.exists()
        content = log.read_text(encoding="utf-8")
        assert "DRY-RUN" in content
        assert "path/to/secret.key" in content
        assert "test dry-run secret scrub" in content

    def test_dry_run_does_not_call_filter_branch(self, tmp_path):
        """Dry-run must not invoke the actual filter-branch subprocess."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._run_filter_branch"
        ) as mock_fb:
            run(
                path_pattern="secret.pem",
                reason="dry-run no-fb test",
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        mock_fb.assert_not_called()

    def test_dry_run_does_not_modify_settings(self, tmp_path):
        """Dry-run must NOT modify settings (no lift)."""
        settings, log = _make_fixtures(tmp_path)
        original_content = settings.read_text(encoding="utf-8")

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ):
            run(
                path_pattern="secret.pem",
                reason="dry-run settings-unchanged test",
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        assert settings.read_text(encoding="utf-8") == original_content


# ── success path tests ────────────────────────────────────────────────────────

class TestSuccessPath:
    def test_success_writes_ok_audit_entry(self, tmp_path):
        """Successful scrub must write audit entry with result=OK."""
        settings, log = _make_fixtures(tmp_path)

        sha_iter = iter([FAKE_HEAD_SHA, FAKE_POST_SHA])

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            side_effect=sha_iter,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._run_filter_branch",
        ):
            rc = run(
                path_pattern="secrets/tailscale.key",
                reason="scrub Tailscale key from history",
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 0
        content = log.read_text(encoding="utf-8")
        assert "OK" in content
        assert "secrets/tailscale.key" in content

    def test_deny_restored_after_success(self, tmp_path):
        """After a successful scrub, deny list must be restored to profile state."""
        settings, log = _make_fixtures(tmp_path)
        original_deny = _load_settings(settings)["permissions"]["deny"]

        sha_iter = iter([FAKE_HEAD_SHA, FAKE_POST_SHA])

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            side_effect=sha_iter,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._run_filter_branch",
        ):
            run(
                path_pattern="key.pem",
                reason="restore-test",
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        restored_deny = _load_settings(settings)["permissions"]["deny"]
        assert restored_deny == original_deny, (
            "deny not restored after success: expected %r got %r"
            % (original_deny, restored_deny)
        )


# ── error-path tests (deny restored) ─────────────────────────────────────────

class TestErrorPaths:
    def test_dirty_tree_rejected(self, tmp_path):
        """Dirty working tree must be rejected with exit code 1."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=False,  # dirty!
        ):
            rc = run(
                path_pattern="secret.pem",
                reason="dirty tree test",
                dry_run=False,
                require_clean=True,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 1
        assert not log.exists(), "no audit entry should be written on dirty-tree rejection"

    def test_dirty_tree_allowed_with_allow_dirty(self, tmp_path):
        """allow_dirty=True should skip the clean check."""
        settings, log = _make_fixtures(tmp_path)

        sha_iter = iter([FAKE_HEAD_SHA, FAKE_POST_SHA])

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            side_effect=sha_iter,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=False,  # dirty, but bypassed
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._run_filter_branch",
        ):
            rc = run(
                path_pattern="secret.pem",
                reason="allow dirty test",
                dry_run=False,
                require_clean=False,  # override
                settings_path=settings,
                log_path=log,
            )

        assert rc == 0

    def test_filter_branch_failure_restores_deny(self, tmp_path):
        """If filter-branch fails, deny list must still be restored."""
        settings, log = _make_fixtures(tmp_path)
        original_deny = _load_settings(settings)["permissions"]["deny"]

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._run_filter_branch",
            side_effect=subprocess.CalledProcessError(1, "git filter-branch"),
        ):
            rc = run(
                path_pattern="fail.key",
                reason="failure-restore test",
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 1
        restored_deny = _load_settings(settings)["permissions"]["deny"]
        assert restored_deny == original_deny, (
            "deny not restored after filter-branch failure: expected %r got %r"
            % (original_deny, restored_deny)
        )

    def test_filter_branch_failure_writes_failed_audit_entry(self, tmp_path):
        """A filter-branch failure must write a FAILED audit entry."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._run_filter_branch",
            side_effect=subprocess.CalledProcessError(1, "git filter-branch"),
        ):
            run(
                path_pattern="fail.key",
                reason="failure audit test",
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        assert log.exists()
        content = log.read_text(encoding="utf-8")
        assert "FAILED" in content

    def test_not_in_git_repo_returns_nonzero(self, tmp_path):
        """Not being in a git repo must return exit code 1."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            rc = run(
                path_pattern="secret.pem",
                reason="no-repo test",
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 1
        assert not log.exists()


# ── audit entry content tests ─────────────────────────────────────────────────

class TestAuditContent:
    def test_audit_contains_tool_name(self, tmp_path):
        """Audit entry must include the tool name."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ):
            run(
                path_pattern="some/secret",
                reason="tool-name test",
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        content = log.read_text(encoding="utf-8")
        assert TOOL_NAME in content

    def test_audit_contains_pre_sha(self, tmp_path):
        """Audit entry must record the pre-scrub HEAD SHA."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ):
            run(
                path_pattern="some/secret",
                reason="sha-test",
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        content = log.read_text(encoding="utf-8")
        assert FAKE_HEAD_SHA in content

    def test_audit_contains_path_pattern(self, tmp_path):
        """Audit entry must include the path pattern being scrubbed."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._get_repo_root",
            return_value=tmp_path,
        ), mock.patch(
            "tools.sanctioned.filter_branch_secret_scrub._check_working_tree_clean",
            return_value=True,
        ):
            run(
                path_pattern="credentials/private_key.pem",
                reason="pattern-test",
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        content = log.read_text(encoding="utf-8")
        assert "credentials/private_key.pem" in content
