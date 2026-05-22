"""Tests for tools/check_structural_antipatterns.py rule registry.

Step 1.4.e: positive cases (each anti-pattern detected) and
            negative cases (legitimate file additions don't trigger).
Tests use synthetic file states via monkeypatching so no real FS changes needed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
_TOOL = REPO / "tools" / "check_structural_antipatterns.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("check_structural_antipatterns", str(_TOOL))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def tool():
    return _load_tool()


# ── rule-001: loose ADR file at docs/NNNN-*.md ────────────────────────────

class TestRule001LooseAdr:
    def test_detects_loose_adr_in_audit(self, tool, tmp_path, monkeypatch):
        """Audit mode finds an ADR file loose in docs/."""
        fake_repo = tmp_path
        (fake_repo / "docs").mkdir()
        (fake_repo / "docs" / "adr").mkdir()
        (fake_repo / "docs" / "0099-some-decision.md").write_text("# ADR")
        monkeypatch.setattr(tool, "REPO", fake_repo)
        findings = tool._check_loose_adr(fake_repo, "audit")
        assert len(findings) == 1
        assert "rule-001" in findings[0]
        assert "0099-some-decision.md" in findings[0]

    def test_ignores_adr_in_correct_location(self, tool, tmp_path, monkeypatch):
        """Audit mode ignores ADR files that are correctly under docs/adr/."""
        fake_repo = tmp_path
        (fake_repo / "docs").mkdir()
        (fake_repo / "docs" / "adr").mkdir()
        (fake_repo / "docs" / "adr" / "0001-decision.md").write_text("# ADR")
        monkeypatch.setattr(tool, "REPO", fake_repo)
        findings = tool._check_loose_adr(fake_repo, "audit")
        assert findings == []

    def test_ignores_non_adr_md_in_docs(self, tool, tmp_path, monkeypatch):
        """Audit mode does not flag non-ADR markdown files in docs/."""
        fake_repo = tmp_path
        (fake_repo / "docs").mkdir()
        (fake_repo / "docs" / "GLOSSARY.md").write_text("# Glossary")
        (fake_repo / "docs" / "README.md").write_text("# Readme")
        monkeypatch.setattr(tool, "REPO", fake_repo)
        findings = tool._check_loose_adr(fake_repo, "audit")
        assert findings == []


# ── rule-002: unexcepted tracked data/ subdirectory ───────────────────────

class TestRule002UnexceptedDataDir:
    def _make_gitignore(self, path, exceptions=None):
        lines = ["data/*/"]
        for exc in (exceptions or []):
            lines.append("!data/" + exc + "/")
        (path / ".gitignore").write_text("\n".join(lines) + "\n")

    def test_detects_missing_exception_in_audit(self, tool, tmp_path, monkeypatch):
        """Audit mode finds a tracked data/ subdir without a gitignore exception."""
        import subprocess as sp
        self._make_gitignore(tmp_path, exceptions=["headscale"])
        monkeypatch.setattr(tool, "REPO", tmp_path)

        def fake_run(cmd, **kwargs):
            class FakeResult:
                stdout = "data/newapp/config.yaml\n"
                returncode = 0
            if cmd[:3] == ["git", "ls-files", "data/"]:
                return FakeResult()
            return sp.run(cmd, **kwargs)

        monkeypatch.setattr(tool.subprocess, "run", fake_run)
        findings = tool._check_unignored_data_dir(tmp_path, "audit")
        assert any("rule-002" in f and "newapp" in f for f in findings)

    def test_no_finding_when_exception_exists(self, tool, tmp_path, monkeypatch):
        """Audit mode is silent when all tracked data/ subdirs have exceptions."""
        self._make_gitignore(tmp_path, exceptions=["headscale", "tailscale"])
        monkeypatch.setattr(tool, "REPO", tmp_path)

        import subprocess as sp
        def fake_run(cmd, **kwargs):
            class FakeResult:
                stdout = "data/headscale/config.yaml\ndata/tailscale/state\n"
                returncode = 0
            if cmd[:3] == ["git", "ls-files", "data/"]:
                return FakeResult()
            return sp.run(cmd, **kwargs)

        monkeypatch.setattr(tool.subprocess, "run", fake_run)
        findings = tool._check_unignored_data_dir(tmp_path, "audit")
        assert findings == []


# ── rule-003: canonical doc at repo root ──────────────────────────────────

class TestRule003CanonicalDocAtRoot:
    def test_detects_core_rules_at_root_in_audit(self, tool, tmp_path, monkeypatch):
        """Audit mode finds CORE_RULES.md at repo root."""
        (tmp_path / "CORE_RULES.md").write_text("# rules")
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_canonical_doc_at_root(tmp_path, "audit")
        assert any("rule-003" in f and "CORE_RULES.md" in f for f in findings)

    def test_detects_project_cleanup_at_root_in_audit(self, tool, tmp_path, monkeypatch):
        """Audit mode finds PROJECT_CLEANUP.md at repo root."""
        (tmp_path / "PROJECT_CLEANUP.md").write_text("# cleanup")
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_canonical_doc_at_root(tmp_path, "audit")
        assert any("rule-003" in f and "PROJECT_CLEANUP.md" in f for f in findings)

    def test_clean_when_no_canonical_doc_at_root(self, tool, tmp_path, monkeypatch):
        """Audit mode is silent when canonical docs are not at repo root."""
        (tmp_path / "README.md").write_text("# readme")
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_canonical_doc_at_root(tmp_path, "audit")
        assert findings == []


# ── rule-005: installer hardcoded paths ───────────────────────────────────

class TestRule005InstallerHardcodedPaths:
    def test_detects_hardcoded_opt_mediastack(self, tool, tmp_path, monkeypatch):
        """Audit mode finds an installer/ file that hardcodes /opt/mediastack."""
        installer_dir = tmp_path / "installer"
        installer_dir.mkdir()
        (installer_dir / "install.py").write_text(
            "INSTALL_DIR = '/opt/mediastack'\n"
        )
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_installer_hardcoded_paths(tmp_path, "audit")
        assert len(findings) == 1
        assert "rule-005" in findings[0]
        assert "/opt/mediastack" in findings[0]

    def test_detects_hardcoded_var_lib_mediastack(self, tool, tmp_path, monkeypatch):
        """Audit mode finds an installer/ file that hardcodes /var/lib/mediastack."""
        installer_dir = tmp_path / "installer"
        installer_dir.mkdir()
        (installer_dir / "state.py").write_text(
            "DATA_DIR = '/var/lib/mediastack'\n"
        )
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_installer_hardcoded_paths(tmp_path, "audit")
        assert len(findings) == 1
        assert "rule-005" in findings[0]
        assert "/var/lib/mediastack" in findings[0]

    def test_ignores_test_fixtures(self, tool, tmp_path, monkeypatch):
        """Audit mode does not flag installer/tests/ files with the literal paths."""
        installer_dir = tmp_path / "installer"
        tests_dir = installer_dir / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_install.py").write_text(
            "EXPECTED_PATH = '/opt/mediastack'\n"
            "EXPECTED_DATA = '/var/lib/mediastack'\n"
        )
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_installer_hardcoded_paths(tmp_path, "audit")
        assert findings == []

    def test_clean_when_no_hardcoded_paths(self, tool, tmp_path, monkeypatch):
        """Audit mode is silent when installer/ files read paths from config."""
        installer_dir = tmp_path / "installer"
        installer_dir.mkdir()
        (installer_dir / "install.py").write_text(
            "from installer.config import DEFAULT_INSTALL_DIR\n"
            "install_dir = args.install_dir or DEFAULT_INSTALL_DIR\n"
        )
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_installer_hardcoded_paths(tmp_path, "audit")
        assert findings == []

    def test_clean_when_no_installer_dir(self, tool, tmp_path, monkeypatch):
        """Audit mode is silent when installer/ does not exist yet."""
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_installer_hardcoded_paths(tmp_path, "audit")
        assert findings == []


# ── run_checks: integration ────────────────────────────────────────────────

class TestRunChecksAuditClean:
    def test_current_repo_is_clean(self, tool):
        """The current repository has no structural anti-pattern violations.

        rule-004 (root-owned pytest scratch) is excluded: it checks mutable
        filesystem state that other tests in the same run may create. That
        check runs via pre-commit hook and ms-update --audit instead.
        """
        findings = tool.run_checks("audit", exclude=["rule-004"])
        assert findings == [], (
            "Structural anti-pattern violations found in repo:\n"
            + "\n".join("  " + f for f in findings)
        )

# ── rule-004: root-owned files in pytest scratch dir ──────────────────────

class TestRule004RootOwnedPytestScratch:
    def test_detects_root_owned_entry(self, tool, tmp_path, monkeypatch):
        """Audit mode detects a root-owned (uid=0) entry via _get_entry_uid."""
        fake_base = tmp_path / "pytest-base"
        fake_base.mkdir()
        (fake_base / "test_compose_failure0").mkdir()

        monkeypatch.setattr(tool, "_PYTEST_BASE", fake_base)
        monkeypatch.setattr(tool, "_get_entry_uid", lambda entry: 0)

        findings = tool._check_root_owned_pytest_scratch(tool.REPO, "audit")
        assert any("rule-004" in f for f in findings)

    def test_clean_when_no_root_owned_entries(self, tool, tmp_path, monkeypatch):
        """Audit mode is silent when all entries are owned by current user."""
        import os
        fake_base = tmp_path / "pytest-base"
        fake_base.mkdir()
        (fake_base / "test_normal0").mkdir()

        monkeypatch.setattr(tool, "_PYTEST_BASE", fake_base)
        monkeypatch.setattr(tool, "_get_entry_uid", lambda entry: os.getuid())

        findings = tool._check_root_owned_pytest_scratch(tool.REPO, "audit")
        assert findings == []


# ── rule-006: bare subprocess.run in installer/ ───────────────────────────────


class TestRule006InstallerBareSubprocess:
    def test_detects_bare_subprocess_run_in_installer(self, tool, tmp_path, monkeypatch):
        """Audit mode finds an installer/ file that calls subprocess.run() directly."""
        installer_dir = tmp_path / "installer"
        installer_dir.mkdir()
        (installer_dir / "mymodule.py").write_text(
            "import subprocess\n"
            "result = subprocess.run(['ls'], capture_output=True)\n"
        )
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_bare_subprocess_run_in_installer(tmp_path, "audit")
        assert len(findings) == 1
        assert "rule-006" in findings[0]

    def test_ignores_run_py(self, tool, tmp_path, monkeypatch):
        """Audit mode does not flag installer/_run.py (the allowed home)."""
        installer_dir = tmp_path / "installer"
        installer_dir.mkdir()
        (installer_dir / "_run.py").write_text(
            "import subprocess\n"
            "result = subprocess.run(cmd, capture_output=True)\n"
        )
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_bare_subprocess_run_in_installer(tmp_path, "audit")
        assert findings == []

    def test_ignores_tests_dir(self, tool, tmp_path, monkeypatch):
        """Audit mode does not flag installer/tests/ files."""
        installer_dir = tmp_path / "installer"
        tests_dir = installer_dir / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_x.py").write_text(
            "with patch('installer._run.subprocess.run', side_effect=...): pass\n"
        )
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_bare_subprocess_run_in_installer(tmp_path, "audit")
        assert findings == []

    def test_clean_when_uses_run_required(self, tool, tmp_path, monkeypatch):
        """Audit mode is silent when installer/ uses run_required()."""
        installer_dir = tmp_path / "installer"
        installer_dir.mkdir()
        (installer_dir / "mymodule.py").write_text(
            "from installer._run import run_required\n"
            "result = run_required(['ls'])\n"
        )
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_bare_subprocess_run_in_installer(tmp_path, "audit")
        assert findings == []

    def test_clean_when_no_installer_dir(self, tool, tmp_path, monkeypatch):
        """Audit mode is silent when installer/ does not exist."""
        monkeypatch.setattr(tool, "REPO", tmp_path)
        findings = tool._check_bare_subprocess_run_in_installer(tmp_path, "audit")
        assert findings == []
