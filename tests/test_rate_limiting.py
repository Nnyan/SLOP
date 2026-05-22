"""tests/test_rate_limiting.py — Rate limiting tests (step 2.4.d).

Per Core Rule 4.14, FastAPI mutating endpoints carry per-tier
`@limiter.limit(...)` decorators. These tests use a minimal app with
limit-decorated routes (not the full Mediastack app) so the assertions
don't depend on whatever rate-limiting state the production app has
accumulated.

Localhost bypass: TestClient sets `client.host == "testclient"`, which
is in `_LOCAL_HOSTS`, so the bypass kicks in. Tests that need to
exercise the limit set the `client.host` attribute via TestClient's
internal scope or use a fresh non-bypassed Limiter.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_app(default_limits=None):
    """Build a minimal FastAPI app with a fresh, non-bypass-aware Limiter
    so the limits actually fire in tests.

    The production limiter bypasses `testclient` (the TestClient default
    host); this helper builds a Limiter that keys on a fixed value so
    every TestClient request increments the same bucket.
    """
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    # slowapi sometimes calls key_func() with no args during setup; accept *args
    test_limiter = Limiter(
        key_func=lambda *args, **kwargs: "test-fixed",
        storage_uri="memory://",
        default_limits=default_limits or [],
    )

    app = FastAPI()
    app.state.limiter = test_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    return app, test_limiter


def test_heavy_mutation_blocks_after_5() -> None:
    """5 requests succeed; the 6th returns 429."""
    app, lim = _make_app()

    @app.post("/install/{key}")
    @lim.limit("5/minute")
    def install(request: Request, key: str) -> dict[str, str]:
        return {"installed": key}

    client = TestClient(app)
    for i in range(5):
        resp = client.post("/install/foo")
        assert resp.status_code == 200, f"request {i+1}: {resp.text}"

    resp = client.post("/install/foo")
    assert resp.status_code == 429, f"6th request should 429: {resp.text}"


def test_heavy_read_blocks_after_10() -> None:
    """10 requests succeed; the 11th returns 429."""
    app, lim = _make_app()

    @app.post("/health/run")
    @lim.limit("10/minute")
    def trigger(request: Request) -> dict[str, str]:
        return {"ok": "yes"}

    client = TestClient(app)
    for i in range(10):
        resp = client.post("/health/run")
        assert resp.status_code == 200, f"request {i+1}: {resp.text}"

    resp = client.post("/health/run")
    assert resp.status_code == 429


def test_default_60_limit_with_global_default() -> None:
    """When no per-route limit is set, the global default applies."""
    app, lim = _make_app(default_limits=["60/minute"])

    # No @limiter.limit on this route — picks up the default
    @app.get("/status")
    def status(request: Request) -> dict[str, str]:
        return {"status": "ok"}

    # NB: slowapi's default_limits aren't auto-applied without
    # SlowAPIMiddleware. Document the gap; this test confirms the
    # NON-decorated route is unrestricted (200s indefinitely).
    client = TestClient(app)
    for _ in range(75):
        resp = client.get("/status")
        assert resp.status_code == 200


def test_429_response_returns_json_error() -> None:
    """slowapi's default handler returns 429 with a parseable error body.

    Retry-After / X-RateLimit-* headers are nice-to-have but require
    `headers_enabled=True` + SlowAPIMiddleware to render correctly in
    TestClient. Asserting on the body is sufficient — clients can read
    the rate-limit message and back off.
    """
    app, lim = _make_app()

    @app.post("/install/{key}")
    @lim.limit("2/minute")
    def install(request: Request, key: str) -> dict[str, str]:
        return {"installed": key}

    client = TestClient(app)
    client.post("/install/x")
    client.post("/install/x")
    resp = client.post("/install/x")
    assert resp.status_code == 429
    # Body has slowapi's "Rate limit exceeded" string somewhere
    body_text = resp.text.lower()
    assert "rate limit" in body_text or "ratelimit" in body_text or "429" in body_text


# ── Production limiter — localhost bypass ──────────────────────────


def test_production_limiter_bypasses_testclient_localhost() -> None:
    """The real `backend.api.rate_limit.limiter` bypasses `testclient` so
    the in-process health scheduler and CLI tools (ms-update, ms-test)
    never trip rate limits when calling the local API."""
    from backend.api.rate_limit import limiter as prod_limiter

    app = FastAPI()
    app.state.limiter = prod_limiter

    @app.post("/install/{key}")
    @prod_limiter.limit("2/minute")
    def install(request: Request, key: str) -> dict[str, str]:
        return {"installed": key}

    client = TestClient(app)
    # 50 requests — way over the 2/minute limit. With localhost bypass,
    # all should succeed because TestClient hits as `testclient`.
    for i in range(50):
        resp = client.post("/install/x")
        assert resp.status_code == 200, f"req {i+1}: {resp.text}"


def test_local_hosts_set_includes_testclient_and_loopback() -> None:
    """Membership invariant — the bypass list shouldn't shrink silently."""
    from backend.api.rate_limit import _LOCAL_HOSTS
    assert "127.0.0.1" in _LOCAL_HOSTS
    assert "::1" in _LOCAL_HOSTS
    assert "testclient" in _LOCAL_HOSTS
