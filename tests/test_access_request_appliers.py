"""Tests for tools.access_request_appliers.

All tests use tmp_path (pytest fixture) for target files.
Subprocess calls are mocked — no live pip/uv invocations.
No live settings/requirements files are touched.

Wave: S-59-B
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.access_request_appliers import (
    APPLIERS,
    UPGRADE_PACKAGE_FLAG,
    apply_allow,
    apply_deny,
    apply_install,
    apply_upgrade,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path, *, allow: list[str] | None = None, deny: list[str] | None = None) -> Path:
    """Write a minimal settings.local.json to tmp_path and return the path."""
    settings_path = tmp_path / "settings.local.json"
    data: dict = {
        "permissions": {
            "allow": allow or [],
            "deny": deny or [],
        }
    }
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return settings_path


def _read_settings(settings_path: Path) -> dict:
    return json.loads(settings_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# apply_allow
# ---------------------------------------------------------------------------


class TestApplyAllow:
    def test_adds_entry_to_empty_allow_list(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path)
        result = apply_allow("WebFetch(domain:example.com)", settings_path=settings_path)
        assert result["added"] is True
        assert result["already_present"] is False
        data = _read_settings(settings_path)
        assert "WebFetch(domain:example.com)" in data["permissions"]["allow"]

    def test_idempotent_no_duplicate_on_rerun(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path, allow=["WebFetch(domain:example.com)"])
        result = apply_allow("WebFetch(domain:example.com)", settings_path=settings_path)
        assert result["added"] is False
        assert result["already_present"] is True
        data = _read_settings(settings_path)
        assert data["permissions"]["allow"].count("WebFetch(domain:example.com)") == 1

    def test_dry_run_makes_no_change(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path)
        result = apply_allow("WebFetch(domain:example.com)", settings_path=settings_path, dry_run=True)
        assert result["dry_run"] is True
        assert result["added"] is False
        data = _read_settings(settings_path)
        assert "WebFetch(domain:example.com)" not in data["permissions"]["allow"]

    def test_creates_file_if_absent(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.local.json"
        assert not settings_path.exists()
        result = apply_allow("Bash(ls *)", settings_path=settings_path)
        assert result["added"] is True
        data = _read_settings(settings_path)
        assert "Bash(ls *)" in data["permissions"]["allow"]

    def test_lifts_and_restores_self_edit_deny(self, tmp_path: Path) -> None:
        """Verify the lift-restore pattern: self-edit deny is put back after edit."""
        settings_path = tmp_path / "settings.local.json"
        self_edit_deny = f"Edit({settings_path})"
        settings_path.write_text(
            json.dumps({
                "permissions": {
                    "allow": [],
                    "deny": [self_edit_deny],
                }
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        apply_allow("Bash(grep *)", settings_path=settings_path)
        data = _read_settings(settings_path)
        # deny must be restored
        assert self_edit_deny in data["permissions"]["deny"]
        # allow must contain new entry
        assert "Bash(grep *)" in data["permissions"]["allow"]

    def test_multiple_entries_accumulate(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path)
        apply_allow("WebFetch(domain:alpha.com)", settings_path=settings_path)
        apply_allow("WebFetch(domain:beta.com)", settings_path=settings_path)
        data = _read_settings(settings_path)
        assert "WebFetch(domain:alpha.com)" in data["permissions"]["allow"]
        assert "WebFetch(domain:beta.com)" in data["permissions"]["allow"]


# ---------------------------------------------------------------------------
# apply_deny
# ---------------------------------------------------------------------------


class TestApplyDeny:
    def test_raises_without_explicit_flag(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path)
        with pytest.raises(ValueError, match="allow_deny_additions=True"):
            apply_deny("Bash(rm -rf /)", settings_path=settings_path)

    def test_adds_entry_with_flag(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path)
        result = apply_deny(
            "Bash(rm -rf /)",
            settings_path=settings_path,
            allow_deny_additions=True,
        )
        assert result["added"] is True
        data = _read_settings(settings_path)
        assert "Bash(rm -rf /)" in data["permissions"]["deny"]

    def test_idempotent_no_duplicate(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path, deny=["Bash(rm -rf /)"])
        result = apply_deny(
            "Bash(rm -rf /)",
            settings_path=settings_path,
            allow_deny_additions=True,
        )
        assert result["added"] is False
        assert result["already_present"] is True
        data = _read_settings(settings_path)
        assert data["permissions"]["deny"].count("Bash(rm -rf /)") == 1

    def test_dry_run_makes_no_change(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path)
        result = apply_deny(
            "Bash(rm -rf /)",
            settings_path=settings_path,
            allow_deny_additions=True,
            dry_run=True,
        )
        assert result["dry_run"] is True
        assert result["added"] is False
        data = _read_settings(settings_path)
        assert "Bash(rm -rf /)" not in data["permissions"]["deny"]

    def test_lifts_and_restores_self_edit_deny(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.local.json"
        self_edit_deny = f"Edit({settings_path})"
        settings_path.write_text(
            json.dumps({
                "permissions": {
                    "allow": [],
                    "deny": [self_edit_deny],
                }
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        apply_deny(
            "Bash(curl *)",
            settings_path=settings_path,
            allow_deny_additions=True,
        )
        data = _read_settings(settings_path)
        assert self_edit_deny in data["permissions"]["deny"]
        assert "Bash(curl *)" in data["permissions"]["deny"]


# ---------------------------------------------------------------------------
# apply_install
# ---------------------------------------------------------------------------


class TestApplyInstall:
    def _mock_uv_success(self) -> MagicMock:
        """Return a mock CompletedProcess with returncode=0."""
        mock = MagicMock()
        mock.returncode = 0
        mock.stderr = ""
        return mock

    def test_appends_when_pkg_absent(self, tmp_path: Path) -> None:
        req_path = tmp_path / "requirements-dev.txt"
        req_path.write_text("pytest>=9\n", encoding="utf-8")

        with patch("subprocess.run", return_value=self._mock_uv_success()) as mock_run:
            result = apply_install(
                "pip-audit>=2.7.0",
                requirements_path=req_path,
            )

        assert result["appended"] is True
        assert result["installed"] is True
        assert result["already_constrained"] is False
        content = req_path.read_text(encoding="utf-8")
        assert "pip-audit>=2.7.0" in content
        mock_run.assert_called_once()

    def test_no_op_when_constraint_satisfied(self, tmp_path: Path) -> None:
        req_path = tmp_path / "requirements-dev.txt"
        req_path.write_text("pip-audit>=2.7.0\n", encoding="utf-8")

        with patch("subprocess.run", return_value=self._mock_uv_success()) as mock_run:
            result = apply_install(
                "pip-audit>=2.7.0",
                requirements_path=req_path,
            )

        assert result["appended"] is False
        assert result["already_constrained"] is True
        assert result["installed"] is True
        # File content should not be changed
        content = req_path.read_text(encoding="utf-8")
        assert content.count("pip-audit") == 1
        mock_run.assert_called_once()

    def test_case_insensitive_name_match(self, tmp_path: Path) -> None:
        req_path = tmp_path / "requirements-dev.txt"
        req_path.write_text("Pip-Audit>=2.7.0\n", encoding="utf-8")

        with patch("subprocess.run", return_value=self._mock_uv_success()):
            result = apply_install("pip-audit>=2.7.0", requirements_path=req_path)

        assert result["already_constrained"] is True
        assert result["appended"] is False

    def test_dry_run_makes_no_change(self, tmp_path: Path) -> None:
        req_path = tmp_path / "requirements-dev.txt"
        req_path.write_text("pytest>=9\n", encoding="utf-8")

        with patch("subprocess.run") as mock_run:
            result = apply_install(
                "pip-audit>=2.7.0",
                requirements_path=req_path,
                dry_run=True,
            )

        assert result["dry_run"] is True
        assert result["appended"] is False
        assert result["installed"] is False
        content = req_path.read_text(encoding="utf-8")
        assert "pip-audit" not in content
        mock_run.assert_not_called()

    def test_subprocess_failure_raises(self, tmp_path: Path) -> None:
        req_path = tmp_path / "requirements-dev.txt"
        req_path.write_text("", encoding="utf-8")

        mock_fail = MagicMock()
        mock_fail.returncode = 1
        mock_fail.stderr = "ERROR: some pip error"

        with patch("subprocess.run", return_value=mock_fail):
            with pytest.raises(RuntimeError, match="uv pip install failed"):
                apply_install("nonexistent-pkg", requirements_path=req_path)

    def test_pkg_found_in_extra_req_paths_no_append(self, tmp_path: Path) -> None:
        """Package in requirements.txt → not appended to requirements-dev.txt."""
        main_req = tmp_path / "requirements.txt"
        main_req.write_text("pip-audit>=2.7.0\n", encoding="utf-8")
        dev_req = tmp_path / "requirements-dev.txt"
        dev_req.write_text("pytest>=9\n", encoding="utf-8")

        with patch("subprocess.run", return_value=self._mock_uv_success()):
            result = apply_install(
                "pip-audit",
                requirements_path=dev_req,
                extra_req_paths=[main_req],
            )

        assert result["already_constrained"] is True
        assert result["appended"] is False
        # dev requirements should not have pip-audit added
        assert "pip-audit" not in dev_req.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# apply_upgrade
# ---------------------------------------------------------------------------


class TestApplyUpgrade:
    def test_writes_request_marker(self, tmp_path: Path) -> None:
        req_file = tmp_path / "upgrade-requests.txt"
        result = apply_upgrade("starlette", upgrade_requests_path=req_file)
        assert result["appended"] is True
        assert result["already_requested"] is False
        content = req_file.read_text(encoding="utf-8")
        assert f"{UPGRADE_PACKAGE_FLAG} starlette" in content

    def test_idempotent_no_duplicate(self, tmp_path: Path) -> None:
        req_file = tmp_path / "upgrade-requests.txt"
        req_file.write_text(f"{UPGRADE_PACKAGE_FLAG} starlette\n", encoding="utf-8")
        result = apply_upgrade("starlette", upgrade_requests_path=req_file)
        assert result["already_requested"] is True
        assert result["appended"] is False
        lines = req_file.read_text(encoding="utf-8").splitlines()
        matching = [l for l in lines if f"{UPGRADE_PACKAGE_FLAG} starlette" in l]
        assert len(matching) == 1

    def test_dry_run_makes_no_change(self, tmp_path: Path) -> None:
        req_file = tmp_path / "upgrade-requests.txt"
        result = apply_upgrade("starlette", upgrade_requests_path=req_file, dry_run=True)
        assert result["dry_run"] is True
        assert result["appended"] is False
        assert not req_file.exists()

    def test_creates_file_if_absent(self, tmp_path: Path) -> None:
        req_file = tmp_path / "upgrade-requests.txt"
        assert not req_file.exists()
        apply_upgrade("httpx", upgrade_requests_path=req_file)
        assert req_file.exists()
        assert f"{UPGRADE_PACKAGE_FLAG} httpx" in req_file.read_text(encoding="utf-8")

    def test_multiple_packages_accumulate(self, tmp_path: Path) -> None:
        req_file = tmp_path / "upgrade-requests.txt"
        apply_upgrade("starlette", upgrade_requests_path=req_file)
        apply_upgrade("fastapi", upgrade_requests_path=req_file)
        content = req_file.read_text(encoding="utf-8")
        assert f"{UPGRADE_PACKAGE_FLAG} starlette" in content
        assert f"{UPGRADE_PACKAGE_FLAG} fastapi" in content

    def test_strips_version_specifier_from_pkg_name(self, tmp_path: Path) -> None:
        req_file = tmp_path / "upgrade-requests.txt"
        result = apply_upgrade("starlette>=1.0.0", upgrade_requests_path=req_file)
        content = req_file.read_text(encoding="utf-8")
        # Should store bare name only
        assert f"{UPGRADE_PACKAGE_FLAG} starlette" in content
        assert result["package"] == "starlette"

    def test_does_not_execute_actual_upgrade(self, tmp_path: Path) -> None:
        """apply_upgrade must never call subprocess; only writes a marker file."""
        req_file = tmp_path / "upgrade-requests.txt"
        with patch("subprocess.run") as mock_run:
            apply_upgrade("starlette", upgrade_requests_path=req_file)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Regression: adapters must pass the subject STRING, not the parsed entry dict
# (/doctor 2026-05-29 found a dict in permissions.deny — S-59 A<->B gap residual)
# ---------------------------------------------------------------------------


class TestAdapterPassesString:
    def _entry(self, category: str, subject: str) -> dict:
        return {
            "category": category,
            "status": "pending",
            "subject": subject,
            "raw_line": f"- `[ ]` **[{category}] {subject}** — x",
            "date": "2026-05-29",
            "source": "TEST",
            "line_index": 0,
        }

    def test_deny_adapter_passes_subject_string_not_dict(self) -> None:
        # The adapter must pass the subject STRING to apply_deny, never the dict.
        entry = self._entry("deny", "Bash(rm -rf *)")
        with patch("tools.access_request_appliers.apply_deny") as m:
            m.return_value = {"action": "added"}
            result = APPLIERS["deny"](entry, dry_run=False, target_paths=None)
        assert result["ok"] is True, result
        args, kwargs = m.call_args
        passed = args[0] if args else kwargs.get("entry")
        assert isinstance(passed, str), f"adapter passed {type(passed).__name__}: {passed!r}"
        assert passed == "Bash(rm -rf *)"

    def test_allow_adapter_passes_subject_string_not_dict(self) -> None:
        # Backtick-wrapped subject (the common allow form) must be unwrapped to the pattern.
        entry = self._entry("allow", "`WebFetch(domain:example.com)`")
        with patch("tools.access_request_appliers.apply_allow") as m:
            m.return_value = {"action": "added"}
            result = APPLIERS["allow"](entry, dry_run=False, target_paths=None)
        assert result["ok"] is True, result
        args, kwargs = m.call_args
        passed = args[0] if args else kwargs.get("entry")
        assert isinstance(passed, str), f"adapter passed {type(passed).__name__}: {passed!r}"
        assert passed == "WebFetch(domain:example.com)"

    def test_apply_deny_rejects_dict(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path)
        with pytest.raises(TypeError):
            apply_deny({"subject": "Bash(rm -rf *)"}, settings_path=settings_path,
                       allow_deny_additions=True)

    def test_apply_allow_rejects_dict(self, tmp_path: Path) -> None:
        settings_path = _make_settings(tmp_path)
        with pytest.raises(TypeError):
            apply_allow({"subject": "Bash(ls *)"}, settings_path=settings_path)


# ---------------------------------------------------------------------------
# Regression: adapters must honor target_paths["settings_local"] and never
# write the REAL settings file during a test run (batch-6 /doctor finding —
# a [deny] Bash(rm -rf *) fixture polluted the live settings via the default path)
# ---------------------------------------------------------------------------


class TestAdapterHonorsTargetPath:
    def _entry(self, category: str, subject: str) -> dict:
        return {"category": category, "status": "pending", "subject": subject,
                "raw_line": f"- `[ ]` **[{category}] {subject}**", "date": "2026-05-29",
                "source": "TEST", "line_index": 0}

    def test_deny_adapter_writes_to_target_path_not_default(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.local.json"
        target.write_text(json.dumps({"permissions": {"allow": [], "deny": []}}) + "\n")
        res = APPLIERS["deny"](self._entry("deny", "Bash(rm -rf *)"),
                               dry_run=False,
                               target_paths={"settings_local": target})
        assert res["ok"] is True, res
        # the supplied tmp file got the rule (as a STRING) ...
        data = json.loads(target.read_text())
        assert "Bash(rm -rf *)" in data["permissions"]["deny"]
        assert all(isinstance(v, str) for v in data["permissions"]["deny"])

    def test_allow_adapter_writes_to_target_path(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.local.json"
        target.write_text(json.dumps({"permissions": {"allow": [], "deny": []}}) + "\n")
        res = APPLIERS["allow"](self._entry("allow", "`WebFetch(domain:example.com)`"),
                                dry_run=False,
                                target_paths={"settings_local": target})
        assert res["ok"] is True, res
        data = json.loads(target.read_text())
        assert "WebFetch(domain:example.com)" in data["permissions"]["allow"]
