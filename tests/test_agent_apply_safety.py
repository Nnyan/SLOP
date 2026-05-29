"""tests/test_agent_apply_safety.py

Integration tests for the backoff + verify health gates added to
backend/agent/apply.py (wave S-60-C).

All external dependencies are mocked:
  - backend.agent.backoff.attempt_allowed / record_attempt
  - backend.agent.verify.verify_container_healthy
  - subprocess.run  (so no real docker calls are made)
  - backend.core.state.StateDB  (so no real DB calls are made)

Three paths covered:
  (a) allow → returncode 0 → verify healthy   → _mark_applied called, ok True
  (b) allow → returncode 0 → verify NOT healthy → _mark_failed called,
        _mark_applied NOT called, ok False
  (c) deny-by-backoff → no action, no verify, ok False, returns reason
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    app_key: str = "testapp",
    diagnosis_class: str = "CRASH_LOOP",
    suggested_fix: str = "Restart the container",
    fix_metadata: str = "{}",
) -> dict:
    """Return a dict-like row as apply_safe_fix expects."""
    return {
        "app_key": app_key,
        "diagnosis_class": diagnosis_class,
        "suggested_fix": suggested_fix,
        "fix_metadata": fix_metadata,
    }


def _noop_state_db():
    """Return a MagicMock context manager that acts as an inert StateDB."""
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute = MagicMock(return_value=mock_db)
    mock_db.fetchall = MagicMock(return_value=[])
    return mock_db


# ---------------------------------------------------------------------------
# (a) allow → docker returncode 0 → container healthy → _mark_applied + ok True
# ---------------------------------------------------------------------------

def test_allow_success_healthy(monkeypatch):
    """apply_safe_fix: backoff allows, docker succeeds, verify healthy
    → _mark_applied is called once, record_attempt called with 'success',
    result ok=True.
    """
    import backend.agent.apply as apply_mod

    row = _make_row(diagnosis_class="CRASH_LOOP")
    fix_id = 42

    # Backoff allows
    monkeypatch.setattr(apply_mod, "attempt_allowed", lambda *a, **k: (True, "allowed"))

    # Docker subprocess succeeds (returncode 0)
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    monkeypatch.setattr("subprocess.run", MagicMock(return_value=mock_proc))

    # Verify returns healthy
    monkeypatch.setattr(
        apply_mod, "verify_container_healthy",
        lambda app_key, **k: (True, "container running, health=none (confirmed on attempt 1/5)"),
    )

    # Record attempt
    record_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "record_attempt", record_mock)

    # StateDB — prevent real DB use
    state_mock = _noop_state_db()
    monkeypatch.setattr(apply_mod, "StateDB", MagicMock(return_value=state_mock))

    # Spy on _mark_applied / _mark_failed
    mark_applied_mock = MagicMock()
    mark_failed_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "_mark_applied", mark_applied_mock)
    monkeypatch.setattr(apply_mod, "_mark_failed", mark_failed_mock)

    result = apply_mod.apply_safe_fix(fix_id, row)

    assert result["ok"] is True
    assert result["fix_type"] == "restart_container"
    mark_applied_mock.assert_called_once_with(fix_id, "testapp", row, "restart_container")
    mark_failed_mock.assert_not_called()
    record_mock.assert_called_once_with("testapp", "restart_container", "success")


# ---------------------------------------------------------------------------
# (b) allow → docker returncode 0 → container NOT healthy → _mark_failed + ok False
# ---------------------------------------------------------------------------

def test_allow_success_verify_fail(monkeypatch):
    """apply_safe_fix: backoff allows, docker succeeds, verify NOT healthy
    → _mark_failed called, _mark_applied NOT called,
    record_attempt called with 'failed_verification', result ok=False.
    """
    import backend.agent.apply as apply_mod

    row = _make_row(diagnosis_class="CRASH_LOOP")
    fix_id = 7

    monkeypatch.setattr(apply_mod, "attempt_allowed", lambda *a, **k: (True, "allowed"))

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    monkeypatch.setattr("subprocess.run", MagicMock(return_value=mock_proc))

    # Verify returns NOT healthy
    monkeypatch.setattr(
        apply_mod, "verify_container_healthy",
        lambda app_key, **k: (False, "not healthy after 5 attempts; status=restarting, health=none"),
    )

    record_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "record_attempt", record_mock)

    state_mock = _noop_state_db()
    monkeypatch.setattr(apply_mod, "StateDB", MagicMock(return_value=state_mock))

    mark_applied_mock = MagicMock()
    mark_failed_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "_mark_applied", mark_applied_mock)
    monkeypatch.setattr(apply_mod, "_mark_failed", mark_failed_mock)

    result = apply_mod.apply_safe_fix(fix_id, row)

    assert result["ok"] is False
    assert result["fix_type"] == "restart_container"
    assert "not healthy" in result["message"] or "restarting" in result["message"]
    mark_failed_mock.assert_called_once_with(fix_id, "testapp", row, "restart_container")
    mark_applied_mock.assert_not_called()
    record_mock.assert_called_once_with("testapp", "restart_container", "failed_verification")


# ---------------------------------------------------------------------------
# (c) deny-by-backoff → no docker action, no verify, ok False, returns reason
# ---------------------------------------------------------------------------

def test_deny_by_backoff(monkeypatch):
    """apply_safe_fix: backoff denies → no subprocess, no verify,
    record_attempt NOT called, result ok=False with the deny reason.
    """
    import backend.agent.apply as apply_mod

    row = _make_row(diagnosis_class="CRASH_LOOP")
    fix_id = 99
    deny_reason = (
        "backoff: 3 attempts for testapp/restart_container in the last 3600s (max 3)"
    )

    # Backoff denies
    monkeypatch.setattr(
        apply_mod, "attempt_allowed", lambda *a, **k: (False, deny_reason)
    )

    # subprocess.run must NOT be called
    subprocess_mock = MagicMock()
    monkeypatch.setattr("subprocess.run", subprocess_mock)

    # verify_container_healthy must NOT be called
    verify_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "verify_container_healthy", verify_mock)

    record_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "record_attempt", record_mock)

    state_mock = _noop_state_db()
    monkeypatch.setattr(apply_mod, "StateDB", MagicMock(return_value=state_mock))

    mark_applied_mock = MagicMock()
    mark_failed_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "_mark_applied", mark_applied_mock)
    monkeypatch.setattr(apply_mod, "_mark_failed", mark_failed_mock)

    result = apply_mod.apply_safe_fix(fix_id, row)

    assert result["ok"] is False
    assert result["fix_type"] == "restart_container"
    assert deny_reason in result["message"]

    subprocess_mock.assert_not_called()
    verify_mock.assert_not_called()
    record_mock.assert_not_called()
    mark_applied_mock.assert_not_called()
    mark_failed_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Additional: repull_restart path also runs verify + record_attempt
# ---------------------------------------------------------------------------

def test_repull_restart_allow_success_healthy(monkeypatch):
    """repull_restart path: backoff allows, docker succeeds, verify healthy → ok True."""
    import backend.agent.apply as apply_mod

    row = _make_row(
        diagnosis_class="IMAGE_PULL_FAIL",
        fix_metadata='{"image": "myapp:latest"}',
    )
    fix_id = 11

    monkeypatch.setattr(apply_mod, "attempt_allowed", lambda *a, **k: (True, "allowed"))
    monkeypatch.setattr("subprocess.run", MagicMock(return_value=MagicMock(returncode=0)))
    monkeypatch.setattr(
        apply_mod, "verify_container_healthy",
        lambda app_key, **k: (True, "container running, health=none"),
    )

    record_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "record_attempt", record_mock)

    state_mock = _noop_state_db()
    monkeypatch.setattr(apply_mod, "StateDB", MagicMock(return_value=state_mock))

    mark_applied_mock = MagicMock()
    mark_failed_mock = MagicMock()
    monkeypatch.setattr(apply_mod, "_mark_applied", mark_applied_mock)
    monkeypatch.setattr(apply_mod, "_mark_failed", mark_failed_mock)

    result = apply_mod.apply_safe_fix(fix_id, row)

    assert result["ok"] is True
    assert result["fix_type"] == "repull_restart"
    mark_applied_mock.assert_called_once()
    mark_failed_mock.assert_not_called()
    record_mock.assert_called_once_with("testapp", "repull_restart", "success")
