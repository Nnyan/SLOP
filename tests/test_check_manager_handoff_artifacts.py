"""Tests for ms-enforce check_manager_handoff_artifacts (BATCH-11 S11, F10).

The two-session Manager-handoff-artifact contract gate. GROUND on the filesystem
(`.claude/waves/`); the back-reference token
`<!-- manager-handoff-prompt: <path> -->` is the discriminator.

Red-path (mandatory):
  (a) a working *-LAUNCH-PROMPT.md with a DANGLING/absent back-reference → DRIFT
  (b) a legitimately paired A (Manager-handoff prompt) + B (launch prompt that
      back-references A) → verified

Plus: no token at all → INCONSISTENT (not a silent pass); empty/absent dir →
INDETERMINATE; newest being a Manager-handoff prompt → verified.

All tests use tmp_path only — no live repo reads.
"""
from __future__ import annotations

import os
import time
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_ms_enforce() -> types.ModuleType:
    """Load the ms-enforce script (no .py extension) as a module."""
    ms_path = REPO_ROOT / "ms-enforce"
    src = ms_path.read_text(encoding="utf-8")
    code = compile(src, str(ms_path), "exec")
    mod = types.ModuleType("ms_enforce")
    mod.__file__ = str(ms_path)
    exec(code, mod.__dict__)  # noqa: S102
    return mod


def _run_gate_with_repo(tmp_path: Path) -> tuple[bool, str]:
    """Load a fresh ms-enforce with REPO + _MH_WAVES_DIR pointing at tmp_path.

    Both must be repointed: _MH_WAVES_DIR is bound from REPO at module-load.
    """
    mod = _load_ms_enforce()
    mod.REPO = tmp_path  # type: ignore[attr-defined]
    mod._MH_WAVES_DIR = tmp_path / ".claude" / "waves"  # type: ignore[attr-defined]
    return mod.check_manager_handoff_artifacts()  # type: ignore[no-any-return]


def _waves(tmp_path: Path) -> Path:
    d = tmp_path / ".claude" / "waves"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_newest(path: Path, content: str) -> None:
    """Write a file and bump its mtime so it is unambiguously the newest."""
    path.write_text(content, encoding="utf-8")
    future = time.time() + 100
    os.utime(path, (future, future))


# ── (a) RED PATH: dangling back-reference → DRIFT ─────────────────────────────

def test_dangling_backreference_drifts(tmp_path: Path) -> None:
    waves = _waves(tmp_path)
    launch = waves / "BATCH-99-LAUNCH-PROMPT.md"
    launch.write_text(
        "# BATCH-99 launch\n"
        "<!-- manager-handoff-prompt: .claude/waves/BATCH-99-MANAGER-HANDOFF-PROMPT.md -->\n"
        "paste me\n",
        encoding="utf-8",
    )
    # NOTE: artifact A (the Manager-handoff prompt) is deliberately NOT created.
    passed, msg = _run_gate_with_repo(tmp_path)
    assert passed is True  # warn-only — never blocks
    assert "DRIFT" in msg
    assert "BATCH-99-MANAGER-HANDOFF-PROMPT.md" in msg
    assert "malformed by construction" in msg


# ── (b) HAPPY PATH: paired A + B (B back-references A) → verified ─────────────

def test_paired_a_and_b_verified(tmp_path: Path) -> None:
    waves = _waves(tmp_path)
    # Artifact A — the Manager-handoff prompt (exists on disk).
    handoff = waves / "BATCH-99-MANAGER-HANDOFF-PROMPT.md"
    handoff.write_text("# BATCH-99 Manager handoff\nstate + pointers\n", encoding="utf-8")
    # Artifact B — the launch prompt that back-references A. Make B newest.
    launch = waves / "BATCH-99-LAUNCH-PROMPT.md"
    _write_newest(
        launch,
        "# BATCH-99 launch\n"
        "<!-- manager-handoff-prompt: .claude/waves/BATCH-99-MANAGER-HANDOFF-PROMPT.md -->\n"
        "paste me\n",
    )
    passed, msg = _run_gate_with_repo(tmp_path)
    assert passed is True
    assert "verified" in msg
    assert "DRIFT" not in msg
    assert "INCONSISTENT" not in msg


# ── launch prompt with NO token → INCONSISTENT (not a silent pass) ────────────

def test_launch_prompt_without_token_inconsistent(tmp_path: Path) -> None:
    waves = _waves(tmp_path)
    launch = waves / "BATCH-99-LAUNCH-PROMPT.md"
    launch.write_text("# BATCH-99 launch\npaste me, no back-reference token\n", encoding="utf-8")
    passed, msg = _run_gate_with_repo(tmp_path)
    assert passed is True
    assert "INCONSISTENT" in msg
    assert "DRIFT" not in msg


# ── newest is a Manager-handoff prompt → verified (artifact A present) ─────────

def test_newest_is_manager_handoff_verified(tmp_path: Path) -> None:
    waves = _waves(tmp_path)
    (waves / "BATCH-99-LAUNCH-PROMPT.md").write_text("# old launch\n", encoding="utf-8")
    handoff = waves / "BATCH-99-MANAGER-HANDOFF-PROMPT.md"
    _write_newest(handoff, "# BATCH-99 Manager handoff (newest)\n")
    passed, msg = _run_gate_with_repo(tmp_path)
    assert passed is True
    assert "verified" in msg
    assert "artifact A present" in msg


# ── empty / absent waves dir → INDETERMINATE (ground unreachable, no false OK) ─

def test_no_waves_dir_indeterminate(tmp_path: Path) -> None:
    passed, msg = _run_gate_with_repo(tmp_path)  # no .claude/waves/ created
    assert passed is True
    assert "INDETERMINATE" in msg


def test_empty_waves_dir_indeterminate(tmp_path: Path) -> None:
    _waves(tmp_path)  # created but empty
    passed, msg = _run_gate_with_repo(tmp_path)
    assert passed is True
    assert "INDETERMINATE" in msg
