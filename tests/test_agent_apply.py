"""tests/test_agent_apply.py

Unit tests for Phase E: safe auto-apply tier.

Coverage (≥4 required):
  1. test_apply_restart_container_success
       Mock subprocess; POST /fixes/{id}/apply for CRASH_LOOP fix →
       200, DB row status='applied', fix_history row inserted.
  2. test_apply_restart_container_subprocess_failure
       Mock subprocess raising CalledProcessError →
       500, DB row status still 'pending'.
  3. test_apply_unsafe_fix_returns_422
       POST /fixes/{id}/apply for PORT_CONFLICT (no safe mapping) → 422.
  4. test_apply_fix_not_found_returns_404
       POST /fixes/9999/apply with empty DB → 404.
  5. test_apply_repull_restart_success  (optional)
       Mock subprocess; IMAGE_PULL_FAIL fix → 200, two docker calls.
  6. test_apply_no_longer_returns_501  (regression guard)
       The old stub returned 501; confirm any valid fix returns something
       other than 501.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core.state as _state_mod
from backend.core.state import StateDB, init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_manifest_cache():
    """Clear manifest cache before/after every test (matches smoke suite)."""
    from backend.manifests.loader import clear_cache

    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated fresh database — applies all migrations via init_db."""
    p = tmp_path / "state.db"
    init_db(p)
    _state_mod.configure(p)
    return p


@pytest.fixture
def client(db_path: Path):
    """TestClient wired to the isolated DB."""
    import backend.core.config as cm
    from backend.api.main import app

    with patch.object(type(cm.config), "db_path", property(lambda self: db_path)):
        _state_mod.configure(db_path)
        with TestClient(app, base_url="http://localhost") as c:
            yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_fix(
    db_path: Path,
    app_key: str = "dozzle",
    problem: str = "Container keeps restarting",
    diagnosis_class: str = "CRASH_LOOP",
    suggested_fix: str = "Restart the container to clear the crash loop.",
    confidence: float = 0.85,
    status: str = "pending",
    fix_metadata: str = "{}",
) -> int:
    """Insert a pending_fixes row; return the new row id."""
    with StateDB() as db:
        cur = db.execute(
            """
            INSERT INTO pending_fixes
                (app_key, check_name, action_type, problem, suggested_fix,
                 confidence, status, diagnosis_class, fix_metadata)
            VALUES (?, 'install_monitor', 'diagnose', ?, ?, ?, ?, ?, ?)
            """,
            (app_key, problem, suggested_fix, confidence, status, diagnosis_class, fix_metadata),
        )
        return cur.lastrowid


def _row_status(db_path: Path, fix_id: int) -> str:
    """Fetch the status of a pending_fixes row."""
    with StateDB() as db:
        row = db.execute(
            "SELECT status FROM pending_fixes WHERE id = ?", (fix_id,)
        ).fetchone()
    assert row is not None, f"Row {fix_id} not found"
    return row["status"]


def _fix_history_count(db_path: Path) -> int:
    """Count rows in fix_history."""
    with StateDB() as db:
        row = db.execute("SELECT COUNT(*) AS cnt FROM fix_history").fetchone()
    return row["cnt"]


# ---------------------------------------------------------------------------
# Tests — required
# ---------------------------------------------------------------------------


def test_apply_restart_container_success(
    client: TestClient, db_path: Path
) -> None:
    """CRASH_LOOP fix → restart_container → 200; DB updated to 'applied'."""
    fix_id = _insert_fix(db_path, app_key="dozzle", diagnosis_class="CRASH_LOOP")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        resp = client.post(f"/api/v1/agent/fixes/{fix_id}/apply")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["fix_type"] == "restart_container"
    assert "restarted" in data["message"].lower()

    # DB: status updated
    assert _row_status(db_path, fix_id) == "applied"
    # DB: fix_history row inserted
    assert _fix_history_count(db_path) == 1

    # subprocess called with correct args
    mock_run.assert_called_once_with(
        ["docker", "restart", "dozzle"],
        check=True,
        timeout=30,
        capture_output=True,
    )


def test_apply_restart_container_subprocess_failure(
    client: TestClient, db_path: Path
) -> None:
    """subprocess.CalledProcessError → 500; DB row remains 'pending'."""
    fix_id = _insert_fix(db_path, app_key="sonarr", diagnosis_class="CRASH_LOOP")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["docker", "restart", "sonarr"]
        )
        resp = client.post(f"/api/v1/agent/fixes/{fix_id}/apply")

    assert resp.status_code == 500, resp.text
    assert "docker" in resp.json()["detail"].lower() or "failed" in resp.json()["detail"].lower()

    # DB: status must NOT have changed to 'applied'
    assert _row_status(db_path, fix_id) == "pending"
    # No fix_history row
    assert _fix_history_count(db_path) == 0


def test_apply_unsafe_fix_returns_422(
    client: TestClient, db_path: Path
) -> None:
    """PORT_CONFLICT has no safe mapping → 422 (requires human approval)."""
    fix_id = _insert_fix(
        db_path,
        app_key="radarr",
        diagnosis_class="PORT_CONFLICT",
        suggested_fix="Change the host port mapping in the compose file.",
    )

    with patch("subprocess.run") as mock_run:
        resp = client.post(f"/api/v1/agent/fixes/{fix_id}/apply")
        mock_run.assert_not_called()  # no docker commands should be issued

    assert resp.status_code == 422, resp.text
    data = resp.json()
    assert "human approval" in data["detail"].lower() or "safe" in data["detail"].lower()
    # DB: must still be pending
    assert _row_status(db_path, fix_id) == "pending"


def test_apply_fix_not_found_returns_404(
    client: TestClient, db_path: Path
) -> None:
    """POST /fixes/9999/apply with no matching row → 404."""
    resp = client.post("/api/v1/agent/fixes/9999/apply")
    assert resp.status_code == 404, resp.text
    data = resp.json()
    assert "9999" in data["detail"] or "not found" in data["detail"].lower()


# ---------------------------------------------------------------------------
# Tests — optional
# ---------------------------------------------------------------------------


def test_apply_repull_restart_success(
    client: TestClient, db_path: Path
) -> None:
    """IMAGE_PULL_FAIL fix → repull_restart → two docker calls; 200."""
    fix_id = _insert_fix(
        db_path,
        app_key="prowlarr",
        diagnosis_class="IMAGE_PULL_FAIL",
        suggested_fix="Re-pull the image and restart.",
        fix_metadata='{"image": "lscr.io/linuxserver/prowlarr:latest"}',
    )

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        resp = client.post(f"/api/v1/agent/fixes/{fix_id}/apply")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["fix_type"] == "repull_restart"

    # Two subprocess calls: pull then restart
    assert mock_run.call_count == 2
    pull_call = mock_run.call_args_list[0]
    restart_call = mock_run.call_args_list[1]
    assert pull_call == call(
        ["docker", "pull", "lscr.io/linuxserver/prowlarr:latest"],
        check=True,
        timeout=120,
        capture_output=True,
    )
    assert restart_call == call(
        ["docker", "restart", "prowlarr"],
        check=True,
        timeout=30,
        capture_output=True,
    )

    assert _row_status(db_path, fix_id) == "applied"
    assert _fix_history_count(db_path) == 1


def test_apply_no_longer_returns_501(
    client: TestClient, db_path: Path
) -> None:
    """Regression: the old Phase D stub returned 501; Phase E must not."""
    fix_id = _insert_fix(db_path, diagnosis_class="CRASH_LOOP")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        resp = client.post(f"/api/v1/agent/fixes/{fix_id}/apply")

    assert resp.status_code != 501, (
        "Phase E endpoint still returning 501 stub response"
    )
