"""tests/test_api_smoke.py

Regression guard — every major API endpoint must:
  1. Return HTTP status != 500
  2. Set Content-Type: application/json
  3. Return a body that parses as valid JSON

These tests run against a fresh DB (no installed apps, no wizard run) so
they exercise the cold-start path.  A route that crashes with a plain-text
"Internal Server Error" causes the frontend `r.json()` call to blow up with
``SyntaxError: Unexpected token 'I'...`` — a silent production regression.

Failing tests are marked ``pytest.mark.xfail(strict=True, reason=...)`` with
a corresponding TODO.md item rather than being left as red failures so the
rest of the suite remains green while the underlying bug is being triaged.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.core.state import init_db


# ── Fixtures (mirror test_api_coverage.py) ───────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_manifest_cache():
    """Clear manifest cache before and after every test in this module."""
    from backend.manifests.loader import clear_cache
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated fresh database — no installed apps, no wizard run."""
    import backend.core.state as sm
    p = tmp_path / "state.db"
    init_db(p)
    sm.configure(p)
    return p


@pytest.fixture
def client(db_path: Path):
    """TestClient wired to the isolated DB."""
    import backend.core.config as cm
    import backend.core.state as sm
    from backend.api.main import app

    with patch.object(type(cm.config), "db_path", property(lambda self: db_path)):
        sm.configure(db_path)
        with TestClient(app, base_url="http://localhost") as c:
            yield c


# ── Helpers ──────────────────────────────────────────────────────────────────


def _assert_json_response(resp, *, allow_status: tuple[int, ...] = ()) -> None:
    """Core smoke assertions — not-500, JSON content-type, parseable body.

    ``allow_status`` is an optional set of extra acceptable status codes
    (e.g. (405,) for GET-on-a-POST-only endpoint).
    """
    # 1. Not an internal server error
    assert resp.status_code != 500, (
        f"Got 500 Internal Server Error — likely an unhandled exception.\n"
        f"Body: {resp.text[:400]}"
    )
    # 2. Not a non-JSON content type (plain-text errors break r.json() in frontend)
    ct = resp.headers.get("content-type", "")
    assert "application/json" in ct, (
        f"Content-Type is not application/json: {ct!r}\nBody: {resp.text[:200]}"
    )
    # 3. Body parses without raising
    data = resp.json()  # raises if not valid JSON
    assert data is not None


# ── Parametrized GET smoke tests ─────────────────────────────────────────────

# Each entry is either a plain path string (expected PASS) or a
# pytest.param(path, marks=pytest.mark.xfail(...)) for known failures.
_GET_ENDPOINTS = [
    "/api/v1/platform/timezones",
    "/api/v1/platform/stacks",
    "/api/v1/catalog",
    "/api/v1/apps",
    "/api/v1/health/summary",
    "/api/v1/health/agent",
    "/api/v1/models/agent/config",
    "/api/v1/platform/prereqs",
    "/api/v1/platform/ollama-models",   # SSRF-guarded Ollama model fetch; live if Ollama running
]

_GET_IDS = [
    (ep if isinstance(ep, str) else ep.values[0])
    .split("/api/v1/")[-1].replace("/", "_")
    for ep in _GET_ENDPOINTS
]


@pytest.mark.parametrize("endpoint", _GET_ENDPOINTS, ids=_GET_IDS)
class TestGetEndpointsReturnJson:
    """Every GET endpoint must respond with valid JSON and status != 500."""

    def test_smoke(self, client, endpoint):
        resp = client.get(endpoint)
        _assert_json_response(resp)


# ── Prereqs shape test ───────────────────────────────────────────────────────


def test_prereqs_returns_expected_shape(client):
    """Verify /prereqs response has the top-level keys the frontend destructures.

    Frontend reads:
        data.checks   — list of gate-check objects (status chips in Stage 0)
        data.system   — dict with puid, pgid, timezone, server_ip, etc.

    A missing key yields silent `undefined` in the frontend and blank form fields.
    """
    r = client.get("/api/v1/platform/prereqs")
    assert r.status_code != 500, f"prereqs returned 500.\nBody: {r.text[:300]}"
    data = r.json()
    assert "checks" in data, f"prereqs missing 'checks' key — frontend Stage 0 chips will be empty. Got: {list(data.keys())}"
    assert "system" in data, f"prereqs missing 'system' key — Stage 1 auto-fill (PUID/TZ) will silently fail. Got: {list(data.keys())}"
    assert isinstance(data["checks"], list), f"prereqs 'checks' must be a list, got {type(data['checks'])}"
    assert isinstance(data["system"], dict), f"prereqs 'system' must be a dict, got {type(data['system'])}"


# ── POST /api/v1/platform/wizard/validate ────────────────────────────────────


class TestWizardValidateSmokePost:
    """POST /wizard/validate with a minimal valid payload must return JSON."""

    # Minimal payload: only `domain` is required; all other fields have
    # server-side defaults. Timezone defaults to "America/Los_Angeles"
    # which is a valid IANA zone.
    _MINIMAL_PAYLOAD = {"domain": "smoke.test"}

    def test_returns_json_not_500(self, client):
        resp = client.post(
            "/api/v1/platform/wizard/validate",
            json=self._MINIMAL_PAYLOAD,
        )
        _assert_json_response(resp)

    def test_response_has_valid_and_issues_fields(self, client):
        """Structural contract: ValidateResponse shape."""
        resp = client.post(
            "/api/v1/platform/wizard/validate",
            json=self._MINIMAL_PAYLOAD,
        )
        assert resp.status_code != 500
        data = resp.json()
        # ValidateResponse must have "valid" (bool) and "issues" (list)
        assert "valid" in data, f"Missing 'valid' key in: {data}"
        assert "issues" in data, f"Missing 'issues' key in: {data}"
        assert isinstance(data["valid"], bool)
        assert isinstance(data["issues"], list)


# ── GET on a POST-only endpoint (lint-compose) ───────────────────────────────


class TestLintComposeGetMethod:
    """GET /api/v1/apps/lint-compose must NOT return 500.

    lint-compose is POST-only.  A GET request to that path is routed by
    FastAPI to the ``GET /apps/{key}`` wildcard (key = "lint-compose"),
    which returns 404 JSON "app not found".  The important invariant is
    that no 500 escapes and the response is valid JSON — 4xx is fine.
    """

    def test_get_returns_4xx_not_500(self, client):
        resp = client.get("/api/v1/apps/lint-compose")
        # Must not be 500
        assert resp.status_code != 500, (
            f"GET lint-compose returned 500.\nBody: {resp.text[:300]}"
        )
        # Must be JSON
        ct = resp.headers.get("content-type", "")
        assert "application/json" in ct, f"Content-Type: {ct!r}"
        resp.json()  # must parse without raising
        # Expect a client error (4xx), not a server error
        assert 400 <= resp.status_code < 500, (
            f"Expected 4xx, got {resp.status_code}"
        )
