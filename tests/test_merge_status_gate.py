"""Red-path tests for the merge-time RED-ON-MISSING-STATUS gate (batch-11 S5/P5).

Covers tools/merge_wave_to_main.py::check_status_gate — the GROUND-class gate
that refuses a merge when the wave's status file is missing or its first-line
State is non-terminal. All fixtures are under tmp_path (no live repo reads).

Verdict contract (ROBOT.md §3.5):
  - missing status file           → DRIFT (refuse) — NOT a silent skip
  - present but no **State:** line → DRIFT (refuse)
  - State: RUNNING                → DRIFT (refuse — run not finished)
  - State: BLOCKED / NEEDS-INPUT  → BLOCKED (refuse — open blocker blocks merge)
  - State: COMPLETE / CLOSED      → verified (pass)
  - inexact filename match        → still evaluates State legs + emits WARNING
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MERGE_TOOL = Path(__file__).parent.parent / "tools" / "merge_wave_to_main.py"


def _load_merge():
    spec = importlib.util.spec_from_file_location("merge_wave_to_main_statusgate", _MERGE_TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["merge_wave_to_main_statusgate"] = mod
    spec.loader.exec_module(mod)
    return mod


mwm = _load_merge()


def _status_dir(root: Path) -> Path:
    d = root / ".claude" / "run" / "status"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_status(root: Path, name: str, body: str) -> Path:
    p = _status_dir(root) / name
    p.write_text(body, encoding="utf-8")
    return p


# ── red paths (refuse) ─────────────────────────────────────────────────────────

def test_missing_status_file_refuses(tmp_path):
    """No status file → DRIFT (refuse), the keystone red path (not a silent skip)."""
    _status_dir(tmp_path)  # dir exists, no file
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is False
    assert "DRIFT" in msg
    assert "GROUND: filesystem" in msg


def test_no_state_marker_refuses(tmp_path):
    """Status file present but no **State:** marker → DRIFT (refuse)."""
    _write_status(tmp_path, "S-99.md", "# S-99 status\nCOMPLETE somewhere in body\n")
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is False
    assert "DRIFT" in msg
    assert "no `**State:**` marker" in msg


def test_running_state_refuses(tmp_path):
    """Non-terminal State RUNNING → DRIFT (refuse — run not finished)."""
    _write_status(tmp_path, "S-99.md", "**State:** RUNNING\n# S-99 status\n")
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is False
    assert "DRIFT" in msg
    assert "RUNNING" in msg


def test_blocked_state_blocks_merge(tmp_path):
    """State BLOCKED → refuse with a BLOCKED verdict (open blocker blocks merge)."""
    _write_status(tmp_path, "S-99.md", "**State:** BLOCKED\n# S-99 status\n")
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is False
    assert "BLOCKED" in msg


def test_needs_input_state_blocks_merge(tmp_path):
    """State NEEDS-INPUT → refuse (blocking state)."""
    _write_status(tmp_path, "S-99.md", "**State:** NEEDS-INPUT\n# S-99 status\n")
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is False
    assert "NEEDS-INPUT" in msg


# ── green paths (pass) ───────────────────────────────────────────────────────

def test_complete_state_passes(tmp_path):
    """Terminal State COMPLETE → verified (pass)."""
    _write_status(tmp_path, "S-99.md", "**State:** COMPLETE\n# S-99 status\n")
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is True
    assert "verified" in msg


def test_closed_state_passes(tmp_path):
    """Terminal State CLOSED → verified (pass)."""
    _write_status(tmp_path, "S-99.md", "**State:** CLOSED\n# done\n")
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is True
    assert "verified" in msg


# ── inexact-name glob fallback (warn, but evaluate) ──────────────────────────

def test_inexact_filename_warns_but_evaluates(tmp_path):
    """A misnamed status file is found via glob fallback → WARNING + State legs run."""
    _write_status(tmp_path, "S-99-KNOWLEDGE-LIFECYCLE.md",
                  "**State:** COMPLETE\n# long-named status\n")
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is True
    assert "WARNING" in msg
    assert "INEXACT" in msg
    assert "verified" in msg


def test_state_marker_tolerates_leading_title(tmp_path):
    """Marker on a line after a leading title is still found (within first few lines)."""
    _write_status(tmp_path, "S-99.md", "# S-99 status\n**State:** COMPLETE\n")
    passed, msg = mwm.check_status_gate("S-99", tmp_path)
    assert passed is True
    assert "verified" in msg


# ── .handoff-sha auto-stamp (R6) ─────────────────────────────────────────────

def test_stamp_handoff_sha_writes_sha_token_first(tmp_path):
    """_stamp_handoff_sha writes the SHA as the first whitespace token.

    The first token must be readable by check_handoff_freshness._read_declared_sha,
    so a downstream gate reads 'verified' once origin/main equals this SHA (post-push).
    """
    sha = "abc1234def5678abc1234def5678abc1234def56"
    path = mwm._stamp_handoff_sha(tmp_path, sha)
    assert path == tmp_path / ".handoff-sha"
    first_token = path.read_text(encoding="utf-8").split()[0]
    assert first_token == sha
    # The 1-commit-lag note is documented in the artifact itself (not hidden).
    body = path.read_text(encoding="utf-8")
    assert "AUTO-STAMPED" in body
    assert "push" in body.lower()
