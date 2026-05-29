"""
tests/test_sanctioned_lift_restore.py — Tests for tools/sanctioned/_lift_restore.py

All tests use tmp_path copies of fixture settings files — NEVER mutate
the real .claude/settings.local.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make tools/ importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.sanctioned._lift_restore import (
    SETTINGS_LOCAL,
    WAVE_MODE_PROFILE,
    lift,
    lifted,
    restore,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_settings(tmp_path: Path, *, extra_deny: list[str] | None = None) -> Path:
    """Create a fixture settings.local.json in tmp_path."""
    deny = [
        "Bash(git push*)",
        "Bash(git push -f*)",
        "Bash(git checkout main*)",
        "Bash(git switch main*)",
        "Bash(sudo *)",
    ]
    if extra_deny:
        deny.extend(extra_deny)
    data = {
        "permissions": {
            "allow": ["Read", "Edit", "Write"],
            "deny": deny,
            "defaultMode": "bypassPermissions",
        }
    }
    settings = tmp_path / "settings.local.json"
    settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return settings


def _make_profile(tmp_path: Path) -> Path:
    """Create a fixture wave-mode-profile.json in tmp_path (same dir as settings)."""
    # The canonical profile has the full deny list
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
    profile = tmp_path / "settings-wave-mode-profile.json"
    profile.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return profile


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── constant tests ────────────────────────────────────────────────────────────

class TestConstants:
    def test_settings_local_is_path(self):
        assert isinstance(SETTINGS_LOCAL, Path)
        assert str(SETTINGS_LOCAL) == ".claude/settings.local.json"

    def test_wave_mode_profile_is_path(self):
        assert isinstance(WAVE_MODE_PROFILE, Path)
        assert str(WAVE_MODE_PROFILE) == ".claude/settings-wave-mode-profile.json"


# ── lift tests ────────────────────────────────────────────────────────────────

class TestLift:
    def test_lift_removes_from_deny(self, tmp_path):
        settings = _make_settings(tmp_path)
        lift(["Bash(git push*)"], settings_path=settings)
        data = _load(settings)
        assert "Bash(git push*)" not in data["permissions"]["deny"]

    def test_lift_adds_to_allow(self, tmp_path):
        settings = _make_settings(tmp_path)
        lift(["Bash(git push*)"], settings_path=settings)
        data = _load(settings)
        assert "Bash(git push*)" in data["permissions"]["allow"]

    def test_lift_multi_pattern(self, tmp_path):
        settings = _make_settings(tmp_path)
        patterns = ["Bash(git push*)", "Bash(git checkout main*)"]
        lift(patterns, settings_path=settings)
        data = _load(settings)
        for p in patterns:
            assert p not in data["permissions"]["deny"]
            assert p in data["permissions"]["allow"]

    def test_lift_idempotent(self, tmp_path):
        """Calling lift twice with the same patterns is safe."""
        settings = _make_settings(tmp_path)
        patterns = ["Bash(git push*)"]
        lift(patterns, settings_path=settings)
        lift(patterns, settings_path=settings)
        data = _load(settings)
        assert "Bash(git push*)" not in data["permissions"]["deny"]
        # Should appear exactly once in allow
        assert data["permissions"]["allow"].count("Bash(git push*)") == 1

    def test_lift_other_deny_rules_preserved(self, tmp_path):
        settings = _make_settings(tmp_path)
        lift(["Bash(git push*)"], settings_path=settings)
        data = _load(settings)
        # Other deny rules untouched
        assert "Bash(sudo *)" in data["permissions"]["deny"]
        assert "Bash(git checkout main*)" in data["permissions"]["deny"]

    def test_lift_preserves_existing_allow(self, tmp_path):
        settings = _make_settings(tmp_path)
        lift(["Bash(git push*)"], settings_path=settings)
        data = _load(settings)
        # Pre-existing allow entries preserved
        assert "Read" in data["permissions"]["allow"]
        assert "Edit" in data["permissions"]["allow"]


# ── restore tests ─────────────────────────────────────────────────────────────

class TestRestore:
    def test_restore_reapplies_profile_deny(self, tmp_path):
        settings = _make_settings(tmp_path)
        _make_profile(tmp_path)
        # Lift first
        lift(["Bash(git push*)", "Bash(git checkout main*)"], settings_path=settings)
        # Now restore
        restore(settings_path=settings)
        data = _load(settings)
        assert "Bash(git push*)" in data["permissions"]["deny"]
        assert "Bash(git checkout main*)" in data["permissions"]["deny"]

    def test_restore_profile_verbatim(self, tmp_path):
        """restore() produces permissions block identical to profile."""
        settings = _make_settings(tmp_path)
        profile = _make_profile(tmp_path)
        profile_data = _load(profile)
        restore(settings_path=settings)
        data = _load(settings)
        assert data["permissions"] == profile_data["permissions"]

    def test_restore_idempotent(self, tmp_path):
        """Calling restore() twice produces the same result."""
        settings = _make_settings(tmp_path)
        _make_profile(tmp_path)
        restore(settings_path=settings)
        data_first = _load(settings)
        restore(settings_path=settings)
        data_second = _load(settings)
        assert data_first["permissions"] == data_second["permissions"]

    def test_restore_recovers_from_mangled_state(self, tmp_path):
        """restore() fixes arbitrary mangled settings to match the profile."""
        settings = tmp_path / "settings.local.json"
        # Write deliberately mangled state
        mangled = {
            "permissions": {
                "allow": ["Bash(sudo *)", "Bash(git push -f*)", "EVIL_RULE"],
                "deny": [],
                "defaultMode": "ask",
            }
        }
        settings.write_text(json.dumps(mangled, indent=2) + "\n", encoding="utf-8")
        _make_profile(tmp_path)
        restore(settings_path=settings)
        data = _load(settings)
        profile_data = _load(tmp_path / "settings-wave-mode-profile.json")
        assert data["permissions"] == profile_data["permissions"]

    def test_restore_removes_lifted_patterns_from_allow(self, tmp_path):
        """After restore, previously-lifted patterns are back in deny, not allow."""
        settings = _make_settings(tmp_path)
        _make_profile(tmp_path)
        lift(["Bash(git push*)"], settings_path=settings)
        restore(settings_path=settings)
        data = _load(settings)
        profile_data = _load(tmp_path / "settings-wave-mode-profile.json")
        assert data["permissions"]["allow"] == profile_data["permissions"]["allow"]
        assert "Bash(git push*)" in data["permissions"]["deny"]


# ── lifted() context manager tests ───────────────────────────────────────────

class TestLifted:
    def test_lifted_restores_after_success(self, tmp_path):
        settings = _make_settings(tmp_path)
        _make_profile(tmp_path)
        with lifted(["Bash(git push*)"], settings_path=settings):
            data_inside = _load(settings)
            assert "Bash(git push*)" not in data_inside["permissions"]["deny"]
            assert "Bash(git push*)" in data_inside["permissions"]["allow"]
        # After context manager exits, restore should have been called
        data_after = _load(settings)
        profile_data = _load(tmp_path / "settings-wave-mode-profile.json")
        assert data_after["permissions"] == profile_data["permissions"]

    def test_lifted_restores_on_exception(self, tmp_path):
        """lifted() must restore even when the body raises an exception."""
        settings = _make_settings(tmp_path)
        _make_profile(tmp_path)
        with pytest.raises(ValueError, match="test error"):
            with lifted(["Bash(git push*)", "Bash(git checkout main*)"],
                        settings_path=settings):
                raise ValueError("test error")
        # Settings should be restored to canonical profile
        data = _load(settings)
        profile_data = _load(tmp_path / "settings-wave-mode-profile.json")
        assert data["permissions"] == profile_data["permissions"]

    def test_lifted_restores_on_runtime_error(self, tmp_path):
        """lifted() restores on RuntimeError too."""
        settings = _make_settings(tmp_path)
        _make_profile(tmp_path)
        with pytest.raises(RuntimeError):
            with lifted(["Bash(sudo *)"], settings_path=settings):
                raise RuntimeError("simulated failure")
        data = _load(settings)
        profile_data = _load(tmp_path / "settings-wave-mode-profile.json")
        assert data["permissions"] == profile_data["permissions"]

    def test_lifted_multi_pattern_restores(self, tmp_path):
        """Multi-pattern lift/restore round-trips correctly."""
        settings = _make_settings(tmp_path)
        _make_profile(tmp_path)
        patterns = ["Bash(git push*)", "Bash(git push -f*)", "Bash(git checkout main*)"]
        with lifted(patterns, settings_path=settings):
            pass
        data = _load(settings)
        profile_data = _load(tmp_path / "settings-wave-mode-profile.json")
        assert data["permissions"] == profile_data["permissions"]

    def test_lifted_yields_control(self, tmp_path):
        """lifted() yields and the body executes before restore."""
        settings = _make_settings(tmp_path)
        _make_profile(tmp_path)
        executed = []
        with lifted(["Bash(git push*)"], settings_path=settings):
            executed.append("ran")
        assert executed == ["ran"]


# ── real profile sanity check (read-only) ────────────────────────────────────

class TestRealProfileReadOnly:
    def test_real_profile_exists_and_has_deny(self):
        """The real wave-mode profile exists and has a non-empty deny list.

        This test is READ-ONLY — it does not modify any real file.
        """
        # Resolve from the repo root
        repo_root = Path(__file__).parent.parent
        profile_path = repo_root / WAVE_MODE_PROFILE
        assert profile_path.exists(), (
            f"Wave-mode profile not found at {profile_path}. "
            "Stream A must create it."
        )
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        assert "permissions" in data
        assert "deny" in data["permissions"]
        assert len(data["permissions"]["deny"]) > 0, "Profile deny list must not be empty"

    def test_real_settings_local_matches_profile_deny(self):
        """The real settings.local.json deny list matches the profile deny list.

        This is a consistency check only (read-only).
        """
        repo_root = Path(__file__).parent.parent
        settings_path = repo_root / SETTINGS_LOCAL
        profile_path = repo_root / WAVE_MODE_PROFILE
        if not settings_path.exists() or not profile_path.exists():
            pytest.skip("Real settings files not present — skipping consistency check")
        settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
        profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        settings_deny = set(settings_data.get("permissions", {}).get("deny", []))
        profile_deny = set(profile_data.get("permissions", {}).get("deny", []))
        assert settings_deny == profile_deny, (
            f"settings.local.json deny list differs from wave-mode profile.\n"
            f"Only in settings: {settings_deny - profile_deny}\n"
            f"Only in profile:  {profile_deny - settings_deny}"
        )
