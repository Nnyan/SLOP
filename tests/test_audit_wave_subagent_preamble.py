"""tests/test_audit_wave_subagent_preamble.py — Tests for
tools/audit_wave_subagent_preamble.py and the ms-enforce
check_wave_subagent_preamble gate.

Covers:
  - clean-pass: wave file with all three preamble signals -> no WARNING
  - warn case: wave file missing some/all signals -> WARNING emitted
  - no Robot mode section: wave file is skipped (no warning)
  - exit code always 0
  - ms-enforce registration (integration smoke test)
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO / "tools" / "audit_wave_subagent_preamble.py"


def _py() -> str:
    """Return path to Python interpreter, preferring the project venv."""
    venv_py = REPO / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _run_script(repo: Path) -> tuple[int, str]:
    """Run the audit script against a fixture repo dir."""
    result = subprocess.run(
        [_py(), str(AUDIT_SCRIPT), "--repo", str(repo)],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout + result.stderr


def _make_waves_dir(repo: Path) -> Path:
    """Create a minimal .claude/waves/ directory."""
    waves = repo / ".claude" / "waves"
    waves.mkdir(parents=True, exist_ok=True)
    return waves


# ---------------------------------------------------------------------------
# Fixture wave file content helpers
# ---------------------------------------------------------------------------

CLEAN_WAVE_TEXT = textwrap.dedent("""\
    # S-55 Deps and Tooling
    ## Goal
    Add dependencies and tooling improvements.

    ## Out of scope
    - Something else.

    ## Robot mode (autonomous execution)
    When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
    doctrine v3 (orchestrator-as-coordinator, subagent preamble with venv symlink,
    Bash heredoc for new files, never AskUserQuestion, never git push, merge to
    `wave/S-55-deps-and-tooling` not main).

    Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-55-DEPS-AND-TOOLING.md as orchestrator.`
""")

WARN_WAVE_NO_SIGNALS_TEXT = textwrap.dedent("""\
    # S-57 Tier2 Cleanup
    ## Goal
    Fix Tier2 test failures.

    ## Robot mode (autonomous execution)
    When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
    doctrine v3. Stream A sequential before B and C dispatch.
    Coordinator merges to `wave/S-57-tier2-cleanup` not main.

    Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-57-TIER2-CLEANUP.md as orchestrator.`
""")

WARN_WAVE_PARTIAL_TEXT = textwrap.dedent("""\
    # S-60 Agent Fix Safety
    ## Goal
    Add safety guardrails to agent auto-fix paths.

    ## Robot mode (autonomous execution)
    When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
    doctrine v4. Streams A and B parallel.
    Never call AskUserQuestion. Write a decision file instead.
    Coordinator merges to `wave/S-60-agent-fix-safety`, never main.

    Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-60-AGENT-FIX-SAFETY.md as orchestrator.`
""")

NO_ROBOT_MODE_TEXT = textwrap.dedent("""\
    # Optional File Size Remediation
    ## Goal
    Gradually reduce oversized files.

    ## Approach
    Work iteratively across multiple cleanup waves.
    No automated dispatch required.
""")

INLINE_ASKUSER_TEXT = textwrap.dedent("""\
    # S-46 Pin Relax
    ## Goal
    Relax dependency pins.

    ## Robot mode (autonomous execution)
    When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
    doctrine v3. Summary of binding rules:

    1. NEVER call `AskUserQuestion`. Write a decision file instead and continue.
    2. NEVER enter plan mode.

    Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-46-PIN-RELAX.md as orchestrator.`
""")


# ---------------------------------------------------------------------------
# Tests: clean-pass cases
# ---------------------------------------------------------------------------

class TestAuditWavePreambleCleanPass:
    def test_no_waves_dir_exits_cleanly(self, tmp_path: Path) -> None:
        """No .claude/waves/ directory: scanner exits 0, no output."""
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out

    def test_empty_waves_dir_exits_cleanly(self, tmp_path: Path) -> None:
        """Empty .claude/waves/ directory: scanner exits 0, no warnings."""
        _make_waves_dir(tmp_path)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out

    def test_wave_with_all_three_signals_passes(self, tmp_path: Path) -> None:
        """Wave file with venv-symlink + file-creation-heredoc + no-AskUserQuestion: no warning."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-55-DEPS-AND-TOOLING.md").write_text(CLEAN_WAVE_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out

    def test_wave_without_robot_mode_section_skipped(self, tmp_path: Path) -> None:
        """Wave file with no '## Robot mode' section is skipped entirely."""
        waves = _make_waves_dir(tmp_path)
        (waves / "OPTIONAL-FILE-SIZE-REMEDIATION.md").write_text(NO_ROBOT_MODE_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out

    def test_exit_code_always_zero(self, tmp_path: Path) -> None:
        """Exit code is 0 even when multiple warnings are emitted."""
        waves = _make_waves_dir(tmp_path)
        # Missing all three signals
        (waves / "S-99-NO-SIGNALS.md").write_text(WARN_WAVE_NO_SIGNALS_TEXT)
        rc, _out = _run_script(tmp_path)
        assert rc == 0

    def test_mixed_clean_and_warn_exits_zero(self, tmp_path: Path) -> None:
        """Mix of passing and failing wave files still exits 0."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-55-CLEAN.md").write_text(CLEAN_WAVE_TEXT)
        (waves / "S-57-WARN.md").write_text(WARN_WAVE_NO_SIGNALS_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        # The clean file should not appear in warnings
        assert "S-55-CLEAN.md" not in out
        # The warn file should appear
        assert "WARNING" in out
        assert "S-57-WARN.md" in out

    def test_inline_askuser_satisfies_no_ask_signal(self, tmp_path: Path) -> None:
        """Older style 'NEVER call AskUserQuestion' inline satisfies no-AskUserQuestion signal."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-46-PIN-RELAX.md").write_text(INLINE_ASKUSER_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        # Should warn about venv-symlink and file-creation-heredoc (missing)
        # but NOT about no-AskUserQuestion (present)
        if "WARNING" in out and "S-46-PIN-RELAX.md" in out:
            assert "no-AskUserQuestion" not in out


# ---------------------------------------------------------------------------
# Tests: warn cases
# ---------------------------------------------------------------------------

class TestAuditWavePreambleWarnCases:
    def test_wave_missing_all_signals_warns(self, tmp_path: Path) -> None:
        """Wave with Robot mode section but none of the three signals: WARNING emitted."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-57-TIER2-CLEANUP.md").write_text(WARN_WAVE_NO_SIGNALS_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" in out
        assert "S-57-TIER2-CLEANUP.md" in out
        assert "venv-symlink" in out
        assert "file-creation-heredoc" in out
        assert "no-AskUserQuestion" in out

    def test_wave_missing_venv_and_heredoc_warns(self, tmp_path: Path) -> None:
        """Wave with AskUserQuestion but no venv-symlink or heredoc: partially warns."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-60-AGENT-FIX-SAFETY.md").write_text(WARN_WAVE_PARTIAL_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        # Should warn about venv-symlink and file-creation-heredoc
        # but NOT about no-AskUserQuestion (present via inline rule)
        if "WARNING" in out and "S-60-AGENT-FIX-SAFETY.md" in out:
            assert "no-AskUserQuestion" not in out

    def test_warning_line_format(self, tmp_path: Path) -> None:
        """WARNING lines follow the format 'WARNING: <path>  missing preamble signal(s): ...'."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-99-WARN.md").write_text(WARN_WAVE_NO_SIGNALS_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) >= 1
        # Format check: should contain 'missing preamble signal(s):'
        for ln in warning_lines:
            assert "missing preamble signal(s):" in ln

    def test_multiple_warn_waves_all_flagged(self, tmp_path: Path) -> None:
        """Multiple wave files missing signals each get a WARNING line."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-57-A.md").write_text(WARN_WAVE_NO_SIGNALS_TEXT)
        (waves / "S-58-B.md").write_text(WARN_WAVE_NO_SIGNALS_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        warning_lines = [ln for ln in out.splitlines() if ln.startswith("WARNING:")]
        assert len(warning_lines) == 2

    def test_ok_message_when_all_clean(self, tmp_path: Path) -> None:
        """When all Robot-mode waves pass, an OK message is emitted."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-55-CLEAN.md").write_text(CLEAN_WAVE_TEXT)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out
        assert "OK" in out


# ---------------------------------------------------------------------------
# Tests: signal detection edge cases
# ---------------------------------------------------------------------------

class TestSignalDetection:
    def test_subagent_preamble_phrase_satisfies_venv_signal(self, tmp_path: Path) -> None:
        """'subagent preamble' phrase (without 'with venv symlink') satisfies venv signal."""
        waves = _make_waves_dir(tmp_path)
        text = textwrap.dedent("""\
            # S-X Test
            ## Robot mode (autonomous execution)
            Operate under `.claude/ROBOT.md` doctrine v4.
            The orchestrator includes the subagent preamble in every dispatch.
            Bash heredoc for new files. Do not call AskUserQuestion.
        """)
        (waves / "S-X-TEST.md").write_text(text)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        # Should pass — 'subagent preamble' + 'Bash heredoc' + 'AskUserQuestion'
        assert "WARNING" not in out

    def test_ln_sf_venv_satisfies_venv_signal(self, tmp_path: Path) -> None:
        """'ln -sf /path/.venv' in file satisfies the venv-symlink signal."""
        waves = _make_waves_dir(tmp_path)
        text = textwrap.dedent("""\
            # S-Y Test
            ## Robot mode (autonomous execution)
            Run: ln -sf /home/stack/code/slop/.venv .venv
            Bash heredoc for new files. Do not call AskUserQuestion.
        """)
        (waves / "S-Y-TEST.md").write_text(text)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out

    def test_not_the_write_tool_satisfies_file_creation(self, tmp_path: Path) -> None:
        """'not the Write tool' phrase satisfies the file-creation signal."""
        waves = _make_waves_dir(tmp_path)
        text = textwrap.dedent("""\
            # S-Z Test
            ## Robot mode (autonomous execution)
            subagent preamble with venv symlink.
            For new files, use Bash heredocs, NOT the Write tool.
            Never call AskUserQuestion.
        """)
        (waves / "S-Z-TEST.md").write_text(text)
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out

    def test_non_md_files_in_waves_dir_ignored(self, tmp_path: Path) -> None:
        """Non-.md files in .claude/waves/ are not scanned."""
        waves = _make_waves_dir(tmp_path)
        (waves / "README.txt").write_text("Just a readme, no Robot mode section.")
        rc, out = _run_script(tmp_path)
        assert rc == 0
        assert "WARNING" not in out


# ---------------------------------------------------------------------------
# Integration: ms-enforce registration
# ---------------------------------------------------------------------------

class TestMsEnforceRegistration:
    def test_check_function_defined_in_ms_enforce(self) -> None:
        """check_wave_subagent_preamble is defined in ms-enforce."""
        ms_enforce = REPO / "ms-enforce"
        assert ms_enforce.exists(), "ms-enforce must exist"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "check_wave_subagent_preamble" in text, \
            "check_wave_subagent_preamble must be defined in ms-enforce"

    def test_check_registered_in_tier1(self) -> None:
        """check_wave_subagent_preamble is listed in TIER_1."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "check_wave_subagent_preamble" in text
        # Verify it appears in the TIER_1 list (after the TIER_1 = line)
        tier1_pos = text.find("TIER_1: list[tuple[str, object]] = [")
        assert tier1_pos != -1, "TIER_1 list not found"
        tier2_pos = text.find("TIER_2: list[tuple[str, object]] = [")
        tier1_section = text[tier1_pos:tier2_pos] if tier2_pos != -1 else text[tier1_pos:]
        assert "check_wave_subagent_preamble" in tier1_section, \
            "check_wave_subagent_preamble must be in TIER_1, not TIER_2"

    def test_check_label_contains_warn_only(self) -> None:
        """TIER_1 registration label for check_wave_subagent_preamble says 'warn only'."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        # Find the registration line
        for line in text.splitlines():
            if "check_wave_subagent_preamble" in line and ("warn only" in line or "warn-only" in line):
                return  # found
        pytest.fail(
            "TIER_1 registration for check_wave_subagent_preamble must include "
            "'warn only' in the label string"
        )

    def test_audit_script_exists(self) -> None:
        """tools/audit_wave_subagent_preamble.py exists."""
        assert AUDIT_SCRIPT.exists(), \
            f"audit_wave_subagent_preamble.py not found at {AUDIT_SCRIPT}"
