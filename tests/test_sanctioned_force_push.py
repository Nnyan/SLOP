"""
tests/test_sanctioned_force_push.py — Unit tests for tools/sanctioned/force_push_tag.py.

Tests:
  - Dry-run mode: no push executed, audit entry written with result=DRY-RUN
  - Audit entry written on success path
  - Deny restored after an error path (confirm mismatch, branch ref rejection)
  - Branch ref rejection (refuses refs/heads/*)
  - Non-tag ref rejection (refuses arbitrary non-tag refs)
  - Confirm token mismatch rejection
  - Settings path untouched in dry-run (no lift performed)

All tests operate on fixture/tmp repos and a tmp SANCTIONED-OPS-LOG —
NEVER mutate the real settings.local.json or the real log.
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

from tools.sanctioned.force_push_tag import run, TOOL_NAME


# ── fixtures ──────────────────────────────────────────────────────────────────

FAKE_HEAD_SHA = "abcdef1234567890abcdef1234567890abcdef12"
FAKE_HEAD_SHA_SHORT = FAKE_HEAD_SHA[-7:]  # "bcdef12" — but actually "bcdef12" ... wait, last 7 is chars [-7:]


def _make_settings(tmp_path: Path) -> Path:
    """Create a fixture settings.local.json in tmp_path (matching the deny profile)."""
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
    """Create a fixture settings-wave-mode-profile.json in the same directory."""
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
    """Create both settings and profile; return (settings_path, log_path)."""
    settings = _make_settings(tmp_path)
    _make_profile(tmp_path)
    log = tmp_path / "OPS-LOG.md"
    return settings, log


def _load_settings(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── dry-run tests ─────────────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_writes_audit_entry(self, tmp_path):
        """Dry-run must write an audit entry with result=DRY-RUN."""
        settings, log = _make_fixtures(tmp_path)
        assert not log.exists()

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ):
            rc = run(
                ref="refs/tags/v1.0.0",
                remote="origin",
                reason="test dry-run scrub",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 0
        assert log.exists()
        content = log.read_text(encoding="utf-8")
        assert "DRY-RUN" in content
        assert "force-push refs/tags/v1.0.0" in content
        assert "test dry-run scrub" in content

    def test_dry_run_does_not_lift_deny(self, tmp_path):
        """Dry-run must NOT modify the settings file (no lift performed)."""
        settings, log = _make_fixtures(tmp_path)
        original_content = settings.read_text(encoding="utf-8")

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ):
            run(
                ref="refs/tags/v1.0.0",
                remote="origin",
                reason="dry-run no-lift test",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        assert settings.read_text(encoding="utf-8") == original_content

    def test_dry_run_does_not_call_push(self, tmp_path):
        """Dry-run must not invoke any git push subprocess."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ) as _mock_sha, mock.patch(
            "tools.sanctioned.force_push_tag._do_force_push"
        ) as mock_push:
            run(
                ref="refs/tags/v1.0.0",
                remote="origin",
                reason="no-push test",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        mock_push.assert_not_called()


# ── success path tests ────────────────────────────────────────────────────────

class TestSuccessPath:
    def test_success_writes_ok_audit_entry(self, tmp_path):
        """Live path writes audit entry with result=OK."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.force_push_tag._do_force_push"
        ):
            rc = run(
                ref="refs/tags/v1.2.3",
                remote="origin",
                reason="authorized tag push after scrub",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 0
        content = log.read_text(encoding="utf-8")
        assert "OK" in content
        assert "force-push refs/tags/v1.2.3" in content
        assert "authorized tag push after scrub" in content

    def test_deny_restored_after_success(self, tmp_path):
        """After a successful push, the deny list must be restored to profile state."""
        settings, log = _make_fixtures(tmp_path)
        original_deny = _load_settings(settings)["permissions"]["deny"]

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.force_push_tag._do_force_push"
        ):
            run(
                ref="refs/tags/v2.0.0",
                remote="origin",
                reason="restore-test",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        restored_deny = _load_settings(settings)["permissions"]["deny"]
        assert restored_deny == original_deny, (
            "deny list was not restored after push: expected %r got %r"
            % (original_deny, restored_deny)
        )


# ── error-path tests (deny restored) ─────────────────────────────────────────

class TestErrorPaths:
    def test_branch_ref_rejected_returns_nonzero(self, tmp_path):
        """refs/heads/* must be refused with exit code 1 and no audit entry."""
        settings, log = _make_fixtures(tmp_path)

        rc = run(
            ref="refs/heads/main",
            remote="origin",
            reason="should be rejected",
            confirm="any",
            dry_run=False,
            settings_path=settings,
            log_path=log,
        )

        assert rc == 1
        assert not log.exists()

    def test_non_tag_non_branch_ref_rejected(self, tmp_path):
        """An arbitrary ref (not refs/tags/*) must be refused."""
        settings, log = _make_fixtures(tmp_path)

        rc = run(
            ref="refs/notes/commits",
            remote="origin",
            reason="should be rejected",
            confirm="any",
            dry_run=False,
            settings_path=settings,
            log_path=log,
        )

        assert rc == 1
        assert not log.exists()

    def test_confirm_mismatch_rejected(self, tmp_path):
        """Wrong --confirm token must be refused with exit code 1."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ):
            rc = run(
                ref="refs/tags/v1.0.0",
                remote="origin",
                reason="test confirm mismatch",
                confirm="wronggg",  # does not match FAKE_HEAD_SHA[-7:]
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 1
        assert not log.exists(), "audit log must NOT be written on confirm mismatch"

    def test_deny_restored_after_push_failure(self, tmp_path):
        """If the push subprocess fails, deny list must still be restored."""
        settings, log = _make_fixtures(tmp_path)
        original_deny = _load_settings(settings)["permissions"]["deny"]

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.force_push_tag._do_force_push",
            side_effect=subprocess.CalledProcessError(1, "git push"),
        ):
            rc = run(
                ref="refs/tags/v1.0.0",
                remote="origin",
                reason="failure-restore test",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        assert rc == 1
        # deny MUST be restored
        restored_deny = _load_settings(settings)["permissions"]["deny"]
        assert restored_deny == original_deny, (
            "deny not restored after push failure: expected %r got %r"
            % (original_deny, restored_deny)
        )

    def test_push_failure_writes_failed_audit_entry(self, tmp_path):
        """A push failure must still write an audit entry (with FAILED result)."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ), mock.patch(
            "tools.sanctioned.force_push_tag._do_force_push",
            side_effect=subprocess.CalledProcessError(1, "git push"),
        ):
            run(
                ref="refs/tags/v1.0.0",
                remote="origin",
                reason="push-failure audit test",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=False,
                settings_path=settings,
                log_path=log,
            )

        assert log.exists()
        content = log.read_text(encoding="utf-8")
        assert "FAILED" in content


# ── audit entry content tests ─────────────────────────────────────────────────

class TestAuditContent:
    def test_audit_contains_tool_name(self, tmp_path):
        """Audit entry must contain the tool name."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ):
            run(
                ref="refs/tags/v1.0.0",
                remote="origin",
                reason="audit content test",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        content = log.read_text(encoding="utf-8")
        assert TOOL_NAME in content

    def test_audit_contains_pre_sha(self, tmp_path):
        """Audit entry must record the pre-push HEAD SHA."""
        settings, log = _make_fixtures(tmp_path)

        with mock.patch(
            "tools.sanctioned.force_push_tag._get_head_sha",
            return_value=FAKE_HEAD_SHA,
        ):
            run(
                ref="refs/tags/v1.0.0",
                remote="origin",
                reason="sha test",
                confirm=FAKE_HEAD_SHA[-7:],
                dry_run=True,
                settings_path=settings,
                log_path=log,
            )

        content = log.read_text(encoding="utf-8")
        assert FAKE_HEAD_SHA in content
