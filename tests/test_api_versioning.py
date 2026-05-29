"""Step 3.2.f — API versioning contracts.

Verifies the dual-mount + deprecation-header behaviour defined in
`docs/adr/0005-api-versioning.md`:

  - Every router that mounts at `/api/<area>/...` is also reachable at
    `/api/v1/<area>/...`.
  - Both prefixes return identical responses for the same request body.
  - The unversioned form carries the deprecation tripod (Deprecation /
    Link / Sunset response headers).
  - The versioned form does NOT carry those headers.
  - Infrastructure routes (`/api/ping`, `/api/health`, `/api/coverage`)
    are explicitly exempted from versioning.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def client():
    """FastAPI TestClient with a fresh state DB so the routes that
    read from StateDB don't crash on `Database path not configured`."""
    from backend.core.state import configure, init_db
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "state.db"
        init_db(db)
        configure(db)
        from backend.api.main import app
        yield TestClient(app, base_url="http://localhost")
        configure(None)


# ── Dual-mount: every legacy /api/<area> path also lives at /api/v1/<area>


def test_v1_health_summary_reachable(client) -> None:
    """The /api/v1/<area> form resolves to the same handler."""
    assert client.get("/api/v1/health/summary").status_code == 200


def test_legacy_health_summary_reachable(client) -> None:
    """Legacy /api/<area> is still reachable for backward compatibility."""
    assert client.get("/api/health/summary").status_code == 200


def test_v1_and_legacy_return_identical_body(client) -> None:
    """For a GET with no side effects, the versioned and legacy
    responses must be byte-identical (same handler, same backend)."""
    r_v1 = client.get("/api/v1/health/summary")
    r_legacy = client.get("/api/health/summary")
    assert r_v1.status_code == r_legacy.status_code == 200
    assert r_v1.json() == r_legacy.json()


# ── Deprecation header tripod on legacy routes only


def test_legacy_path_carries_deprecation_header(client) -> None:
    """`Deprecation: true` must be set on responses to /api/<area>."""
    r = client.get("/api/health/summary")
    assert r.headers.get("Deprecation") == "true"


def test_legacy_path_carries_link_to_successor(client) -> None:
    """`Link: </api/v1/...>; rel="successor-version"` points at the
    versioned counterpart so external consumers can auto-discover the
    migration target."""
    r = client.get("/api/health/summary")
    link = r.headers.get("Link", "")
    assert "/api/v1/health/summary" in link
    assert 'rel="successor-version"' in link


def test_legacy_path_carries_sunset_header(client) -> None:
    """`Sunset` is an RFC 8594 HTTP-date header signaling the soft
    removal target. Exact date doesn't matter for the test — only
    that the header is present so HTTP intermediaries see the signal."""
    r = client.get("/api/health/summary")
    assert "Sunset" in r.headers


def test_v1_path_has_no_deprecation_header(client) -> None:
    """The v1 path is the canonical form — no deprecation signal."""
    r = client.get("/api/v1/health/summary")
    assert "Deprecation" not in r.headers
    assert "Link" not in r.headers or "successor-version" not in r.headers.get("Link", "")
    assert "Sunset" not in r.headers


# ── Infrastructure routes exempt from versioning


def test_api_ping_is_not_versioned(client) -> None:
    """/api/ping is infrastructure (uptime probe), not the application
    API. It carries no deprecation header even though it sits under
    /api/. (We don't assert /api/v1/ping is 404 — the SPA catch-all
    matches it in dev/test environments where the static dir exists.)"""
    r = client.get("/api/ping")
    assert r.status_code == 200
    assert "Deprecation" not in r.headers


def test_api_coverage_is_not_versioned(client) -> None:
    """/api/coverage is the topology-dashboard data feed, not the
    application API. Same exemption as /api/ping."""
    r = client.get("/api/coverage")
    # 200 OR an error dict — but no deprecation header either way
    assert "Deprecation" not in r.headers


# ── Sample of dual-mounted routers (smoke-test breadth)


@pytest.mark.parametrize("area", [
    "platform", "registry", "catalog", "models", "health",
    "settings", "routing", "apps", "infra",
])
def test_each_router_dual_mounted(client, area: str) -> None:
    """For each top-level router area, GET against /api/<area>/ and
    /api/v1/<area>/ must NOT both 404 — at least one route is exposed
    for the area, and both prefixes expose it. We grep the OpenAPI
    schema rather than hitting an arbitrary endpoint to avoid coupling
    the test to a specific route's request shape."""
    schema = client.get("/openapi.json").json()
    paths = schema.get("paths", {})
    has_v1 = any(p.startswith(f"/api/v1/{area}/") or p == f"/api/v1/{area}"
                 for p in paths)
    has_legacy = any(p.startswith(f"/api/{area}/") or p == f"/api/{area}"
                     for p in paths)
    assert has_v1, f"No /api/v1/{area}/* routes in OpenAPI schema"
    assert has_legacy, f"No /api/{area}/* routes in OpenAPI schema"


def test_openapi_schema_tags_legacy_routes_as_deprecated(client) -> None:
    """Swagger UI groups by tag; the legacy mount carries a
    'deprecated' tag so operators see the two groups distinctly."""
    schema = client.get("/openapi.json").json()
    paths = schema.get("paths", {})
    legacy_health = paths.get("/api/health/summary", {})
    assert legacy_health, "/api/health/summary should be in the schema"
    get_op = legacy_health.get("get", {})
    tags = get_op.get("tags", [])
    assert "deprecated" in tags, (
        f"Legacy mount's tags should include 'deprecated' — got {tags}"
    )


# ── v2 framework rehearsal (per docs/cleanup/STEP_3_2_V2_PLAYBOOK.md) ──
#
# These tests make the v2-readiness contract explicit. They prove the
# framework supports `/api/v<N>/` for any integer N — not just `v1` —
# without a middleware change. When a real v2 endpoint lands, these
# tests stay green; the playbook's runbook becomes mechanical.


def test_v2_path_carries_no_deprecation_tripod(client) -> None:
    """A request to `/api/v2/foo` (not registered, returns 404 OR 200
    depending on SPA fallback) must NOT carry the deprecation
    headers. The middleware recognises any `/api/v<N>/` form as
    canonical, so adding a v2 route in the future is purely additive.
    """
    r = client.get("/api/v2/some_future_endpoint")
    assert "Deprecation" not in r.headers, (
        "DeprecationHeaderMiddleware should NOT flag /api/v2/* paths. "
        "If this trips, the regex `_API_VERSIONED_PREFIX` in "
        "backend/api/middleware.py is too narrow."
    )
    # Same for v3 / v9 / vN — anticipate any version ahead of time.
    r3 = client.get("/api/v9/anything")
    assert "Deprecation" not in r3.headers, (
        "v9 path got the deprecation tripod — versioned-prefix regex "
        "should match any `/api/v<digits>/` form."
    )


def test_unversioned_api_path_still_carries_deprecation(client) -> None:
    """Verify the corollary: a literal `/api/<area>` (no version) DOES
    still carry the deprecation tripod. Confirms the middleware is
    only relaxing for versioned forms, not for everything under
    `/api/`."""
    r = client.get("/api/health/summary")
    assert r.headers.get("Deprecation") == "true"
