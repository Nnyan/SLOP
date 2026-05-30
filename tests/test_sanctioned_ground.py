"""tests/test_sanctioned_ground.py — BATCH-11 S6 (P6): Sanctioned-channel GROUND leg.

Two kinds of proof:

1. **AST GROUND gate** (tools/audit_sanctioned_ground.py):
   - verified on the real repo (every registry-row tool exists + is correctly wired);
   - DRIFT on a planted bad tool (lifts without a finally-guarded restore) — the gate
     can go RED against physics (report §4c structural leg).

2. **Per-tool RED-PATH crash-mid-push test (the REAL proof):** for each registry-row
   tool that performs a lift, simulate a crash DURING the push and assert the deny is
   RESTORED. AST presence != correct ordering — this is what actually proves the
   try/finally invariant holds. We exercise the tools' real `run`/`push-then-restore`
   entry points with the push step mocked to raise, against a tmp settings fixture.
   NEVER touches the real settings.local.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.audit_sanctioned_ground import audit, _ast_wiring, _registry_tool_paths


# ── 1. AST GROUND gate ────────────────────────────────────────────────────────

class TestAstGroundGate:
    def test_real_repo_verifies(self):
        """Every registry-row tool on the real repo is wired correctly -> verified."""
        verdict, lines = audit(REPO)
        assert verdict == "verified", "\n".join(lines)

    def test_registry_parse_finds_tools(self):
        md = (REPO / "docs" / "SANCTIONED-CHANNELS.md").read_text(encoding="utf-8")
        tools = _registry_tool_paths(md, REPO)
        names = {p.name for _, p in tools}
        assert "robot_settings.py" in names
        assert "force_push_tag.py" in names
        assert "merge_wave_to_main.py" in names

    def test_lifted_cm_counts_as_guaranteed_restore(self):
        """A tool using `with lifted(...)` has a guaranteed restore."""
        src = (
            "from tools.sanctioned._lift_restore import lifted\n"
            "from tools.sanctioned._audit import write_entry\n"
            "def run():\n"
            "    with lifted(['Bash(git push*)']):\n"
            "        write_entry(tool='x', op='y')\n"
        )
        legs = _ast_wiring(src)
        assert legs["calls_lift"] and legs["calls_restore"]
        assert legs["restore_is_guaranteed"]
        assert legs["calls_audit"]

    def test_bare_lift_without_finally_is_not_guaranteed(self):
        """A tool that lifts and restores only on the happy path -> NOT guaranteed."""
        src = (
            "from tools.sanctioned._lift_restore import lift, restore\n"
            "def run():\n"
            "    lift(['Bash(git push*)'])\n"
            "    do_push()\n"          # if this raises, restore never runs
            "    restore()\n"
        )
        legs = _ast_wiring(src)
        assert legs["calls_lift"] and legs["calls_restore"]
        assert not legs["restore_is_guaranteed"]

    def test_planted_bad_tool_drifts(self, tmp_path):
        """RED-PATH: a registry-row tool that lifts without a finally-guarded restore
        makes the gate go DRIFT (proves it can go red against physics)."""
        # Build a minimal fake repo with a SANCTIONED-CHANNELS.md pointing at one
        # deliberately-broken tool.
        (tmp_path / "docs").mkdir()
        (tmp_path / "tools" / "sanctioned").mkdir(parents=True)
        bad = tmp_path / "tools" / "sanctioned" / "leaky_push.py"
        bad.write_text(
            "from tools.sanctioned._lift_restore import lift, restore\n"
            "def run():\n"
            "    lift(['Bash(git push*)'])\n"
            "    do_push()\n"
            "    restore()\n",
            encoding="utf-8",
        )
        (tmp_path / "docs" / "SANCTIONED-CHANNELS.md").write_text(
            "## Registry: deny -> sanctioned tool\n\n"
            "| Deny rule | Sanctioned tool | Notes |\n"
            "|---|---|---|\n"
            "| `Bash(git push*)` | `tools/sanctioned/leaky_push.py` | leaks on crash |\n\n"
            "## No-exceptions-period\n",
            encoding="utf-8",
        )
        verdict, lines = audit(tmp_path)
        assert verdict == "DRIFT", "\n".join(lines)
        assert any("leaky_push.py" in ln and "DRIFT" in ln for ln in lines)

    def test_missing_tool_drifts(self, tmp_path):
        """RED-PATH: a registry row pointing at a non-existent tool -> DRIFT."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "SANCTIONED-CHANNELS.md").write_text(
            "## Registry: deny -> sanctioned tool\n\n"
            "| Deny rule | Sanctioned tool | Notes |\n"
            "|---|---|---|\n"
            "| `Bash(git push*)` | `tools/sanctioned/ghost.py` | deleted |\n\n"
            "## No-exceptions-period\n",
            encoding="utf-8",
        )
        verdict, lines = audit(tmp_path)
        assert verdict == "DRIFT"
        assert any("ghost.py" in ln and "does not exist" in ln for ln in lines)

    def test_missing_doc_is_indeterminate(self, tmp_path):
        """No registry doc -> INDETERMINATE (unreachable ground), never a silent pass."""
        verdict, _ = audit(tmp_path)
        assert verdict == "INDETERMINATE"


# ── 2. Per-tool RED-PATH: crash mid-push -> deny restored ──────────────────────

def _make_settings_and_profile(tmp_path: Path) -> Path:
    """Create a fixture .claude/ with settings.local.json + wave-mode-profile."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    perms = {
        "permissions": {
            "allow": ["Read", "Edit"],
            "deny": ["Bash(git push*)", "Bash(git push -f*)", "Bash(git push -u*)",
                     "Bash(git push --no-verify*)", "Bash(git push --force*)",
                     "Bash(git checkout main*)", "Bash(git switch main*)"],
            "defaultMode": "bypassPermissions",
        }
    }
    (claude / "settings.local.json").write_text(json.dumps(perms, indent=2) + "\n", encoding="utf-8")
    (claude / "settings-wave-mode-profile.json").write_text(json.dumps(perms, indent=2) + "\n", encoding="utf-8")
    return claude / "settings.local.json"


def _deny(settings: Path) -> list[str]:
    return json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"]


class TestForcePushCrashMidPush:
    """force_push_tag.run with the push raising mid-flight -> deny restored."""

    def test_deny_restored_when_push_crashes(self, tmp_path):
        from tools.sanctioned import force_push_tag

        settings = _make_settings_and_profile(tmp_path)
        before = _deny(settings)
        log = tmp_path / "ops.md"
        FAKE = "abcdef1234567890abcdef1234567890abcdef12"

        with mock.patch.object(force_push_tag, "_get_head_sha", return_value=FAKE), \
             mock.patch.object(force_push_tag, "_do_force_push",
                               side_effect=RuntimeError("network died mid-push")):
            rc = force_push_tag.run(
                ref="refs/tags/v9.9.9", remote="origin",
                reason="crash-mid-push red-path", confirm=FAKE[-7:],
                dry_run=False, settings_path=settings, log_path=log,
            )
        # A crash mid-push must NOT leave the push deny lifted.
        after = _deny(settings)
        assert after == before, f"deny leaked after crash: {before} -> {after}"
        assert "Bash(git push*)" in after


class TestRobotSettingsCrashMidPush:
    """robot_settings push-then-restore with subprocess raising -> deny restored."""

    def test_deny_restored_when_push_crashes(self, tmp_path, monkeypatch):
        from tools.sanctioned import robot_settings

        settings = _make_settings_and_profile(tmp_path)
        before = _deny(settings)
        # Point the tool's repo-root at our fixture so it edits the tmp settings.
        monkeypatch.setattr(robot_settings, "_REPO_ROOT", tmp_path)
        # Redirect the audit log so we don't touch the real SANCTIONED-OPS-LOG.
        monkeypatch.setenv("SLOP_AUDIT_LOG_PATH", str(tmp_path / "ops.md"))
        # _git_sha() is fine; only the PUSH subprocess crashes mid-flight.
        monkeypatch.setattr(robot_settings, "_git_sha", lambda *a, **k: "deadbee")

        def _crash_on_push(cmd, *a, **k):
            if "push" in cmd:
                raise RuntimeError("ssh died mid-push")
            raise AssertionError(f"unexpected subprocess: {cmd}")

        with mock.patch.object(robot_settings.subprocess, "run", side_effect=_crash_on_push):
            with pytest.raises(SystemExit):
                # _die() raises SystemExit; the lifted() finally must still restore.
                robot_settings._cmd_push_then_restore([])

        after = _deny(settings)
        assert after == before, f"deny leaked after crash: {before} -> {after}"
        assert "Bash(git push*)" in after


class TestLiftPushRestoreCrashMidPush:
    """lift_push_restore.py is the routine path; document its crash behaviour.

    Its `main('all')` restores on a non-zero push RETURN code, but it does NOT
    wrap lift/push/restore in a try/finally — so an EXCEPTION inside push() (not
    just a non-zero rc) would leak the deny. The GROUND gate does not flag this
    tool because it is not in the SANCTIONED-CHANNELS Registry table. We pin the
    non-zero-rc restore behaviour (its actual safety contract) here, and record
    the exception-leak gap as an observation in the stream return.
    """

    def test_deny_restored_on_nonzero_push_rc(self, tmp_path, monkeypatch):
        import tools.sanctioned.lift_push_restore as lpr

        settings = _make_settings_and_profile(tmp_path)
        before = _deny(settings)
        monkeypatch.setattr(lpr, "SETTINGS_PATH", settings)

        # push() returns non-zero (rejected push) — main('all') must restore.
        with mock.patch.object(lpr, "push", return_value=1):
            rc = lpr.main(["all", "--branch", "main"])
        assert rc == 1
        after = _deny(settings)
        assert "Bash(git push*)" in after, f"deny leaked on non-zero push rc: {after}"
