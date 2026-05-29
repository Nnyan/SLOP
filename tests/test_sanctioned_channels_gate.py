"""
tests/test_sanctioned_channels_gate.py — Tests for check_sanctioned_channels_complete (S-68-E).

Tests:
  - deny mapped in SANCTIONED-CHANNELS.md (registry) → pass (no warning)
  - deny mapped in SANCTIONED-CHANNELS.md (no-exceptions) → pass (no warning)
  - deny not in SANCTIONED-CHANNELS.md at all → warning
  - empty deny list → pass (nothing to check)
  - missing settings file → pass with skip message
  - missing SANCTIONED-CHANNELS.md → pass with skip message
  - multiple unmapped denies → warning listing all gaps
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_ms_enforce() -> types.ModuleType:
    """Load the ms-enforce script (no .py extension) as a module."""
    ms_path = REPO_ROOT / "ms-enforce"
    # Read the source and compile it
    src = ms_path.read_text(encoding="utf-8")
    code = compile(src, str(ms_path), "exec")
    mod = types.ModuleType("ms_enforce")
    mod.__file__ = str(ms_path)
    # Provide the necessary globals
    exec(code, mod.__dict__)  # noqa: S102
    return mod


def _write_settings(path: Path, deny_rules: list[str]) -> None:
    """Write a minimal settings.local.json fixture with given deny rules."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "permissions": {
            "deny": deny_rules,
        }
    }), encoding="utf-8")


def _write_channels(path: Path, registry_rules: list[str], no_exceptions_rules: list[str]) -> None:
    """Write a minimal SANCTIONED-CHANNELS.md fixture with given rules."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Sanctioned Channels\n", "\n"]

    # Registry table
    lines.append("## Registry: deny → sanctioned tool\n\n")
    lines.append("| Deny rule | Sanctioned tool | Notes |\n")
    lines.append("|---|---|---|\n")
    for rule in registry_rules:
        lines.append(f"| `{rule}` | tools/sanctioned/some_tool.py | test |\n")
    lines.append("\n")

    # No-exceptions table
    lines.append("## No-exceptions-period: denies that are NEVER lifted\n\n")
    lines.append("| Deny rule | No-exceptions rationale |\n")
    lines.append("|---|---|\n")
    for rule in no_exceptions_rules:
        lines.append(f"| `{rule}` | Test rationale. |\n")

    path.write_text("".join(lines), encoding="utf-8")


def _run_gate_with_repo(tmp_path: Path) -> tuple[bool, str]:
    """Load a fresh ms-enforce module with REPO pointing to tmp_path."""
    mod = _load_ms_enforce()
    mod.REPO = tmp_path  # type: ignore[attr-defined]
    return mod.check_sanctioned_channels_complete()  # type: ignore[no-any-return]


# ── fixture-based tests using a temporary REPO structure ─────────────────────

class TestSanctionedChannelsGate:
    """Tests using fake REPO structures under tmp_path."""

    def _make_repo(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create minimal .claude/ and docs/ structure. Returns (settings_path, channels_path)."""
        settings = tmp_path / ".claude" / "settings.local.json"
        channels = tmp_path / "docs" / "SANCTIONED-CHANNELS.md"
        return settings, channels

    def test_mapped_in_registry_passes(self, tmp_path: Path) -> None:
        """A deny rule registered in the Registry table produces no warning."""
        settings, channels = self._make_repo(tmp_path)
        deny = ["Bash(git checkout main*)"]
        _write_settings(settings, deny)
        _write_channels(channels, registry_rules=deny, no_exceptions_rules=[])

        passed, msg = _run_gate_with_repo(tmp_path)
        assert passed is True
        assert "WARNING" not in msg
        assert "1 deny rule" in msg

    def test_mapped_in_no_exceptions_passes(self, tmp_path: Path) -> None:
        """A deny rule in the No-exceptions table produces no warning."""
        settings, channels = self._make_repo(tmp_path)
        deny = ["Bash(sudo *)"]
        _write_settings(settings, deny)
        _write_channels(channels, registry_rules=[], no_exceptions_rules=deny)

        passed, msg = _run_gate_with_repo(tmp_path)
        assert passed is True
        assert "WARNING" not in msg

    def test_unmapped_deny_warns(self, tmp_path: Path) -> None:
        """A deny rule NOT in either table produces a WARNING."""
        settings, channels = self._make_repo(tmp_path)
        unmapped_rule = "Bash(some-new-unknown-command *)"
        _write_settings(settings, [unmapped_rule])
        _write_channels(channels, registry_rules=[], no_exceptions_rules=[])

        passed, msg = _run_gate_with_repo(tmp_path)
        assert passed is True  # warn-only — never blocks
        assert "WARNING" in msg
        assert unmapped_rule in msg

    def test_multiple_unmapped_warns_all(self, tmp_path: Path) -> None:
        """Multiple unmapped deny rules all appear in the warning."""
        settings, channels = self._make_repo(tmp_path)
        deny = ["Bash(cmd-one *)", "Bash(cmd-two *)", "Bash(cmd-three *)"]
        _write_settings(settings, deny)
        _write_channels(channels, registry_rules=[], no_exceptions_rules=[])

        passed, msg = _run_gate_with_repo(tmp_path)
        assert passed is True
        assert "WARNING" in msg
        assert "3" in msg

    def test_empty_deny_list_passes(self, tmp_path: Path) -> None:
        """An empty deny list produces no warning."""
        settings, channels = self._make_repo(tmp_path)
        _write_settings(settings, [])
        _write_channels(channels, registry_rules=[], no_exceptions_rules=[])

        passed, msg = _run_gate_with_repo(tmp_path)
        assert passed is True
        assert "nothing to check" in msg

    def test_missing_settings_file_skips(self, tmp_path: Path) -> None:
        """Missing settings.local.json skips with a pass."""
        _, channels = self._make_repo(tmp_path)
        # Don't write settings
        _write_channels(channels, registry_rules=[], no_exceptions_rules=[])

        passed, msg = _run_gate_with_repo(tmp_path)
        assert passed is True
        assert "not found" in msg.lower() or "skip" in msg.lower()

    def test_missing_channels_file_skips(self, tmp_path: Path) -> None:
        """Missing SANCTIONED-CHANNELS.md skips with a pass."""
        settings, _ = self._make_repo(tmp_path)
        # Don't write channels
        _write_settings(settings, ["Bash(sudo *)"])

        passed, msg = _run_gate_with_repo(tmp_path)
        assert passed is True
        assert "not found" in msg.lower() or "skip" in msg.lower()

    def test_mixed_mapped_and_unmapped(self, tmp_path: Path) -> None:
        """Partial coverage: mapped rules pass, unmapped rules warn."""
        settings, channels = self._make_repo(tmp_path)
        registry_deny = ["Bash(git push*)"]
        no_exc_deny = ["Bash(sudo *)"]
        unmapped = "Bash(totally-new-command *)"
        all_deny = registry_deny + no_exc_deny + [unmapped]
        _write_settings(settings, all_deny)
        _write_channels(channels, registry_rules=registry_deny, no_exceptions_rules=no_exc_deny)

        passed, msg = _run_gate_with_repo(tmp_path)
        assert passed is True
        assert "WARNING" in msg
        assert unmapped in msg


# ── integration: real settings.local.json + real SANCTIONED-CHANNELS.md ──────

class TestSanctionedChannelsIntegration:
    """Integration test: verify that the actual project settings and channels file
    are consistent — i.e., all real deny rules are covered."""

    def test_real_settings_fully_covered(self) -> None:
        """All deny rules in the real settings.local.json must be covered by
        docs/SANCTIONED-CHANNELS.md — no gaps allowed in the project's own config."""
        mod = _load_ms_enforce()
        mod.REPO = REPO_ROOT  # type: ignore[attr-defined]
        passed, msg = mod.check_sanctioned_channels_complete()  # type: ignore[no-any-return]

        assert passed is True
        # The integration test checks that there are no warnings about unmapped rules
        if "WARNING" in msg:
            pytest.fail(
                f"Real settings.local.json has deny rules not covered by "
                f"SANCTIONED-CHANNELS.md:\n{msg}"
            )
