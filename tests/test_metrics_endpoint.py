"""tests/test_metrics_endpoint.py

Step 4.1.d — verify /metrics endpoint returns valid Prometheus
exposition format with both auto-instrumented HTTP request metrics
and Mediastack-specific custom metric definitions.

The Prometheus exposition format spec:
  https://prometheus.io/docs/instrumenting/exposition_formats/

Each test pulls /metrics and asserts on a stable invariant. We don't
snapshot the body verbatim — too volatile (cumulative counters
advance per request) — but we DO assert on the structure and the
presence of every metric the operator runbook depends on.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def client():
    """FastAPI TestClient with a fresh state DB."""
    from backend.core.state import configure, init_db
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "state.db"
        init_db(db)
        configure(db)
        from backend.api.main import app
        yield TestClient(app)
        configure(None)


# ── Endpoint reachability + content-type ──────────────────────────────────


def test_metrics_endpoint_responds_200(client) -> None:
    assert client.get("/metrics").status_code == 200


def test_metrics_content_type_is_prometheus_exposition(client) -> None:
    """Prometheus scrapers reject non-text content-types. The exposition
    format spec mandates text/plain with version+charset parameters."""
    r = client.get("/metrics")
    ctype = r.headers.get("content-type", "").lower()
    assert ctype.startswith("text/plain"), (
        f"expected text/plain content-type, got: {ctype!r}"
    )


# ── Format validity (smoke) ───────────────────────────────────────────────


def test_metrics_body_has_help_and_type_lines(client) -> None:
    """Every metric family should be preceded by `# HELP` + `# TYPE` lines
    in the exposition format. We don't validate every line — just that
    the format-marker conventions are present."""
    body = client.get("/metrics").text
    assert "# HELP" in body, "no `# HELP` lines — exposition format broken"
    assert "# TYPE" in body, "no `# TYPE` lines — exposition format broken"


def test_metrics_body_has_no_unicode_or_html(client) -> None:
    """Sanity: the body must be ASCII-safe Prometheus text, not
    accidentally rendered HTML or a JSON error blob."""
    body = client.get("/metrics").text
    # The Prometheus text format is ASCII-safe; non-ASCII content
    # would imply we're hitting an error page or the SPA fallback.
    assert "<html" not in body.lower() and "<!doctype" not in body.lower(), (
        "/metrics returned HTML — the route is shadowed (likely by the SPA "
        "catch-all). Verify Instrumentator.expose() ran on app startup."
    )
    body.encode("ascii")  # raises UnicodeEncodeError if not ASCII-safe


# ── Auto-instrumented HTTP metrics present ────────────────────────────────


def test_http_request_total_counter_defined(client) -> None:
    """The auto-instrumented HTTP request counter must be present."""
    body = client.get("/metrics").text
    assert "http_requests_total" in body, (
        "http_requests_total missing — instrumentator not running"
    )


def test_http_request_duration_histogram_defined(client) -> None:
    """Auto-instrumented HTTP request duration histogram must be present."""
    body = client.get("/metrics").text
    assert "http_request_duration_seconds" in body, (
        "http_request_duration_seconds missing — instrumentator not running"
    )


# ── Custom Mediastack metrics surfaced ────────────────────────────────────


@pytest.mark.parametrize("metric_name", [
    "mediastack_install_duration_seconds",
    "mediastack_health_check_duration_seconds",
    "mediastack_db_query_duration_seconds",
    "mediastack_errors_total",
])
def test_custom_metric_definition_present(client, metric_name: str) -> None:
    """Every custom metric defined in `backend/core/metrics.py` must
    appear in the /metrics output (at minimum its `# HELP` line). They
    show up even before any sample because prometheus_client emits the
    metadata for every registered metric.
    """
    body = client.get("/metrics").text
    assert metric_name in body, (
        f"{metric_name} not in /metrics output — registry not joined "
        f"or import side-effect is missing"
    )


# ── Counter increments on activity ────────────────────────────────────────


def test_db_query_metric_records_select_samples(client) -> None:
    """Step 4.1 wire-up: every StateDB.execute() call records a sample
    in `mediastack_db_query_duration_seconds`. After GETting any
    endpoint that does a SELECT, the SELECT-labeled samples count > 0."""
    client.get("/api/v1/health/summary")
    body = client.get("/metrics").text
    select_lines = [
        L for L in body.splitlines()
        if L.startswith("mediastack_db_query_duration_seconds_count")
        and 'verb="SELECT"' in L
    ]
    assert select_lines, "no SELECT samples in db_query_duration histogram"
    sample_count = float(select_lines[0].rsplit(" ", 1)[-1])
    assert sample_count > 0, (
        f"SELECT sample count is {sample_count} after a /health/summary "
        f"call — StateDB.execute() wire-up not recording"
    )


def test_request_counter_records_traffic(client) -> None:
    """Confirms the instrumentator isn't a no-op shell — after a GET
    against `/api/v1/health/summary`, the metrics body includes a
    `http_requests_total{...,handler="/api/v1/health/summary",...}`
    series with count >= 1.

    Pollution-resilient: rather than comparing pre/post counts (which
    flickered in the full suite because prometheus_client uses a
    process-global registry shared across tests), this test asserts
    on absolute presence of the traffic. Whether the counter is at
    1 or 1000 doesn't matter — what matters is that the wire-up DID
    record the test's GET as a sample under the right handler label.
    """
    client.get("/api/v1/health/summary")
    body = client.get("/metrics").text
    summary_lines = [
        L for L in body.splitlines()
        if L.startswith("http_requests_total{")
        and 'handler="/api/v1/health/summary"' in L
    ]
    assert summary_lines, (
        "http_requests_total had no /api/v1/health/summary series "
        "after a GET — the FastAPI instrumentator isn't recording. "
        "Verify the Instrumentator.instrument(app).expose(app, ...) "
        "call ran during app startup."
    )
    # At least one of the matching series must be > 0 (a counter that
    # registered the metric but never incremented is just as broken).
    counts = [float(L.rsplit(" ", 1)[-1]) for L in summary_lines]
    assert max(counts) > 0, (
        f"All http_requests_total{{handler=/api/v1/health/summary}} "
        f"series are at 0: {counts}"
    )
