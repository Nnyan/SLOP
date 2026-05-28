"""tests/test_trusted_host.py

Verify TrustedHostMiddleware behaviour (CVE-2026-48710 defense-in-depth).

Three cases:
  1. Valid Host header matching config.domain → 200 (request passes middleware).
  2. Malformed Host header that would trick request.url.path → 400 from middleware.
  3. MS_TRUSTED_HOSTS env override is honoured — custom host list replaces defaults.

The middleware runs at the Starlette layer, so responses are always 400
(not 422 or 500) when the host is rejected.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── helpers ─────────────────────────────────────────────────────────────────


def _reload_app():
    """Re-import backend.api.main so middleware is rebuilt from the current env."""
    # Remove cached module to force a fresh middleware stack.
    for key in list(sys.modules.keys()):
        if key.startswith("backend.api.main"):
            del sys.modules[key]
    import backend.api.main as _m
    return _m.app


def _make_client(tmp_path: Path, extra_env: dict[str, str] | None = None):
    """Return a (TestClient, db_path) pair with an isolated DB.

    Patches the env vars in extra_env before reloading main.py so the
    middleware stack picks them up.
    """
    import backend.core.state as sm
    from backend.core.state import init_db

    db_path = tmp_path / "state.db"
    init_db(db_path)
    sm.configure(db_path)

    env_patch = extra_env or {}
    with patch.dict("os.environ", env_patch, clear=False):
        app = _reload_app()
        client = TestClient(app, raise_server_exceptions=False)
        return client, db_path


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_manifest_cache():
    """Clear manifest cache before/after each test to avoid cross-test pollution."""
    from backend.manifests.loader import clear_cache
    clear_cache()
    yield
    clear_cache()


# ── test cases ────────────────────────────────────────────────────────────────


def test_valid_host_domain_accepted(tmp_path: Path):
    """Case 1: A request whose Host matches DOMAIN passes TrustedHostMiddleware."""
    client, _ = _make_client(
        tmp_path,
        extra_env={
            "DOMAIN": "myserver.local",
            "MS_TRUSTED_HOSTS": "",  # ensure default path is taken
            "MS_DEBUG": "",
        },
    )
    # Use a simple read-only endpoint that is always registered.
    resp = client.get("/api/ping", headers={"Host": "myserver.local"})
    assert resp.status_code == 200, (
        f"Expected 200 for trusted host 'myserver.local', got {resp.status_code}: {resp.text}"
    )


def test_malformed_host_rejected(tmp_path: Path):
    """Case 2: A malformed Host header that would forge request.url.path is rejected with 400."""
    client, _ = _make_client(
        tmp_path,
        extra_env={
            "DOMAIN": "myserver.local",
            "MS_TRUSTED_HOSTS": "",
            "MS_DEBUG": "",
        },
    )
    # Host value that embeds a path — this is the BadHost CVE pattern.
    # TrustedHostMiddleware rejects hosts that don't match the allow-list,
    # returning 400 Bad Request before the request reaches any handler.
    resp = client.get("/api/ping", headers={"Host": "/healthz?evil#"})
    assert resp.status_code == 400, (
        f"Expected 400 for malformed host '/healthz?evil#', got {resp.status_code}: {resp.text}"
    )


def test_ms_trusted_hosts_override(tmp_path: Path):
    """Case 3: MS_TRUSTED_HOSTS env override is honoured — custom list replaces defaults."""
    client, _ = _make_client(
        tmp_path,
        extra_env={
            "MS_TRUSTED_HOSTS": "custom-host.example.com,other.example.com",
            "DOMAIN": "",
            "MS_DEBUG": "",
        },
    )
    # custom-host.example.com is explicitly in the override list → should be accepted.
    resp_ok = client.get("/api/ping", headers={"Host": "custom-host.example.com"})
    assert resp_ok.status_code == 200, (
        f"Expected 200 for overridden trusted host, got {resp_ok.status_code}: {resp_ok.text}"
    )

    # 'localhost' is NOT in the override list (override replaces defaults) → 400.
    resp_reject = client.get("/api/ping", headers={"Host": "localhost"})
    assert resp_reject.status_code == 400, (
        f"Expected 400 for 'localhost' when override excludes it, "
        f"got {resp_reject.status_code}: {resp_reject.text}"
    )
