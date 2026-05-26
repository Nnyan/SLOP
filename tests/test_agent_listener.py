"""tests/test_agent_listener.py

Unit tests for backend/agent/listener.py — Phase A of the LLM agent.

Coverage:
  - Error step writes a pending_fixes row with diagnosis_class='UNKNOWN'
  - Non-error steps (running, done) do not write anything
  - DB failure does not propagate — listener is a no-op on exception

StateDB fixture pattern: same as test_api_coverage.py / test_install_inner_refactor.py.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core.state as _state_mod
from backend.core.state import StateDB, init_db
from backend.agent.listener import install_failure_listener, _write_pending_fix


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated database for each test — same pattern as test_api_coverage."""
    p = tmp_path / "state.db"
    init_db(p)
    _state_mod.configure(p)
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_step(detail: str = "permission denied on /config") -> dict:
    return {"name": "deploy", "status": "error", "message": "Deploy failed", "detail": detail}


def _ok_step(status: str = "ok") -> dict:
    return {"name": "deploy", "status": status, "message": "All good", "detail": ""}


def _get_pending_fixes(db_path: Path) -> list[dict]:
    """Return all rows from pending_fixes as plain dicts."""
    with StateDB() as db:
        rows = db.execute("SELECT * FROM pending_fixes").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInstallFailureListener:

    def test_error_step_writes_pending_fix(self, db_path: Path) -> None:
        """Error step creates a pending_fixes row with diagnosis_class='UNKNOWN'."""
        asyncio.run(
            install_failure_listener("sonarr", _error_step("permission denied on /config"))
        )
        rows = _get_pending_fixes(db_path)
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}: {rows}"
        row = rows[0]
        assert row["app_key"] == "sonarr"
        assert row["check_name"] == "install_monitor"
        assert row["action_type"] == "diagnose"
        assert row["diagnosis_class"] == "UNKNOWN"
        assert row["status"] == "pending"
        assert row["confidence"] == 0.0
        assert "permission denied" in row["problem"]
        assert "Diagnosis pending" in row["suggested_fix"]

    def test_non_error_step_is_ignored(self, db_path: Path) -> None:
        """Non-error steps (running, done) do not write pending_fixes."""
        asyncio.run(install_failure_listener("radarr", _ok_step("ok")))
        asyncio.run(install_failure_listener("radarr", _ok_step("running")))
        asyncio.run(install_failure_listener("radarr", _ok_step("done")))
        rows = _get_pending_fixes(db_path)
        assert rows == [], f"Expected no rows but got: {rows}"

    def test_listener_is_noop_on_db_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DB failure does not propagate — listener swallows exceptions.

        StateDB is imported lazily inside the listener, so we patch it on
        the backend.core.state module (where it lives) rather than on
        backend.agent.listener.
        """
        bad_db = MagicMock()
        bad_db.__enter__ = MagicMock(side_effect=RuntimeError("DB exploded"))
        bad_db.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(
            "backend.core.state.StateDB",
            MagicMock(return_value=bad_db),
        )

        # Must not raise
        asyncio.run(
            install_failure_listener("jackett", _error_step("some error"))
        )
        # If we reach here, the listener swallowed the exception — test passes.
