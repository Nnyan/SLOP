"""tests/test_agent_backoff.py

Unit tests for backend/agent/backoff.py — restart-oscillation guard.

Coverage:
  (a) fresh app (no prior attempts) → allowed
  (b) >= max_attempts within window  → denied
  (c) within backoff interval since last attempt → denied
  (d) after backoff interval elapsed → allowed again
  (e) record_attempt swallows a DB error without raising

Time is controlled via monkeypatching backoff._now — no real sleeps.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core.state as _state_mod
from backend.core.state import StateDB, init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated fresh database — applies all migrations (including 008)."""
    p = tmp_path / "state.db"
    init_db(p)
    _state_mod.configure(p)
    return p


@pytest.fixture(autouse=True)
def reset_clock(monkeypatch):
    """Reset the monkeypatchable clock to real time.time after each test."""
    import backend.agent.backoff as backoff_mod
    import time

    monkeypatch.setattr(backoff_mod, "_now", time.time)
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_clock(monkeypatch, ts: float) -> None:
    """Pin backoff._now to return ts."""
    import backend.agent.backoff as backoff_mod

    monkeypatch.setattr(backoff_mod, "_now", lambda: ts)


def _insert_attempt(db_path: Path, app_key: str, fix_type: str, outcome: str, created_at: int) -> None:
    """Directly insert a fix_attempts row (bypasses record_attempt for time control)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO fix_attempts (app_key, fix_type, outcome, created_at) VALUES (?, ?, ?, ?)",
        (app_key, fix_type, outcome, created_at),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# (a) Fresh app — no prior attempts → allowed
# ---------------------------------------------------------------------------


def test_fresh_app_allowed(db_path: Path, monkeypatch) -> None:
    from backend.agent.backoff import attempt_allowed

    _set_clock(monkeypatch, 1_000_000.0)
    allowed, reason = attempt_allowed("myapp", "restart_container")

    assert allowed is True
    assert "allowed" in reason


# ---------------------------------------------------------------------------
# (b) >= max_attempts within window → denied
# ---------------------------------------------------------------------------


def test_max_attempts_within_window_denied(db_path: Path, monkeypatch) -> None:
    from backend.agent.backoff import attempt_allowed

    now = 1_000_000.0
    _set_clock(monkeypatch, now)

    # Insert 3 attempts inside the 3600s window
    for delta in [3500, 2000, 100]:
        _insert_attempt(db_path, "flapper", "restart_container", "success", int(now - delta))

    allowed, reason = attempt_allowed("flapper", "restart_container", max_attempts=3, window_s=3600)

    assert allowed is False
    assert "3 attempts" in reason or "backoff" in reason


# ---------------------------------------------------------------------------
# (c) Within backoff interval since last attempt → denied
# ---------------------------------------------------------------------------


def test_within_backoff_interval_denied(db_path: Path, monkeypatch) -> None:
    from backend.agent.backoff import attempt_allowed

    now = 1_000_000.0
    _set_clock(monkeypatch, now)

    # One prior attempt 30s ago; backoff_base_s=60, n=1 → must_wait=60*(2^0)=60s
    _insert_attempt(db_path, "bouncer", "restart_container", "success", int(now - 30))

    allowed, reason = attempt_allowed(
        "bouncer", "restart_container", max_attempts=3, window_s=3600, backoff_base_s=60
    )

    assert allowed is False
    assert "backoff" in reason


# ---------------------------------------------------------------------------
# (d) After backoff interval elapsed → allowed again
# ---------------------------------------------------------------------------


def test_after_backoff_interval_allowed(db_path: Path, monkeypatch) -> None:
    from backend.agent.backoff import attempt_allowed

    now = 1_000_000.0
    _set_clock(monkeypatch, now)

    # One prior attempt 70s ago; backoff_base_s=60, n=1 → must_wait=60s → 70s > 60s → OK
    _insert_attempt(db_path, "recovered", "restart_container", "success", int(now - 70))

    allowed, reason = attempt_allowed(
        "recovered", "restart_container", max_attempts=3, window_s=3600, backoff_base_s=60
    )

    assert allowed is True
    assert "allowed" in reason


# ---------------------------------------------------------------------------
# (e) record_attempt swallows DB error without raising
# ---------------------------------------------------------------------------


def test_record_attempt_swallows_db_error(db_path: Path, monkeypatch) -> None:
    """record_attempt must never raise even when the DB write fails."""
    import backend.agent.backoff as backoff_mod
    from unittest.mock import patch, MagicMock

    # Patch StateDB.__enter__ to raise an OperationalError
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(side_effect=Exception("db exploded"))
    mock_cm.__exit__ = MagicMock(return_value=False)

    with patch.object(backoff_mod, "StateDB", return_value=mock_cm):
        # Must not raise — not even AssertionError
        backoff_mod.record_attempt("any_app", "restart_container", "success")


# ---------------------------------------------------------------------------
# Additional: second attempt uses 2x backoff (n=2 → must_wait=120s)
# ---------------------------------------------------------------------------


def test_second_attempt_backoff_doubles(db_path: Path, monkeypatch) -> None:
    from backend.agent.backoff import attempt_allowed

    now = 1_000_000.0
    _set_clock(monkeypatch, now)

    # Two prior attempts; n=2 → must_wait=60*(2^1)=120s
    # Last attempt was 100s ago → still within 120s → denied
    _insert_attempt(db_path, "doubler", "restart_container", "success", int(now - 3000))
    _insert_attempt(db_path, "doubler", "restart_container", "success", int(now - 100))

    allowed, reason = attempt_allowed(
        "doubler", "restart_container", max_attempts=5, window_s=3600, backoff_base_s=60
    )

    assert allowed is False

    # 130s since last attempt → past 120s window → allowed
    _set_clock(monkeypatch, now + 30)  # move clock so last attempt was 130s ago
    allowed2, _ = attempt_allowed(
        "doubler", "restart_container", max_attempts=5, window_s=3600, backoff_base_s=60
    )

    assert allowed2 is True


# ---------------------------------------------------------------------------
# record_attempt actually inserts a row
# ---------------------------------------------------------------------------


def test_record_attempt_inserts_row(db_path: Path) -> None:
    from backend.agent.backoff import record_attempt

    record_attempt("myapp", "restart_container", "success")

    with StateDB() as db:
        rows = db.execute(
            "SELECT * FROM fix_attempts WHERE app_key=? AND fix_type=?",
            ("myapp", "restart_container"),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["outcome"] == "success"
