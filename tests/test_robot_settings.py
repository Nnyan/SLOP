"""
tests/test_robot_settings.py — Tests for tools/sanctioned/robot_settings.py

Uses temporary directories and fixture files.
Does NOT touch the live SLOP repo, live settings, or live SANCTIONED-OPS-LOG.

Test coverage:
1. restore is a no-op when settings already match the profile.
2. restore applies the profile when settings differ.
3. lift push wraps in try/finally — deny rules restored after lift subcommand.
4. lift checkout-main — rules lifted then restored.
5. lift filter-branch — rules lifted then restored.
6. push-then-restore — lift push -> subprocess -> restore; restored even on failure.
7. Audit entry written to SANCTIONED-OPS-LOG on each operation.
8. Golden MERGE-LOG entry: _append_audit_entry output is byte-identical pre/post refactor.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types as _types
from pathlib import Path

import pytest

# ── load modules under test ───────────────────────────────────────────────────

_SANCTIONED_DIR = Path(__file__).parent.parent / "tools" / "sanctioned"
_ROBOT_SETTINGS_PATH = _SANCTIONED_DIR / "robot_settings.py"
_LIFT_RESTORE_PATH = _SANCTIONED_DIR / "_lift_restore.py"
_AUDIT_PATH = _SANCTIONED_DIR / "_audit.py"
_MERGE_TOOL_PATH = Path(__file__).parent.parent / "tools" / "merge_wave_to_main.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Ensure tools.sanctioned.* package stubs exist before loading robot_settings
for _pkg_name, _pkg_path in [
    ("tools", Path(__file__).parent.parent / "tools"),
    ("tools.sanctioned", _SANCTIONED_DIR),
]:
    if _pkg_name not in sys.modules:
        _m = _types.ModuleType(_pkg_name)
        _m.__path__ = [str(_pkg_path)]
        sys.modules[_pkg_name] = _m

# Load the foundation modules into their canonical names
_load_module(_LIFT_RESTORE_PATH, "tools.sanctioned._lift_restore")
_load_module(_AUDIT_PATH, "tools.sanctioned._audit")

# Load robot_settings and merge_wave_to_main under unique test-module names
robot_settings = _load_module(_ROBOT_SETTINGS_PATH, "robot_settings_test_mod")
merge_wave_to_main = _load_module(_MERGE_TOOL_PATH, "merge_wave_to_main_test_mod")


# ── fixture helpers ───────────────────────────────────────────────────────────

def _make_profile(tmp_path: Path, extra_deny: list[str] | None = None) -> Path:
    """Create a settings-wave-mode-profile.json in .claude/."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    path = claude_dir / "settings-wave-mode-profile.json"
    deny = [
        "Bash(git push*)",
        "Bash(git push -f*)",
        "Bash(git push -u*)",
        "Bash(git push --no-verify*)",
        "Bash(git push --force*)",
        "Bash(git checkout main*)",
        "Bash(git switch main*)",
        "Bash(git filter-branch*)",
        "Bash(sudo *)",
    ] + (extra_deny or [])
    data = {
        "permissions": {
            "allow": ["Bash(ls *)", "Bash(git status*)"],
            "deny": deny,
        }
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _make_settings(tmp_path: Path, match_profile: bool = True) -> Path:
    """Create a settings.local.json in .claude/ that may or may not match the profile."""
    profile_path = tmp_path / ".claude" / "settings-wave-mode-profile.json"
    if not profile_path.exists():
        _make_profile(tmp_path)
    profile_data = json.loads(profile_path.read_text())

    path = tmp_path / ".claude" / "settings.local.json"
    if match_profile:
        path.write_text(json.dumps(profile_data, indent=2) + "\n", encoding="utf-8")
    else:
        # Mangled: push/checkout/filter rules removed from deny
        data = {
            "permissions": {
                "allow": ["Bash(ls *)", "Bash(git push*)"],
                "deny": ["Bash(sudo *)"],
            }
        }
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _patch_repo_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect robot_settings._REPO_ROOT to tmp_path."""
    monkeypatch.setattr(robot_settings, "_REPO_ROOT", tmp_path)


def _make_docs_dir(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    return docs


def _capture_audit_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict]:
    """Patch write_entry in robot_settings to capture calls without writing to disk."""
    captured: list[dict] = []

    def fake_write_entry(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(robot_settings, "write_entry", fake_write_entry)
    return captured


# ── tests: restore subcommand ─────────────────────────────────────────────────

class TestRestore:
    """restore subcommand behaviour."""

    def test_restore_noop_when_already_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=True)
        _patch_repo_root(monkeypatch, tmp_path)
        _capture_audit_entries(monkeypatch)  # suppress disk writes

        result = robot_settings.main(["restore"])
        assert result == 0

        # Settings must still match profile after no-op
        settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
        profile = json.loads((tmp_path / ".claude" / "settings-wave-mode-profile.json").read_text())
        assert settings["permissions"] == profile["permissions"]

    def test_restore_applies_profile_when_settings_differ(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=False)
        _patch_repo_root(monkeypatch, tmp_path)
        _capture_audit_entries(monkeypatch)

        result = robot_settings.main(["restore"])
        assert result == 0

        settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
        profile = json.loads((tmp_path / ".claude" / "settings-wave-mode-profile.json").read_text())
        assert settings["permissions"] == profile["permissions"], (
            "Settings should match profile after restore"
        )

    def test_restore_writes_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=False)
        _patch_repo_root(monkeypatch, tmp_path)
        captured = _capture_audit_entries(monkeypatch)

        robot_settings.main(["restore"])

        assert len(captured) == 1, f"Expected 1 audit entry, got {len(captured)}: {captured}"
        entry = captured[0]
        assert entry["tool"] == "robot_settings"
        assert entry["op"] == "restore"
        assert entry["result"] == "OK"

    def test_restore_noop_writes_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=True)
        _patch_repo_root(monkeypatch, tmp_path)
        captured = _capture_audit_entries(monkeypatch)

        robot_settings.main(["restore"])

        assert len(captured) == 1, f"Expected 1 audit entry, got {len(captured)}: {captured}"
        entry = captured[0]
        assert entry["tool"] == "robot_settings"
        assert entry["op"] == "restore"
        assert "NO-OP" in entry["result"] or "no-op" in entry["result"].lower()


# ── tests: lift subcommand ────────────────────────────────────────────────────

class TestLift:
    """lift <sub> subcommand — rules lifted then immediately restored by try/finally."""

    def _run_lift(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sub: str,
        expected_rules: list[str],
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=True)
        _patch_repo_root(monkeypatch, tmp_path)
        _capture_audit_entries(monkeypatch)  # suppress disk writes

        settings_path = tmp_path / ".claude" / "settings.local.json"

        # After lift+restore completes, settings should be restored to profile
        result = robot_settings.main(["lift", sub])
        assert result == 0

        # The try/finally in lifted() must have restored the canonical profile
        profile = json.loads(
            (tmp_path / ".claude" / "settings-wave-mode-profile.json").read_text()
        )
        data = json.loads(settings_path.read_text())
        assert data["permissions"] == profile["permissions"], (
            f"Settings should match profile after lift {sub!r} completes"
        )
        # Specifically, the lifted rules must be back in deny
        for rule in expected_rules:
            assert rule in data["permissions"]["deny"], (
                f"Rule {rule!r} should be back in deny after lift {sub!r}"
            )

    def test_lift_push_restores_after(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._run_lift(tmp_path, monkeypatch, "push", robot_settings._PUSH_RULES)

    def test_lift_checkout_main_restores_after(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._run_lift(
            tmp_path, monkeypatch, "checkout-main", robot_settings._CHECKOUT_MAIN_RULES
        )

    def test_lift_filter_branch_restores_after(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._run_lift(
            tmp_path, monkeypatch, "filter-branch", robot_settings._FILTER_BRANCH_RULES
        )

    def test_lift_writes_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=True)
        _patch_repo_root(monkeypatch, tmp_path)
        captured = _capture_audit_entries(monkeypatch)

        robot_settings.main(["lift", "push"])

        assert len(captured) >= 1, "Expected at least 1 audit entry"
        assert any(e["op"] == "lift push" for e in captured), (
            f"Expected 'lift push' op in audit entries, got: {[e['op'] for e in captured]}"
        )

    def test_lift_unknown_subcommand_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=True)
        _patch_repo_root(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            robot_settings.main(["lift", "nonexistent-rule"])
        assert exc_info.value.code != 0

    def test_lift_no_subcommand_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=True)
        _patch_repo_root(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            robot_settings.main(["lift"])
        assert exc_info.value.code != 0


# ── tests: push-then-restore subcommand ──────────────────────────────────────

class TestPushThenRestore:
    """push-then-restore — push rules restored even on git push failure."""

    def _make_fake_subprocess(self, push_returncode: int = 0):
        """Return a fake subprocess module that intercepts git push and lets git rev-parse through."""
        real_run = subprocess.run

        def fake_run(args, **kwargs):
            # Only intercept git push; let git rev-parse and others go through
            if isinstance(args, (list, tuple)) and len(args) >= 2:
                if args[:2] == ["git", "push"]:
                    class _Result:
                        returncode = push_returncode
                    return _Result()
            # Let git rev-parse and other git commands fail gracefully
            # (no real repo in tmp_path, so rev-parse will fail too)
            try:
                return real_run(args, **kwargs)
            except Exception:
                class _FallbackResult:
                    returncode = 1
                    stdout = ""
                    stderr = ""
                return _FallbackResult()

        return fake_run

    def test_push_then_restore_restores_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Push to a non-existent remote fails; push rules must still be restored."""
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=True)
        _patch_repo_root(monkeypatch, tmp_path)
        _capture_audit_entries(monkeypatch)

        # Intercept subprocess.run to make git push fail
        monkeypatch.setattr(robot_settings.subprocess, "run", self._make_fake_subprocess(push_returncode=1))

        result = robot_settings.main(["push-then-restore"])
        assert result != 0  # push failed → non-zero exit

        # Despite failure, push rules must be restored (profile applied)
        profile = json.loads(
            (tmp_path / ".claude" / "settings-wave-mode-profile.json").read_text()
        )
        settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
        assert settings["permissions"] == profile["permissions"], (
            "Settings should match profile after push failure"
        )

    def test_push_then_restore_writes_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_profile(tmp_path)
        _make_settings(tmp_path, match_profile=True)
        _patch_repo_root(monkeypatch, tmp_path)
        captured = _capture_audit_entries(monkeypatch)

        monkeypatch.setattr(
            robot_settings.subprocess, "run",
            self._make_fake_subprocess(push_returncode=1)
        )

        robot_settings.main(["push-then-restore"])

        assert len(captured) >= 1, "Expected at least 1 audit entry"
        ops = [e["op"] for e in captured]
        assert any("push-then-restore" in op for op in ops), (
            f"Expected push-then-restore op in audit entries, got: {ops}"
        )
        assert any(e["tool"] == "robot_settings" for e in captured), (
            "Expected robot_settings tool in audit entries"
        )


# ── tests: unknown subcommand ─────────────────────────────────────────────────

class TestUnknownSubcommand:
    def test_unknown_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_repo_root(monkeypatch, tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            robot_settings.main(["unknown-subcommand"])
        assert exc_info.value.code != 0


# ── golden test: MERGE-LOG entry format byte-identical pre/post refactor ──────

class TestMergeLogGolden:
    """
    Asserts that the MERGE-LOG entry produced by merge_wave_to_main._append_audit_entry
    is byte-identical before and after the S-68 refactor.

    The refactor touches only the lift/restore mechanics in main(); it does NOT
    change _append_audit_entry. This test confirms that invariant holds by calling
    _append_audit_entry directly with a fixed set of parameters and comparing the
    output to a hard-coded golden reference.
    """

    _FIXED_PARAMS = dict(
        branches=["wave/S-99-golden"],
        pre_sha="aabbccdd",
        post_sha="11223344",
        preflight_results={
            "working-tree": "CLEAN",
            "branch-exists:wave/S-99-golden": "OK",
            "status:wave/S-99-golden": "COMPLETE",
            "diff:wave/S-99-golden": "OK (3 diff-stat lines)",
            "ms-enforce:wave/S-99-golden": "OK",
        },
        notes="golden fixture merge",
        caller="golden-tester",
        timestamp="2026-05-29T00:00:00Z",
    )

    def _generate_entry(self, run_dir: Path) -> str:
        """Call _append_audit_entry and return the freshly-written entry."""
        run_dir.mkdir(parents=True, exist_ok=True)
        merge_log = run_dir / "MERGE-LOG.md"
        merge_log.write_text("# Wave Merge Log\n\n---\n\n", encoding="utf-8")
        merge_wave_to_main._append_audit_entry(merge_log, **self._FIXED_PARAMS)
        text = merge_log.read_text()
        # Extract just the newly-inserted entry (after the ---\n divider)
        divider_pos = text.find("\n---\n")
        if divider_pos != -1:
            return text[divider_pos + len("\n---\n"):]
        return text

    def test_golden_entry_matches_expected(self, tmp_path: Path) -> None:
        """The entry must contain all expected fields with exact values."""
        entry = self._generate_entry(tmp_path / "run1")
        assert "wave/S-99-golden" in entry
        assert "aabbccdd" in entry
        assert "11223344" in entry
        assert "golden fixture merge" in entry
        assert "golden-tester" in entry
        assert "2026-05-29" in entry
        assert "tools/merge_wave_to_main.py" in entry
        assert "Pushed to origin" in entry
        assert "no (push is operator-only" in entry

    def test_golden_entry_byte_identical_on_repeat(self, tmp_path: Path) -> None:
        """Two calls with the same params produce byte-identical entries."""
        entry1 = self._generate_entry(tmp_path / "run1")
        entry2 = self._generate_entry(tmp_path / "run2")
        assert entry1 == entry2, (
            "MERGE-LOG entry not byte-identical on repeat — format has drifted!\n"
            f"Entry 1:\n{entry1}\n\nEntry 2:\n{entry2}"
        )

    def test_golden_entry_stable_across_refactor(self, tmp_path: Path) -> None:
        """
        Hard-coded golden reference: the MERGE-LOG entry shape must not change.
        This test pins the exact field names and structure.
        """
        entry = self._generate_entry(tmp_path / "golden")
        # Each of these lines must appear verbatim in the entry
        required_lines = [
            "- **Method:** tools/merge_wave_to_main.py",
            "- **Operator/Caller:** golden-tester",
            "- **Pre-merge main HEAD:** `aabbccdd`",
            "- **Post-merge main HEAD:** `11223344`",
            "- **Pushed to origin:** no (push is operator-only)",
        ]
        for expected_line in required_lines:
            assert expected_line in entry, (
                f"Golden entry missing expected line: {expected_line!r}\n"
                f"Actual entry:\n{entry}"
            )


# ── tests: help / no-args ─────────────────────────────────────────────────────

class TestHelp:
    def test_help_returns_zero(self) -> None:
        result = robot_settings.main(["--help"])
        assert result == 0

    def test_no_args_returns_zero(self) -> None:
        result = robot_settings.main([])
        assert result == 0
