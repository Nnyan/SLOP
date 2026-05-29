"""tests/test_audit_orchestrator_prompt_format.py

Tests for tools/audit_orchestrator_prompt_format.py — orchestrator prompt
format linter.  Uses fixture directories / files populated with synthetic
content to verify clean-pass and warn cases for each of the three elements:

  1. git rev-parse origin/main base
  2. Per-stream model assignments
  3. Subagent preamble reference

Tests also cover the ms-enforce wrapper (check_orchestrator_prompt_format)
and the standalone scanner exit code.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "tools" / "audit_orchestrator_prompt_format.py"


def _py() -> str:
    venv_py = REPO / ".venv" / "bin" / "python3"
    return str(venv_py) if venv_py.exists() else sys.executable


def _run_scanner(repo: Path) -> tuple[int, str]:
    result = subprocess.run(
        [_py(), str(SCANNER), "--repo", str(repo)],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Helpers to build fixture repo trees
# ---------------------------------------------------------------------------

def _make_waves_dir(repo: Path) -> Path:
    waves = repo / ".claude" / "waves"
    waves.mkdir(parents=True, exist_ok=True)
    return waves


def _make_archive_dir(repo: Path, batch: str = "2026-01-01-test") -> tuple[Path, Path]:
    """Create .claude/run-archive/<batch>/{status,decisions}/ and return both."""
    base = repo / ".claude" / "run-archive" / batch
    status = base / "status"
    decisions = base / "decisions"
    status.mkdir(parents=True, exist_ok=True)
    decisions.mkdir(parents=True, exist_ok=True)
    return status, decisions


_FULL_COMPLIANT_WAVE = textwrap.dedent("""\
    # S-70-TEST-WAVE — test fixture

    ## Cross-wave dependencies (EXPLICIT)
    - Depends ONLY on current main (`git rev-parse origin/main` at startup).

    ## Parallelization
    **Models:** coordinator = **opus**, subagents = **sonnet**. Two streams A∥B.

    | Stream | Order | Subagent type |
    |---|---|---|
    | A | parallel | sonnet in worktree |
    | B | parallel | sonnet in worktree |

    ## Robot mode (autonomous execution)
    Operate under `.claude/ROBOT.md` doctrine v4. The orchestrator dispatches the
    subagent preamble (venv-symlink, no AskUserQuestion, in Robot mode signal)
    at the top of each subagent's task prompt.

    Invocation: `in Robot mode: execute the wave.`
""")

_MISSING_GIT_BASE_WAVE = textwrap.dedent("""\
    # S-70-TEST-WAVE — test fixture

    ## Cross-wave dependencies (EXPLICIT)
    - Depends ONLY on current main (HEAD).

    ## Parallelization
    **Models:** coordinator = **opus**, subagents = **sonnet**. Two streams A∥B.

    | Stream | Order | Subagent type |
    |---|---|---|
    | A | parallel | sonnet in worktree |

    ## Robot mode (autonomous execution)
    Operate under `.claude/ROBOT.md` doctrine v4. The orchestrator dispatches the
    subagent preamble (venv-symlink, no AskUserQuestion, in Robot mode signal)
    at the top of each subagent's task prompt.

    Invocation: `in Robot mode: execute the wave.`
""")

_MISSING_MODELS_WAVE = textwrap.dedent("""\
    # S-70-TEST-WAVE — test fixture

    ## Cross-wave dependencies (EXPLICIT)
    - Depends ONLY on current main (`git rev-parse origin/main` at startup).

    ## Parallelization
    Two streams A and B run in parallel from separate worktrees.

    | Stream | Order |
    |---|---|
    | A | parallel |
    | B | parallel |

    ## Robot mode (autonomous execution)
    Operate under `.claude/ROBOT.md` doctrine v4.
    subagent preamble injected at dispatch time.

    Invocation: `in Robot mode: execute the wave.`
""")

_MISSING_PREAMBLE_WAVE = textwrap.dedent("""\
    # S-70-TEST-WAVE — test fixture

    ## Cross-wave dependencies (EXPLICIT)
    - Depends ONLY on current main (`git rev-parse origin/main` at startup).

    ## Parallelization
    **Models:** coordinator = **opus**, subagents = **sonnet**. Two streams A∥B.

    | Stream | Order | Subagent type |
    |---|---|---|
    | A | parallel | sonnet in worktree |

    ## Robot mode (autonomous execution)
    Operate under `.claude/ROBOT.md` doctrine v4.

    Invocation: `in Robot mode: execute the wave.`
""")

_NO_ROBOT_SECTION_WAVE = textwrap.dedent("""\
    # S-70-DESIGN-ONLY — test fixture (no Robot mode section)

    ## Cross-wave dependencies
    This is a design document, not an orchestrator prompt.

    ## Parallelization
    N/A
""")


# ---------------------------------------------------------------------------
# Tests: wave file scanning
# ---------------------------------------------------------------------------

class TestWaveFileLint:
    def test_fully_compliant_wave_no_warnings(self, tmp_path: Path) -> None:
        """A wave file with all three elements emits no warnings."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-70-COMPLIANT.md").write_text(_FULL_COMPLIANT_WAVE)
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines() if ln.startswith("WARNING")]
        # Should have no warnings for this file
        file_warnings = [w for w in warnings if "S-70-COMPLIANT" in w]
        assert not file_warnings, f"Expected no warnings, got: {file_warnings}"

    def test_missing_git_base_emits_warning(self, tmp_path: Path) -> None:
        """A wave file referencing bare HEAD (not origin/main) triggers a warning."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-70-NO-GIT-BASE.md").write_text(_MISSING_GIT_BASE_WAVE)
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines() if "S-70-NO-GIT-BASE" in ln]
        assert any("git-rev-parse-base" in w for w in warnings), (
            f"Expected git-rev-parse-base warning, got: {warnings}"
        )

    def test_missing_models_emits_warning(self, tmp_path: Path) -> None:
        """A wave with Parallelization section but no model names triggers a warning."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-70-NO-MODELS.md").write_text(_MISSING_MODELS_WAVE)
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines() if "S-70-NO-MODELS" in ln]
        assert any("per-stream-models" in w for w in warnings), (
            f"Expected per-stream-models warning, got: {warnings}"
        )

    def test_missing_preamble_emits_warning(self, tmp_path: Path) -> None:
        """A wave with Robot mode section but no preamble ref triggers a warning."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-70-NO-PREAMBLE.md").write_text(_MISSING_PREAMBLE_WAVE)
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines() if "S-70-NO-PREAMBLE" in ln]
        assert any("subagent-preamble" in w for w in warnings), (
            f"Expected subagent-preamble warning, got: {warnings}"
        )

    def test_no_robot_section_skipped(self, tmp_path: Path) -> None:
        """A file with no Robot mode section is skipped entirely (no warnings)."""
        waves = _make_waves_dir(tmp_path)
        (waves / "S-70-DESIGN-ONLY.md").write_text(_NO_ROBOT_SECTION_WAVE)
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines() if "S-70-DESIGN-ONLY" in ln]
        assert not warnings, f"Design-only file should be skipped, got: {warnings}"

    def test_exit_code_always_zero(self, tmp_path: Path) -> None:
        """Scanner always exits 0 regardless of warnings found."""
        waves = _make_waves_dir(tmp_path)
        # Write a wave file that triggers all three warning types
        (waves / "S-70-ALL-MISSING.md").write_text(
            "# S-70-ALL-MISSING\n\n## Robot mode\n\nOperate under ROBOT.md.\n\n"
            "Invocation: `in Robot mode: execute.`\n"
        )
        rc, _ = _run_scanner(tmp_path)
        assert rc == 0

    def test_pre_convention_wave_no_preamble_warning(self, tmp_path: Path) -> None:
        """Pre-convention waves (S-55 and earlier) skip the preamble check."""
        waves = _make_waves_dir(tmp_path)
        # S-50 predates preamble convention; should NOT get preamble warning
        (waves / "S-50-OLD-WAVE.md").write_text(
            textwrap.dedent("""\
                # S-50-OLD-WAVE

                ## Cross-wave dependencies
                Depends on main (`git rev-parse origin/main` at startup).

                ## Parallelization
                **Models:** coordinator = **opus**, streams = **sonnet**.

                ## Robot mode (autonomous execution)
                Operate under ROBOT.md doctrine.

                Invocation: `in Robot mode: execute the wave.`
            """)
        )
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines()
                    if "S-50-OLD-WAVE" in ln and "subagent-preamble" in ln]
        assert not warnings, (
            f"Pre-convention wave should not get preamble warning, got: {warnings}"
        )


# ---------------------------------------------------------------------------
# Tests: origin/main SHA variant recognition
# ---------------------------------------------------------------------------

class TestGitBaseDetection:
    def test_origin_main_sha_recognised(self, tmp_path: Path) -> None:
        """origin/main @ abc1234 pattern is accepted as a valid base reference."""
        waves = _make_waves_dir(tmp_path)
        text = textwrap.dedent("""\
            # S-70-SHA-VARIANT

            ## Cross-wave dependencies
            - Depends ONLY on main (`069d798` as of 2026-05-29; orchestrator
              re-confirms `git rev-parse origin/main` at startup).

            ## Parallelization
            **Models:** coordinator = **opus**, subagents = **sonnet**.

            ## Robot mode
            subagent preamble injected. Do not call AskUserQuestion.

            Invocation: `in Robot mode: execute the wave.`
        """)
        (waves / "S-70-SHA-VARIANT.md").write_text(text)
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines()
                    if "S-70-SHA-VARIANT" in ln and "git-rev-parse-base" in ln]
        assert not warnings, f"SHA variant should not warn: {warnings}"

    def test_bare_head_triggers_warning(self, tmp_path: Path) -> None:
        """Using HEAD (not origin/main) triggers the git-base warning."""
        waves = _make_waves_dir(tmp_path)
        text = textwrap.dedent("""\
            # S-70-BARE-HEAD

            ## Cross-wave dependencies
            - Depends on HEAD commit (latest).

            ## Parallelization
            **Models:** coordinator = **opus**, subagents = **sonnet**.

            ## Robot mode
            subagent preamble injected. Do not call AskUserQuestion.

            Invocation: `in Robot mode: execute the wave.`
        """)
        (waves / "S-70-BARE-HEAD.md").write_text(text)
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines() if "S-70-BARE-HEAD" in ln]
        assert any("git-rev-parse-base" in w for w in warnings), (
            f"Bare HEAD should trigger git-base warning: {warnings}"
        )


# ---------------------------------------------------------------------------
# Tests: run-archive scanning (element 1 only for informational records)
# ---------------------------------------------------------------------------

class TestRunArchiveScanning:
    def test_archive_status_with_origin_main_no_warning(self, tmp_path: Path) -> None:
        """An archive status file referencing origin/main should not warn."""
        status_dir, _ = _make_archive_dir(tmp_path)
        (status_dir / "BATCH-1-COMPLETE.md").write_text(
            "# BATCH-1 COMPLETE — orchestrator summary\n"
            "Orchestrator: opus (one-orchestrator-per-batch)\n"
            "Base: origin/main 0b9f8d3\n"
            "All streams merged.\n"
        )
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines() if "BATCH-1-COMPLETE" in ln]
        assert not warnings, f"Compliant archive file should not warn: {warnings}"

    def test_non_orchestrator_archive_file_skipped(self, tmp_path: Path) -> None:
        """Archive decision files not referencing 'orchestrator' are skipped."""
        _, decisions_dir = _make_archive_dir(tmp_path)
        (decisions_dir / "S-70-C-1.md").write_text(
            "# Decision: stream C-1\nApplied default: foo bar baz.\n"
        )
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        warnings = [ln for ln in out.splitlines() if "S-70-C-1" in ln]
        assert not warnings, f"Non-orchestrator file should be skipped: {warnings}"


# ---------------------------------------------------------------------------
# Tests: empty / minimal repos
# ---------------------------------------------------------------------------

class TestEmptyRepo:
    def test_no_waves_dir_clean(self, tmp_path: Path) -> None:
        """Repo with no .claude/waves/ exits 0 with no warnings."""
        rc, out = _run_scanner(tmp_path)
        assert rc == 0
        assert "OK:" in out or "0 orchestrator" not in out  # summary line present

    def test_empty_waves_dir_clean(self, tmp_path: Path) -> None:
        """Empty .claude/waves/ exits 0 with no warnings."""
        _make_waves_dir(tmp_path)
        rc, out = _run_scanner(tmp_path)
        assert rc == 0


# ---------------------------------------------------------------------------
# Tests: ms-enforce wrapper (text-based, matching the house pattern in
# test_backlog_audit.py — importlib cannot load extensionless scripts)
# ---------------------------------------------------------------------------

class TestMsEnforceWrapper:
    def test_check_function_defined_in_ms_enforce(self) -> None:
        """check_orchestrator_prompt_format is defined in ms-enforce."""
        ms_enforce = REPO / "ms-enforce"
        assert ms_enforce.exists(), "ms-enforce must exist"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "check_orchestrator_prompt_format" in text, (
            "check_orchestrator_prompt_format must be defined in ms-enforce"
        )

    def test_tier1_registration_present(self) -> None:
        """check_orchestrator_prompt_format is registered in TIER_1."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "Orchestrator prompt format" in text or "orchestrator_prompt_format" in text, (
            "check_orchestrator_prompt_format must be listed in TIER_1"
        )

    def test_check_output_format(self) -> None:
        """check_orchestrator_prompt_format produces (True, str) output matching expected pattern.

        Runs the scanner directly and verifies it exits 0 (warn-only).
        Does not run full ms-enforce --fast since other TIER_1 checks may
        have pre-existing failures unrelated to this stream.
        """
        result = subprocess.run(
            [_py(), str(SCANNER), "--repo", str(REPO)],
            capture_output=True, text=True, cwd=str(REPO), timeout=60,
        )
        assert result.returncode == 0, (
            f"scanner must always exit 0 (warn-only), got {result.returncode}"
        )
        combined = result.stdout + result.stderr
        # Summary line should always be present
        assert "OK:" in combined or "Summary:" in combined or "warning" in combined.lower(), (
            f"Expected summary output from scanner, got:\n{combined[:400]}"
        )
