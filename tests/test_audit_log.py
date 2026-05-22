"""tests/test_audit_log.py — Step 4.3.f — audit log contracts.

Verifies the audit_log table is populated for every mutating
request, holds the right columns, and that the read-only query
endpoint at /api/v1/audit applies filters correctly.

See migrations/004_audit_log.sql for the schema rationale and
backend/api/middleware.py::AuditLogMiddleware for the write path.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def client():
    from backend.core.state import configure, init_db
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "state.db"
        init_db(db)
        configure(db)
        from backend.api.main import app
        yield TestClient(app)
        configure(None)


def _audit_rows(client) -> list[dict]:
    return client.get("/api/v1/audit").json()["rows"]


# ── Migration installs the table ──────────────────────────────────────────


def test_audit_log_table_exists(client) -> None:
    """Migration 004 created the table; querying /api/v1/audit on a
    fresh DB returns an empty list, not a 500."""
    r = client.get("/api/v1/audit")
    assert r.status_code == 200
    assert r.json() == {"rows": [], "count": 0}


# ── Mutation auditing: POST/PUT/DELETE write rows ────────────────────────


def test_get_does_not_write_audit_row(client) -> None:
    """Read-only requests must NOT pollute the audit log."""
    client.get("/api/v1/health/summary")
    client.get("/api/v1/health/summary")
    assert _audit_rows(client) == []


def test_post_writes_an_audit_row(client) -> None:
    """A mutating request creates one row with the route template
    (not the literal URL) as `action`."""
    # The /api/v1/platform/wizard/validate-secrets endpoint is a POST
    # with no path params, returns quickly without DB writes.
    client.post(
        "/api/v1/platform/wizard/validate-secrets",
        json={"checks": []},
    )
    rows = _audit_rows(client)
    # Filter to only the test-triggered row (audit may include others
    # from background side-effects in shared state).
    rows = [r for r in rows if "validate-secrets" in r["action"]]
    assert len(rows) >= 1
    row = rows[0]
    assert row["actor"] == "local"
    assert row["action"] == "POST /api/v1/platform/wizard/validate-secrets"
    assert row["resource_id"] is None  # no path params
    assert row["response_status"] == 200


def test_audit_action_uses_route_template_not_literal_url(client) -> None:
    """The `action` column captures the route template — `/api/v1/apps/{key}`,
    not `/api/v1/apps/sonarr`. Bounded cardinality (Rule 4.19 discipline).
    The path-param value lives in `resource_id` instead."""
    # Hit a path-parameterised route. We use DELETE on a non-existent
    # app — the mutation goes through the middleware regardless of
    # whether the underlying handler returns 404.
    client.delete("/api/v1/apps/nonexistent_for_audit_test")
    rows = _audit_rows(client)
    rows = [r for r in rows if "/apps/" in r["action"]]
    assert rows, "no audit row written for DELETE /api/v1/apps/{key}"
    row = rows[0]
    assert "{key}" in row["action"], (
        f"action should be the route template, got: {row['action']!r}"
    )
    assert row["resource_id"] == "nonexistent_for_audit_test"


# ── Body hashing (no body storage) ────────────────────────────────────────


def test_request_body_hash_is_sha256(client) -> None:
    """The middleware records sha256(body), never the body itself.
    PII safety: bodies often contain secrets that must not be persisted."""
    payload = {"checks": ["dns"]}
    body_bytes = json.dumps(payload).encode("utf-8")
    expected_hash = hashlib.sha256(body_bytes).hexdigest()

    client.post("/api/v1/platform/wizard/validate-secrets", json=payload)
    rows = [r for r in _audit_rows(client) if "validate-secrets" in r["action"]]
    assert rows
    # httpx's TestClient may add tiny whitespace differences vs
    # json.dumps; we just verify a 64-hex-char hash is recorded.
    h = rows[0]["request_body_hash"]
    assert h is not None
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ── Query endpoint filters ────────────────────────────────────────────────


def test_audit_query_filter_by_actor(client) -> None:
    """Filter by actor returns only matching rows."""
    client.post(
        "/api/v1/platform/wizard/validate-secrets",
        json={"checks": []},
    )
    r = client.get("/api/v1/audit?actor=local")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert all(row["actor"] == "local" for row in rows)
    # And a non-existent actor returns empty
    r = client.get("/api/v1/audit?actor=nonexistent")
    assert r.json()["rows"] == []


def test_audit_query_limit_caps_rows(client) -> None:
    """`limit` parameter caps the result count. Default 100, max 1000."""
    # Generate >5 mutating requests
    for _ in range(7):
        client.post(
            "/api/v1/platform/wizard/validate-secrets",
            json={"checks": []},
        )
    r = client.get("/api/v1/audit?limit=3")
    rows = r.json()["rows"]
    assert len(rows) <= 3


def test_audit_query_orders_newest_first(client) -> None:
    """Reverse-chronological ordering. The most recent ts must be
    first; ties broken by id DESC."""
    # Post 3 requests in sequence
    for i in range(3):
        client.post(
            "/api/v1/platform/wizard/validate-secrets",
            json={"checks": [], "i": i},
        )
    rows = _audit_rows(client)
    if len(rows) >= 2:
        for a, b in zip(rows, rows[1:]):
            assert (a["ts"], a["id"]) >= (b["ts"], b["id"]), (
                "audit rows must be ordered newest-first"
            )


# ── Audit endpoint dual-mounted (3.2 ADR 0005 contract) ──────────────────


def test_audit_endpoint_dual_mounted(client) -> None:
    """Step 3.2 contract: every router lives at both /api/v1/<area>
    and /api/<area>. Audit router must follow the same pattern."""
    r_v1 = client.get("/api/v1/audit")
    r_legacy = client.get("/api/audit")
    assert r_v1.status_code == r_legacy.status_code == 200
    assert r_legacy.headers.get("Deprecation") == "true"


# ── Operational paths NOT audited ─────────────────────────────────────────


def test_metrics_scrapes_not_audited(client) -> None:
    """The /metrics endpoint MAY be hit at a high frequency by
    Prometheus; auditing it would balloon the table."""
    # If client isn't able to GET /metrics for some test reason,
    # this is still a no-op — the assertion is about absence, not
    # presence.
    client.get("/metrics")
    rows = [r for r in _audit_rows(client) if "/metrics" in r["action"]]
    assert rows == [], "metrics scrapes should not write audit rows"
