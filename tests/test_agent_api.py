"""tests/test_agent_api.py

Unit tests for backend/agent/api.py — Phase D.

Coverage:
  1. test_diagnoses_empty_db
       GET /agent/diagnoses on an empty DB → {"diagnoses": []}
  2. test_diagnoses_with_suggested_fix
       Insert a pending_fixes row with suggested_fix != '' →
       GET /agent/diagnoses returns it in the response
  3. test_diagnoses_excludes_empty_fix
       Rows with suggested_fix = '' are excluded from the response
  4. test_apply_stub_returns_501
       POST /agent/fixes/1/apply → HTTP 501

Fixture pattern mirrors test_api_smoke.py / test_api_coverage.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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
    """Clear manifest cache before and after every test (matches smoke suite)."""
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
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_pending_fix(
    db_path: Path,
    app_key: str = "dozzle",
    problem: str = "Container exited with code 1",
    diagnosis_class: str = "PORT_CONFLICT",
    suggested_fix: str = "Check if port 8080 is already in use.",
    confidence: float = 0.82,
    status: str = "pending",
) -> None:
    """Insert a row into pending_fixes directly (bypasses listener logic)."""
    with StateDB() as db:
        db.execute(
            """
            INSERT INTO pending_fixes
                (app_key, check_name, action_type, problem, suggested_fix,
                 confidence, status, diagnosis_class)
            VALUES (?, 'install_monitor', 'diagnose', ?, ?, ?, ?, ?)
            """,
            (app_key, problem, suggested_fix, confidence, status, diagnosis_class),
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_diagnoses_empty_db(client: TestClient) -> None:
    """GET /agent/diagnoses on empty DB returns empty diagnoses list."""
    resp = client.get("/api/v1/agent/diagnoses")
    assert resp.status_code == 200
    data = resp.json()
    assert "diagnoses" in data
    assert data["diagnoses"] == []


def test_diagnoses_with_suggested_fix(client: TestClient, db_path: Path) -> None:
    """A pending_fixes row with suggested_fix != '' appears in the response."""
    _insert_pending_fix(
        db_path,
        app_key="dozzle",
        problem="Container exited with code 1",
        diagnosis_class="PORT_CONFLICT",
        suggested_fix="Check if port 8080 is already in use. Run: docker ps -a",
        confidence=0.82,
    )

    resp = client.get("/api/v1/agent/diagnoses")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["diagnoses"]) == 1

    d = data["diagnoses"][0]
    assert d["app_key"] == "dozzle"
    assert d["diagnosis_class"] == "PORT_CONFLICT"
    assert "port 8080" in d["suggested_fix"]
    assert abs(d["confidence"] - 0.82) < 0.001
    assert d["status"] == "pending"
    assert isinstance(d["id"], int)
    assert isinstance(d["created_at"], int)


def test_diagnoses_excludes_empty_fix(client: TestClient, db_path: Path) -> None:
    """Rows with suggested_fix = '' are excluded from the response."""
    # Row with an empty suggested_fix (LLM was unreachable)
    _insert_pending_fix(
        db_path,
        app_key="sonarr",
        suggested_fix="",
        confidence=0.4,
    )

    resp = client.get("/api/v1/agent/diagnoses")
    assert resp.status_code == 200
    data = resp.json()
    assert data["diagnoses"] == [], (
        "Row with empty suggested_fix should be excluded from diagnoses endpoint"
    )


def test_apply_fix_missing_returns_404(client: TestClient) -> None:
    """POST /agent/fixes/1/apply with no matching row returns 404 (Phase E).

    The Phase D stub returned 501 unconditionally.  Phase E replaced the stub
    with real lookup logic — a missing fix ID now returns 404 instead.
    """
    resp = client.post("/api/v1/agent/fixes/1/apply")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
