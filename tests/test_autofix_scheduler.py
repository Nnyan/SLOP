"""tests/test_autofix_scheduler.py — S-64 Stream B.

Unit tests for backend.health.scheduler._maybe_auto_apply_safe_fixes.

The four required scenarios:
  1. enabled + safe high-confidence pending → apply_safe_fix invoked
  2. disabled (DEFAULT, no settings) → no-op (default-OFF assertion)
  3. low-confidence → skipped (select_auto_applicable returns [])
  4. apply_safe_fix raising → swallowed, loop continues (no exception propagates)

Patching strategy: _maybe_auto_apply_safe_fixes uses lazy (in-function) imports
from backend.agent.autofix and backend.agent.apply.  We therefore patch at the
source modules rather than at backend.health.scheduler.* (which has no module-
level bindings for these names).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core.state as _state_mod
from backend.core.state import StateDB, init_db

# Import the function under test
from backend.health.scheduler import _maybe_auto_apply_safe_fixes


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated fresh database — applies all migrations via init_db."""
    p = tmp_path / "state.db"
    init_db(p)
    _state_mod.configure(p)
    return p


def _make_row(
    fix_id: int = 1,
    app_key: str = "dozzle",
    diagnosis_class: str = "CRASH_LOOP",
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Build a minimal dict-like row matching what select_auto_applicable returns."""
    return {
        "id": fix_id,
        "app_key": app_key,
        "diagnosis_class": diagnosis_class,
        "confidence": confidence,
        "status": "pending",
        "suggested_fix": "restart container",
        "fix_metadata": "{}",
    }


def _enable_autofix(min_confidence: str = "0.9") -> None:
    """Set autofix settings in the current configured StateDB."""
    with StateDB() as db:
        db.set_setting("agent_autofix_enabled", "true")
        db.set_setting("agent_autofix_min_confidence", min_confidence)


# ---------------------------------------------------------------------------
# 1. Enabled + safe high-confidence pending → apply_safe_fix invoked
# ---------------------------------------------------------------------------


def test_enabled_high_confidence_applies(db_path: Path) -> None:
    """When autofix is enabled and a safe high-confidence fix is pending,
    apply_safe_fix must be called exactly once for that row."""
    _enable_autofix()
    row = _make_row(fix_id=42, confidence=0.95)

    mock_select = MagicMock(return_value=[row])
    mock_apply = MagicMock(return_value={"ok": True, "message": "restarted"})

    with (
        patch("backend.agent.autofix.select_auto_applicable", mock_select),
        patch("backend.agent.apply.apply_safe_fix", mock_apply),
    ):
        _maybe_auto_apply_safe_fixes()

    mock_apply.assert_called_once_with(42, row)


# ---------------------------------------------------------------------------
# 2. Disabled by default (no settings present) → no-op
# ---------------------------------------------------------------------------


def test_disabled_by_default_no_apply(db_path: Path) -> None:
    """With no settings present (fresh DB), autofix must NOT call apply_safe_fix.
    This is the explicit default-OFF assertion required by the wave spec."""
    # db_path fixture sets up fresh DB with no autofix settings
    mock_apply = MagicMock()

    with patch("backend.agent.apply.apply_safe_fix", mock_apply):
        _maybe_auto_apply_safe_fixes()

    mock_apply.assert_not_called()


def test_explicitly_disabled_no_apply(db_path: Path) -> None:
    """When agent_autofix_enabled is explicitly set to 'false', no apply occurs."""
    with StateDB() as db:
        db.set_setting("agent_autofix_enabled", "false")

    mock_apply = MagicMock()
    row = _make_row(fix_id=1, confidence=0.99)

    with (
        patch("backend.agent.autofix.select_auto_applicable", return_value=[row]),
        patch("backend.agent.apply.apply_safe_fix", mock_apply),
    ):
        _maybe_auto_apply_safe_fixes()

    mock_apply.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Low-confidence → skipped (select_auto_applicable returns [])
# ---------------------------------------------------------------------------


def test_low_confidence_skipped(db_path: Path) -> None:
    """When select_auto_applicable returns [] (all rows below threshold),
    apply_safe_fix must never be called."""
    _enable_autofix(min_confidence="0.9")

    # select returns empty because low confidence is filtered by the autofix module
    mock_select = MagicMock(return_value=[])
    mock_apply = MagicMock()

    with (
        patch("backend.agent.autofix.select_auto_applicable", mock_select),
        patch("backend.agent.apply.apply_safe_fix", mock_apply),
    ):
        _maybe_auto_apply_safe_fixes()

    mock_apply.assert_not_called()
    mock_select.assert_called_once_with(min_confidence=0.9)


# ---------------------------------------------------------------------------
# 4. apply_safe_fix raising → swallowed, loop continues
# ---------------------------------------------------------------------------


def test_apply_safe_fix_raising_is_swallowed(db_path: Path) -> None:
    """If apply_safe_fix raises for one row, the exception must not propagate
    out of _maybe_auto_apply_safe_fixes — the loop continues for remaining rows."""
    _enable_autofix()
    row1 = _make_row(fix_id=10, app_key="app_a", confidence=0.99)
    row2 = _make_row(fix_id=11, app_key="app_b", diagnosis_class="IMAGE_PULL_FAIL",
                     confidence=0.95)

    call_log: list[int] = []

    def _flaky_apply(fix_id: int, row: Any) -> dict[str, Any]:
        if fix_id == 10:
            raise RuntimeError("docker daemon unavailable")
        call_log.append(fix_id)
        return {"ok": True, "message": "ok"}

    with (
        patch("backend.agent.autofix.select_auto_applicable", return_value=[row1, row2]),
        patch("backend.agent.apply.apply_safe_fix", side_effect=_flaky_apply),
    ):
        # Must not raise
        _maybe_auto_apply_safe_fixes()

    # row2 (fix_id=11) should still have been attempted despite row1 raising
    assert 11 in call_log


# ---------------------------------------------------------------------------
# 5. Config read failure → silently returns (never raises)
# ---------------------------------------------------------------------------


def test_config_read_failure_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """If StateDB raises during config read, _maybe_auto_apply_safe_fixes
    must not propagate the exception."""
    import backend.core.state as state_mod

    class _BoomStateDB:
        def __enter__(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("DB unavailable")

        def __exit__(self, *a: Any) -> bool:
            return False

    original_statedb = state_mod.StateDB
    monkeypatch.setattr(state_mod, "StateDB", _BoomStateDB)

    try:
        # Must not raise
        _maybe_auto_apply_safe_fixes()
    finally:
        monkeypatch.setattr(state_mod, "StateDB", original_statedb)
