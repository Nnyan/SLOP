"""tests/test_routes.py

Regression suite for route registration bugs:

- Favicon and static root files returning text/html instead of image/*
  (the SPA catch-all /{full_path:path} was swallowing /favicon.svg,
  /favicon.ico etc. — browsers got index.html back and showed no icon)

- Duplicate route registrations
  (weekly-summary was registered twice — once as sync def, once as
  async def — the first shadowed the second with wrong behaviour)

- Missing endpoints that the frontend calls
  (install-custom, pin-tag, pull were called by frontend but returned
  404 or 405 because the routes weren't registered)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "state.db"
    import backend.core.state as sm
    from backend.core.state import init_db
    sm.configure(db)
    init_db(db)
    return db


@pytest.fixture(scope="module")
def client(db_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


# ── Static root files ─────────────────────────────────────────────────────

class TestFaviconRoutes:
    """Each root-level static file must return its own content-type,
    not text/html from the SPA fallback.

    Root cause: FastAPI's /{full_path:path} catch-all was registered
    before explicit favicon routes existed, so browsers received
    index.html when requesting /favicon.svg.
    """

    EXPECTED = {
        "/favicon.svg":          "image/svg+xml",
        "/favicon.ico":          "image/x-icon",
        "/apple-touch-icon.png": "image/png",
        "/icon-192.png":         "image/png",
        "/icon-512.png":         "image/png",
    }

    def test_favicon_svg_content_type(self, client):
        r = client.get("/favicon.svg")
        assert r.status_code == 200, "/favicon.svg returned non-200"
        ct = r.headers.get("content-type", "")
        assert "image/svg+xml" in ct, (
            f"/favicon.svg returned content-type '{ct}' — expected image/svg+xml. "
            "The SPA catch-all may be swallowing this route."
        )

    def test_favicon_ico_content_type(self, client):
        r = client.get("/favicon.ico")
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "image" in ct, (
            f"/favicon.ico returned content-type '{ct}' — expected an image type."
        )

    def test_favicon_is_not_html(self, client):
        """The most direct check: favicon must never return HTML."""
        for path in ["/favicon.svg", "/favicon.ico", "/apple-touch-icon.png"]:
            r = client.get(path)
            ct = r.headers.get("content-type", "")
            assert "text/html" not in ct, (
                f"{path} returned text/html — the SPA fallback is intercepting it. "
                "Add explicit FileResponse routes before the catch-all."
            )

    def test_apple_touch_icon(self, client):
        r = client.get("/apple-touch-icon.png")
        assert r.status_code == 200
        assert "image/png" in r.headers.get("content-type", "")

    def test_pwa_icons(self, client):
        for path in ["/icon-192.png", "/icon-512.png"]:
            r = client.get(path)
            assert r.status_code == 200, f"{path} returned {r.status_code}"
            assert "image/png" in r.headers.get("content-type", "")

    def test_index_html_still_works(self, client):
        """SPA fallback must still serve index.html for app routes."""
        r = client.get("/")
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "text/html" in ct


# ── Duplicate route detection ─────────────────────────────────────────────

class TestNoDuplicateRoutes:
    """Routes must be registered exactly once.

    Duplicate registrations cause the first definition to shadow the
    second — the wrong handler runs silently with no error.
    """

    def _route_map(self):
        from backend.api.main import app
        routes: dict[tuple, list[str]] = {}
        for route in app.routes:
            if hasattr(route, "path") and hasattr(route, "methods"):
                key = route.path
                methods = sorted(route.methods or [])
                for method in methods:
                    full = (method, key)
                    routes.setdefault(full, []).append(
                        getattr(route, "name", "?")
                    )
        return routes

    def test_no_duplicate_routes(self):
        dupes = {
            k: v for k, v in self._route_map().items() if len(v) > 1
        }
        assert not dupes, (
            "Duplicate route registrations found — second handler is dead code:\n"
            + "\n".join(f"  {m} {p}: {names}" for (m, p), names in dupes.items())
        )

    def test_weekly_summary_registered_once(self):
        """weekly-summary was accidentally registered twice (sync + async).
        The async version (which actually calls the LLM) was shadowed.

        Step 3.2: the dual-mount at /api/v1/<area> + /api/<area> means
        every route appears twice — once per prefix. Filter to the
        canonical /api/v1/ path and assert it appears exactly once
        there.
        """
        from backend.api.main import app
        matches = [
            r for r in app.routes
            if hasattr(r, "path") and "weekly-summary" in r.path
            and r.path.startswith("/api/v1/")
        ]
        assert len(matches) == 1, (
            f"/api/v1 weekly-summary registered {len(matches)} times — expected 1. "
            "Remove the duplicate definition from health.py."
        )

    def test_config_route_registered_once(self):
        """AppConfigUpdate was defined twice — second 'config: dict' field
        shadowed the first 'values: dict' field, silently changing the API.

        Step 3.2: scope to /api/v1/ to skip the deprecated alias mount.
        """
        from backend.api.main import app
        put_config = [
            r for r in app.routes
            if hasattr(r, "path") and r.path.endswith("/config")
            and hasattr(r, "methods") and "PUT" in (r.methods or [])
            and r.path.startswith("/api/v1/")
        ]
        assert len(put_config) == 1, (
            f"/api/v1 PUT /config registered {len(put_config)} times — expected 1."
        )


# ── Critical frontend-called endpoints ────────────────────────────────────

class TestRequiredEndpoints:
    """Endpoints the frontend calls must exist and accept the right method."""

    @pytest.fixture(autouse=True)
    def cleanup_test_artifacts(self):
        """Remove any test-manifest files created by install-custom tests."""
        yield
        import shutil
        from backend.core.config import config
        for key in ["_pytest_route_test_", "x"]:
            for d in [config.catalog_dir / "apps", config.catalog_dir / "community"]:
                for ext in [".yaml", ".compose.yaml"]:
                    f = d / f"{key}{ext}"
                    if f.exists():
                        f.unlink()

    """Endpoints the frontend calls must exist and accept the right method.

    These were previously returning 404 or 405 because routes were added
    to the wrong file, registered with wrong HTTP verb, or simply missed.
    """

    ENDPOINTS = [
        # (method, path_template, seed_needed)
        ("GET",  "/api/apps/{key}/config",           True),
        ("PUT",  "/api/apps/{key}/config",           True),
        ("POST", "/api/apps/{key}/pin-tag",          True),
        ("PUT",  "/api/apps/{key}/pin-version",      True),
        ("POST", "/api/apps/{key}/pull",             True),
        ("POST", "/api/apps/{key}/update",           True),
        ("GET",  "/api/apps/{key}/post-install-steps", False),
        ("GET",  "/api/health/ghost-resources",      False),
        ("POST", "/api/health/ghost-resources/action", False),
        ("GET",  "/api/health/weekly-summary",       False),
        ("GET",  "/api/settings/traefik",            False),
        ("PUT",  "/api/settings/traefik",            False),
        ("POST", "/api/apps/install-custom",         False),
    ]

    @pytest.fixture(autouse=True)
    def seed(self, db_path):
        from backend.core.state import StateDB
        with StateDB() as db:
            db.upsert_app(
                "sonarr", display_name="Sonarr", category="arr",
                image="lscr.io/linuxserver/sonarr", container_name="sonarr",
                status="running", config_path="/tmp/sonarr-test", image_tag="latest",
            )

    def test_endpoints_not_404_or_405(self, client):
        """No endpoint should return 404 (not registered) or 405 (wrong method)."""
        bad = []
        for method, path, _ in self.ENDPOINTS:
            url = path.replace("{key}", "sonarr")
            fn = getattr(client, method.lower())

            # Minimal valid body for PUT/POST
            body = {}
            if "pin-tag" in path or "pin-version" in path:
                body = {"image_tag": "latest"}
            elif "config" in path and method == "PUT":
                body = {"values": {}}
            elif "traefik" in path and method == "PUT":
                body = {"image_tag": "v3.2"}
            elif "ghost-resources/action" in path:
                body = {"resource_type": "container", "name": "test", "action": "ignore"}
            elif "install-custom" in path:
                body = {"manifest": {"key": "_pytest_route_test_", "image": "test:latest"},
                        "compose_yaml": "services:\n  _pytest_route_test_:\n    image: test:latest\n"}

            r = fn(url, json=body) if body else fn(url)

            if r.status_code in (404, 405):
                bad.append(f"{method} {path} → {r.status_code}")

        assert not bad, (
            "Endpoints returning 404 (not registered) or 405 (wrong HTTP verb):\n"
            + "\n".join(f"  {b}" for b in bad)
        )

# ── Frontend fetch() method vs backend route method ───────────────────────

class TestFetchMethodAlignment:
    """Every fetch() call in the frontend must use the same HTTP method
    that the backend route is registered with.

    Root cause: evaluate-hardware was POST on the backend but the frontend
    called it with GET — the GET hit the SPA fallback and returned HTML,
    causing SyntaxError: Unexpected token '<' in the frontend JSON.parse().
    Similarly, pin-version was PUT but frontend called it with POST.
    """

    def _get_registered_routes(self):
        from backend.api.main import app
        routes: set[tuple] = set()
        for r in app.routes:
            if hasattr(r, "path") and hasattr(r, "methods") and r.methods:
                for m in r.methods:
                    routes.add((m, r.path))
        return routes

    def test_evaluate_hardware_has_get(self, client):
        """evaluate-hardware must accept GET since the frontend uses fetch() without method."""
        r = client.get("/api/models/evaluate-hardware?model_size_gb=4.0")
        assert r.status_code != 405, (
            "GET /api/models/evaluate-hardware returns 405. "
            "The frontend calls this as GET (default fetch method). "
            "Add @router.get() decorator alongside @router.post()."
        )
        assert "text/html" not in r.headers.get("content-type", ""), (
            "GET /api/models/evaluate-hardware returns HTML — "
            "the SPA catch-all is intercepting the request."
        )
        assert r.status_code == 200, f"evaluate-hardware returned {r.status_code}"

    def test_evaluate_hardware_returns_json(self, client):
        r = client.get("/api/models/evaluate-hardware?model_size_gb=4.0")
        assert r.status_code == 200
        data = r.json()
        assert "verdict" in data or "steps" in data or "summary" in data, (
            f"evaluate-hardware returned unexpected shape. Got keys: {list(data.keys())}"
        )

    def test_pin_version_accepts_put(self, client):
        """pin-version must accept PUT — that's what the frontend sends."""
        from backend.core.state import StateDB
        with StateDB() as db:
            db.upsert_app("sonarr", display_name="Sonarr", category="arr",
                          image="sonarr:latest", container_name="sonarr",
                          status="running", config_path="", image_tag="latest")
        r = client.put("/api/apps/sonarr/pin-version", json={"image_tag": "v4.0"})
        assert r.status_code != 405, (
            "PUT /api/apps/sonarr/pin-version returns 405. "
            "The frontend sends PUT — check the router decorator."
        )


# ── Comprehensive fetch↔route mismatch scanner ────────────────────────────

def _extract_fetch_calls(src: str) -> list[tuple[str, str]]:
    """Parse all fetch() calls in a Vue file, handling template literals.

    Returns list of (method, normalized_path) where path params are
    normalized to {param} for comparison with FastAPI route templates.
    """
    import re
    results = []
    for m in re.finditer(r'\bfetch\(', src):
        pos = m.end()
        while pos < len(src) and src[pos] in ' \t\n':
            pos += 1
        if pos >= len(src) or src[pos] not in ('`', "'", '"'):
            continue
        quote = src[pos]
        pos += 1
        path_chars = []
        if quote == '`':
            while pos < len(src) and src[pos] != '`':
                if src[pos] == '$' and pos + 1 < len(src) and src[pos + 1] == '{':
                    depth, pos = 1, pos + 2
                    while pos < len(src) and depth > 0:
                        if src[pos] == '{': depth += 1
                        elif src[pos] == '}': depth -= 1
                        pos += 1
                    path_chars.append('{param}')
                elif src[pos] in '?#':
                    while pos < len(src) and src[pos] != '`':
                        pos += 1
                    break
                else:
                    path_chars.append(src[pos])
                    pos += 1
        else:
            while pos < len(src) and src[pos] not in (quote, '?', '#'):
                path_chars.append(src[pos])
                pos += 1
        path = ''.join(path_chars).rstrip('/')
        if not path.startswith('/api/'):
            continue
        # Look for method in the options arg of THIS specific fetch() call
        call_ctx = src[m.start():min(len(src), m.start() + 600)]
        # Only look up to the next standalone fetch( call
        next_fetch = re.search(r'\n[^\n]*\bfetch\(', call_ctx[10:])
        bounded = call_ctx[:next_fetch.start() + 10] if next_fetch else call_ctx
        method_m = re.search(r"method\s*:\s*['\"]([A-Z]+)['\"]", bounded)
        method = method_m.group(1) if method_m else 'GET'
        results.append((method, path))
    return results


def _get_registered_routes_normalized() -> dict[tuple[str, str], str]:
    """Return {(method, normalized_path): real_path} for all registered routes."""
    import re
    from backend.api.main import app
    routes = {}
    for r in app.routes:
        if not hasattr(r, 'path') or not hasattr(r, 'methods') or not r.methods:
            continue
        norm = re.sub(r'\{[^}]+\}', '{param}', r.path)
        for method in r.methods:
            routes[(method, norm)] = r.path
    return routes


class TestFetchRouteAlignment:
    """Systematically verify every fetch() call in the frontend matches
    a registered backend route with the correct HTTP method.

    This scanner catches:
    - Calling GET when backend is POST-only (evaluate-hardware bug)
    - Missing endpoints the frontend calls (check-update was unregistered)
    - Method inversions from copy-paste (POST↔PUT swaps)
    - Routes removed from backend but still called by frontend

    The scanner handles template literals: /api/apps/${key}/config → {param}.
    It bounds method detection to the current fetch() call to avoid
    false positives from nearby fetch calls bleeding into the context.
    """

    FRONTEND = Path(__file__).parent.parent / "frontend" / "src"

    # Known false positives to suppress (scanner limitations, not real bugs)
    SUPPRESS = {
        # Format: (vue_filename, method, path_prefix)
    }

    def test_no_frontend_backend_method_mismatches(self, db_path):
        """No Vue file should call an API endpoint with the wrong HTTP method."""
        import re
        registered = _get_registered_routes_normalized()
        mismatches = []
        for vf in sorted(self.FRONTEND.rglob("*.vue")):
            for method, path in _extract_fetch_calls(vf.read_text()):
                norm = re.sub(r'\{param\}', '{param}', path)
                if (method, norm) not in registered:
                    reg_methods = [m for (m, p) in registered if p == norm]
                    if reg_methods:
                        mismatches.append(
                            f"{vf.name}: {method} {path} → "
                            f"backend registered as {reg_methods}"
                        )
        assert not mismatches, (
            "Frontend uses wrong HTTP method for these endpoints:\n"
            + "\n".join(f"  {m}" for m in mismatches)
        )

    def test_no_unregistered_api_calls(self, db_path):
        """No Vue file should call an endpoint that isn't registered."""
        import re
        registered = _get_registered_routes_normalized()
        unregistered = []
        INFRA_SLOTS = {"auth", "tunnel", "vpn", "dashboard", "management"}
        for vf in sorted(self.FRONTEND.rglob("*.vue")):
            for method, path in _extract_fetch_calls(vf.read_text()):
                norm = re.sub(r'\{param\}', '{param}', path)
                # Normalize literal slot names to {param} for infra routes
                parts = norm.split('/')
                for i, part in enumerate(parts):
                    if part in INFRA_SLOTS and i > 0 and parts[i-1] == 'infra':
                        parts[i] = '{param}'
                norm = '/'.join(parts)
                if (method, norm) not in registered:
                    reg_methods = [m for (m, p) in registered if p == norm]
                    if not reg_methods:  # truly unregistered
                        unregistered.append(f"{vf.name}: {method} {path}")
        assert not unregistered, (
            "Frontend calls endpoints that are not registered in the backend:\n"
            + "\n".join(f"  {u}" for u in unregistered)
        )

    def test_scanner_finds_expected_calls(self, db_path):
        """Smoke test the scanner itself — verify it finds known endpoints.

        The frontend migrated to `/api/v1/...` (per ADR 0005); these
        sentinel paths track the new prefix.
        """
        import re
        all_calls = set()
        for vf in sorted(self.FRONTEND.rglob("*.vue")):
            for method, path in _extract_fetch_calls(vf.read_text()):
                norm = re.sub(r'\{param\}', '{param}', path)
                all_calls.add((method, norm))
        # These must be found
        expected = [
            ("GET", "/api/v1/health/ghost-resources"),
            ("GET", "/api/v1/models/evaluate-hardware"),
        ]
        missing = [f"{m} {p}" for m, p in expected if (m, p) not in all_calls]
        assert not missing, f"Scanner missed expected calls: {missing}"

