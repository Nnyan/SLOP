"""tests/test_ms_deps_refresh.py — Tests for tools.ms_deps.refresh.

Wave: S-49-B

Design:
- All subprocess calls (uv lock, pip-audit) are mocked.
- A real temporary lockfile is used as a fixture — we never modify the
  project's actual uv.lock (wave rule #9 forbids it).
- tools.ms_deps.diff is stubbed via mock.patch so tests are not coupled to
  Stream A's deliverable. At merge time the real module replaces the stub
  automatically.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# The module under test
# ---------------------------------------------------------------------------
import tools.ms_deps.refresh as refresh_mod
from tools.ms_deps.refresh import run_refresh, _extract_cve_set


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_LOCK_OLD = """\
version = 1
revision = 1
requires-python = ">=3.12"

[[package]]
name = "starlette"
version = "0.36.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "fastapi"
version = "0.110.0"
source = { registry = "https://pypi.org/simple" }
"""

FIXTURE_LOCK_NEW = """\
version = 1
revision = 2
requires-python = ">=3.12"

[[package]]
name = "starlette"
version = "0.40.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "fastapi"
version = "0.115.0"
source = { registry = "https://pypi.org/simple" }
"""

# pip-audit JSON with no vulnerabilities
_AUDIT_CLEAN: dict[str, Any] = {"dependencies": []}

# pip-audit JSON with one CVE (simulates a regression)
_AUDIT_ONE_CVE: dict[str, Any] = {
    "dependencies": [
        {
            "name": "starlette",
            "version": "0.40.0",
            "vulns": [{"id": "CVE-2099-99999", "description": "test vuln"}],
        }
    ]
}

# pip-audit JSON with a CVE already present in baseline (not a regression)
_AUDIT_SAME_CVE: dict[str, Any] = {
    "dependencies": [
        {
            "name": "starlette",
            "version": "0.36.0",
            "vulns": [{"id": "CVE-2099-11111", "description": "baseline vuln"}],
        }
    ]
}


@pytest.fixture()
def lock_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with a uv.lock and requirements.txt."""
    lock_file = tmp_path / "uv.lock"
    lock_file.write_text(FIXTURE_LOCK_OLD)
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("fastapi>=0.110.0\nstarlette>=0.36.0\n")
    return tmp_path


def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _uv_upgrade_side_effect(new_lock_content: str):
    """Return a side_effect callable that writes new_lock_content into cwd/uv.lock.

    _run_uv_lock signature: (uv, *, upgrade, upgrade_package, cwd)
    """

    def _side_effect(uv, *, upgrade, upgrade_package, cwd):
        lock = cwd / "uv.lock"
        lock.write_text(new_lock_content)
        return _make_completed(returncode=0)

    return _side_effect


# ---------------------------------------------------------------------------
# Helper: patch the whole refresh module's subprocess + deps_diff + pip-audit
# ---------------------------------------------------------------------------

def _patch_uv_supports_upgrade(supports: bool = True):
    return mock.patch.object(refresh_mod, "_uv_supports_upgrade_flag", return_value=supports)


def _patch_uv_executable(uv_path: str = "/fake/uv"):
    return mock.patch.object(refresh_mod, "_uv_executable", return_value=uv_path)


def _patch_run_pip_audit(return_value: dict | None):
    return mock.patch.object(refresh_mod, "_run_pip_audit", return_value=return_value)


def _patch_deps_diff(output: str = "| starlette | 0.36.0 | 0.40.0 | minor↑ |"):
    return mock.patch.object(refresh_mod, "_compute_diff", return_value=output)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Lock changes, no new CVEs → exit 0, new lockfile retained."""

    def test_exit_0_on_clean_upgrade(self, lock_dir: Path) -> None:
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff(),
        ):
            exit_code = run_refresh(cwd=lock_dir)

        assert exit_code == 0

    def test_new_lock_retained(self, lock_dir: Path) -> None:
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff(),
        ):
            run_refresh(cwd=lock_dir)

        assert (lock_dir / "uv.lock").read_text() == FIXTURE_LOCK_NEW

    def test_upgrade_flag_used_when_available(self, lock_dir: Path) -> None:
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable("/fake/uv"),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff(),
        ):
            run_refresh(cwd=lock_dir)

        _, kwargs = uv_proc_call.call_args
        assert kwargs.get("upgrade") is True
        assert kwargs.get("upgrade_package") is None


class TestAuditRegression:
    """New CVE introduced → exit 2, lockfile restored to original."""

    def test_exit_2_on_new_cve(self, lock_dir: Path) -> None:
        original_content = (lock_dir / "uv.lock").read_text()
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        # Baseline returns no CVEs; new lock returns one new CVE.
        audit_results = iter([_AUDIT_CLEAN, _AUDIT_ONE_CVE])

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            mock.patch.object(refresh_mod, "_run_pip_audit", side_effect=audit_results),
            _patch_deps_diff(),
        ):
            exit_code = run_refresh(cwd=lock_dir)

        assert exit_code == 2

    def test_lockfile_restored_on_regression(self, lock_dir: Path) -> None:
        original_content = (lock_dir / "uv.lock").read_text()
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        audit_results = iter([_AUDIT_CLEAN, _AUDIT_ONE_CVE])

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            mock.patch.object(refresh_mod, "_run_pip_audit", side_effect=audit_results),
            _patch_deps_diff(),
        ):
            run_refresh(cwd=lock_dir)

        assert (lock_dir / "uv.lock").read_text() == original_content

    def test_existing_cves_not_treated_as_regression(self, lock_dir: Path) -> None:
        """A CVE present in BOTH baseline and new lock is not a regression."""
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))
        # Both audits return the same CVE.
        audit_results = iter([_AUDIT_SAME_CVE, _AUDIT_SAME_CVE])

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            mock.patch.object(refresh_mod, "_run_pip_audit", side_effect=audit_results),
            _patch_deps_diff(),
        ):
            exit_code = run_refresh(cwd=lock_dir)

        assert exit_code == 0


class TestNoChange:
    """uv lock --upgrade produces same lock → exit 0, diff shows no changes."""

    def test_exit_0_when_lock_unchanged(self, lock_dir: Path) -> None:
        # uv lock "upgrades" but the file content stays the same.
        uv_proc_call = mock.MagicMock(
            side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_OLD)
        )

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff("(no changes)"),
        ):
            exit_code = run_refresh(cwd=lock_dir)

        assert exit_code == 0

    def test_lock_content_unchanged(self, lock_dir: Path) -> None:
        original_content = (lock_dir / "uv.lock").read_text()
        uv_proc_call = mock.MagicMock(
            side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_OLD)
        )

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff("(no changes)"),
        ):
            run_refresh(cwd=lock_dir)

        assert (lock_dir / "uv.lock").read_text() == original_content


class TestDryRun:
    """--dry-run: diff shown, lockfile unchanged."""

    def test_exit_0_dry_run(self, lock_dir: Path) -> None:
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff(),
        ):
            exit_code = run_refresh(dry_run=True, cwd=lock_dir)

        assert exit_code == 0

    def test_lockfile_not_modified_in_dry_run(self, lock_dir: Path) -> None:
        original_content = (lock_dir / "uv.lock").read_text()
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff(),
        ):
            run_refresh(dry_run=True, cwd=lock_dir)

        assert (lock_dir / "uv.lock").read_text() == original_content


class TestUpgradePackage:
    """--upgrade-package <name>: subprocess called with correct args."""

    def test_upgrade_package_passed_to_uv(self, lock_dir: Path) -> None:
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable("/fake/uv"),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff(),
        ):
            exit_code = run_refresh(upgrade_package="starlette", cwd=lock_dir)

        assert exit_code == 0
        _, kwargs = uv_proc_call.call_args
        assert kwargs.get("upgrade_package") == "starlette"

    def test_upgrade_package_disables_global_upgrade(self, lock_dir: Path) -> None:
        """When --upgrade-package is specified, the global --upgrade flag is NOT set."""
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable("/fake/uv"),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
            _patch_deps_diff(),
        ):
            run_refresh(upgrade_package="starlette", cwd=lock_dir)

        _, kwargs = uv_proc_call.call_args
        assert kwargs.get("upgrade") is False


class TestFallbackBehavior:
    """Fallback: no --upgrade flag, no pip-audit → graceful degradation."""

    def test_no_upgrade_flag_falls_back_to_plain_lock(self, lock_dir: Path) -> None:
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable("/fake/uv"),
            _patch_uv_supports_upgrade(False),  # uv doesn't support --upgrade
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(None),  # pip-audit unavailable
            _patch_deps_diff(),
        ):
            exit_code = run_refresh(cwd=lock_dir)

        assert exit_code == 0
        _, kwargs = uv_proc_call.call_args
        # upgrade should be False when flag is not supported
        assert kwargs.get("upgrade") is False

    def test_pip_audit_unavailable_does_not_block(self, lock_dir: Path) -> None:
        uv_proc_call = mock.MagicMock(side_effect=_uv_upgrade_side_effect(FIXTURE_LOCK_NEW))

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(None),  # pip-audit unavailable
            _patch_deps_diff(),
        ):
            exit_code = run_refresh(cwd=lock_dir)

        assert exit_code == 0


class TestExtractCveSet:
    """Unit tests for the _extract_cve_set helper."""

    def test_empty_result(self) -> None:
        assert _extract_cve_set({}) == set()

    def test_none_result(self) -> None:
        assert _extract_cve_set(None) == set()

    def test_extracts_ids(self) -> None:
        audit = {
            "dependencies": [
                {"name": "foo", "version": "1.0", "vulns": [{"id": "CVE-2099-1"}, {"id": "CVE-2099-2"}]},
                {"name": "bar", "version": "2.0", "vulns": []},
            ]
        }
        assert _extract_cve_set(audit) == {"CVE-2099-1", "CVE-2099-2"}

    def test_missing_id_skipped(self) -> None:
        audit = {
            "dependencies": [
                {"name": "foo", "version": "1.0", "vulns": [{"description": "no id here"}]},
            ]
        }
        assert _extract_cve_set(audit) == set()


class TestUvLockFailure:
    """uv lock returns non-zero → exit 1, lockfile restored."""

    def test_exit_1_on_uv_failure(self, lock_dir: Path) -> None:
        uv_proc_call = mock.MagicMock(
            return_value=_make_completed(returncode=1, stderr="uv lock failed")
        )

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
        ):
            exit_code = run_refresh(cwd=lock_dir)

        assert exit_code == 1

    def test_lockfile_restored_on_uv_failure(self, lock_dir: Path) -> None:
        original_content = (lock_dir / "uv.lock").read_text()
        uv_proc_call = mock.MagicMock(
            return_value=_make_completed(returncode=1, stderr="uv lock failed")
        )

        with (
            _patch_uv_executable(),
            _patch_uv_supports_upgrade(True),
            mock.patch.object(refresh_mod, "_run_uv_lock", uv_proc_call),
            _patch_run_pip_audit(_AUDIT_CLEAN),
        ):
            run_refresh(cwd=lock_dir)

        assert (lock_dir / "uv.lock").read_text() == original_content
