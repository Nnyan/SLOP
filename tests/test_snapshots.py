"""tests/test_snapshots.py

Step 2.1 — Snapshot tests for stable outputs.

Per `docs/cleanup/STEP_2_1_SNAPSHOT_STRATEGY.md`, this module locks in the
shape of outputs that downstream tools or operators depend on. When an
output legitimately changes, regenerate snapshots with:

    pytest tests/test_snapshots.py --snapshot-update

then commit the source change AND the snapshot diff in the same commit.

This is the seed implementation — it covers two of the five strategy
targets (the two with the simplest fixture surface):

    1. `/api/health/summary` JSON shape
    2. `/api/health/scheduler` JSON shape

The remaining three (ms-update banner, ms-test summary, ms-enforce
--json) require richer fixtures (subprocess invocations + path
redaction) and land in a follow-up.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.state import init_db  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _fresh_state_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Schema-migrated StateDB; the API endpoints we snapshot read from it."""
    db_path = tmp_path_factory.mktemp("snapshots") / "state.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def client():
    """FastAPI TestClient with a fresh-DB-backed app instance.

    Late import to dodge module-import-time DB checks.
    """
    from fastapi.testclient import TestClient
    from backend.api.main import app
    return TestClient(app)


# ── Snapshot 1: /api/health/summary ────────────────────────────────


def test_health_summary_shape(client, snapshot) -> None:
    """The summary endpoint returns counts by status; the keys are stable
    and downstream UI / dashboards depend on them.

    Volatility: the count VALUES change with real DB state. We only snapshot
    the SHAPE (sorted keys), which is what the frontend actually depends on.
    """
    resp = client.get("/api/health/summary")
    assert resp.status_code == 200
    data = resp.json()
    # Snapshot the keys (stable) — values change per environment so we
    # snapshot the shape, not the literals.
    assert sorted(data.keys()) == snapshot


# ── Snapshot 2: /api/health/scheduler ──────────────────────────────


def test_health_scheduler_shape(client, snapshot) -> None:
    """The scheduler status endpoint returns scheduler running-state +
    last-cycle metadata. Frontend dashboard renders this verbatim.

    Volatility: timestamps and run-state change. Snapshot the keys only.
    """
    resp = client.get("/api/health/scheduler")
    assert resp.status_code == 200
    data = resp.json()
    assert sorted(data.keys()) == snapshot


def test_health_scheduler_summary_shape_when_present(client, snapshot) -> None:
    """When `last_cycle_summary` is non-null, its inner keys are also stable.

    On a fresh DB it'll be None, so this test seeds a synthetic summary
    via the settings table before fetching.
    """
    import json as _j
    from backend.core.state import StateDB

    fixed_summary = dict(
        apps_checked=0,
        apps_healthy=0,
        apps_degraded=0,
        llm_agent="unknown",
        elapsed_ms=0,
    )
    with StateDB() as db:
        db.set_setting("health_last_cycle_at", "1700000000")
        db.set_setting("health_last_cycle_summary", _j.dumps(fixed_summary))

    resp = client.get("/api/health/scheduler")
    assert resp.status_code == 200
    data = resp.json()
    # Snapshot the inner summary shape (keys), not the values.
    summary = data.get("last_cycle_summary") or {}
    assert sorted(summary.keys()) == snapshot


# ── CLI snapshot — ms-status --json ────────────────────────────────

_PLAN_PATH = Path(__file__).resolve().parent.parent / "docs" / "cleanup" / "PROJECT_CLEANUP.md"
_plan_absent = pytest.mark.skipif(
    not _PLAN_PATH.exists(),
    reason="docs/cleanup/PROJECT_CLEANUP.md not present in this repo (lives in slop-process)",
)


@_plan_absent
def test_ms_status_json_top_level_shape(snapshot) -> None:
    """`ms-status --json` is the cross-session continuity output (the
    `--handoff` prompt's machine-readable cousin). Its top-level keys
    are part of the cleanup-arc's tooling contract — agents and humans
    alike key off them.

    Snapshots the SHAPE (sorted top-level keys), not values like `head`
    or `unpushed_count` which change every commit. Per Core Rule 4.11
    (Snapshot Discipline).
    """
    import json
    import subprocess
    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        ["python3", str(repo_root / "ms-status"), "--json"],
        cwd=str(repo_root),
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, f"ms-status --json failed: {proc.stderr}"
    data = json.loads(proc.stdout)
    assert sorted(data.keys()) == snapshot


@_plan_absent
def test_ms_status_step_entry_shape(snapshot) -> None:
    """Each step entry in ms-status --json has a stable key set."""
    import json
    import subprocess
    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        ["python3", str(repo_root / "ms-status"), "--json"],
        cwd=str(repo_root),
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    steps = data.get("steps", [])
    assert steps, "ms-status --json must produce at least one step"
    # Snapshot the FIRST step's keys (every step has the same shape).
    assert sorted(steps[0].keys()) == snapshot
