"""tests/test_probes.py — Step 4.2.c — health-probe contracts.

Three Kubernetes-style probes, each with distinct semantics:

  /healthz  — liveness; never blocks on dependencies.
  /readyz   — readiness; checks DB + state.configure().
  /startupz — startup; flips ON after migrations finish.

Each test asserts a stable invariant. We DON'T snapshot bodies (the
ts field varies per request) but we DO assert on status codes and
the diagnostic `checks` map structure.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def app_unconfigured():
    """A FastAPI TestClient with state.configure() NOT called.
    Used to verify /readyz and /startupz error semantics on cold start."""
    from backend.core import state as _state_mod
    from fastapi.testclient import TestClient
    # Save + clear state config + the startup flag (both live in state.py)
    saved_db_path = _state_mod._DB_PATH
    saved_complete = _state_mod._STARTUP_COMPLETE
    _state_mod._DB_PATH = None
    _state_mod._STARTUP_COMPLETE = False
    try:
        from backend.api.main import app
        yield TestClient(app)
    finally:
        _state_mod._DB_PATH = saved_db_path
        _state_mod._STARTUP_COMPLETE = saved_complete


@pytest.fixture
def app_configured():
    """A FastAPI TestClient with state configured + DB initialised
    (which flips startup-complete on)."""
    from backend.core.state import configure, init_db
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "state.db"
        init_db(db)  # also calls mark_startup_complete()
        configure(db)
        from backend.api.main import app
        yield TestClient(app)
        configure(None)


# ── /healthz: liveness must NEVER block on dependencies ──────────────────


def test_healthz_returns_200_even_when_state_unconfigured(app_unconfigured) -> None:
    """The defining property of a liveness probe — it MUST NOT depend
    on any of the things readiness checks. Process-alive is the only
    contract /healthz upholds."""
    r = app_unconfigured.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_healthz_body_has_timestamp(app_unconfigured) -> None:
    """The body has a `ts` field (unix epoch). Helpful for log
    correlation / verifying the response is fresh, not cached."""
    r = app_unconfigured.get("/healthz")
    body = r.json()
    assert "ts" in body
    assert isinstance(body["ts"], int)


# ── /readyz: returns 503 until state is configured + DB pings ────────────


def test_readyz_returns_503_when_state_unconfigured(app_unconfigured) -> None:
    """No state configured → /readyz must surface that as 503 +
    diagnostic. Load balancers should NOT route traffic here."""
    r = app_unconfigured.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert "checks" in body
    assert "fail" in body["checks"]["state_configured"]


def test_readyz_returns_200_when_state_ready(app_configured) -> None:
    """State configured + DB pingable → ready for traffic."""
    r = app_configured.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"state_configured": "ok", "db_ping": "ok"}


# ── /startupz: flips on once migrations finish ───────────────────────────


def test_startupz_returns_503_during_startup(app_unconfigured) -> None:
    """Before init_db has run, /startupz reports 503. K8s
    startupProbe sees this and delays the liveness probe until
    startup completes."""
    r = app_unconfigured.get("/startupz")
    assert r.status_code == 503
    assert r.json() == {"status": "starting", "startup_complete": False}


def test_startupz_returns_200_after_init_db(app_configured) -> None:
    """init_db runs migrations + flips the startup flag. Subsequent
    /startupz responses are 200 for the life of the process."""
    r = app_configured.get("/startupz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "startup_complete": True}


# ── Probes are NOT versioned (separate from /api/v1) ─────────────────────


def test_probes_carry_no_deprecation_header(app_configured) -> None:
    """The probe paths sit outside the /api/v1/ versioning umbrella.
    They MUST NOT carry the deprecation tripod even though they
    don't have an /api/v1/ counterpart."""
    for path in ("/healthz", "/readyz", "/startupz"):
        r = app_configured.get(path)
        assert "Deprecation" not in r.headers, (
            f"{path} should not carry a Deprecation header"
        )
        assert "Sunset" not in r.headers, (
            f"{path} should not carry a Sunset header"
        )


def test_probes_excluded_from_openapi_schema(app_configured) -> None:
    """The probe routes are operational, not part of the API. They're
    registered with `include_in_schema=False` so they don't pollute
    the OpenAPI / Swagger UI."""
    schema = app_configured.get("/openapi.json").json()
    paths = schema.get("paths", {})
    for probe in ("/healthz", "/readyz", "/startupz"):
        assert probe not in paths, (
            f"{probe} leaked into OpenAPI schema — `include_in_schema=False` broken"
        )
