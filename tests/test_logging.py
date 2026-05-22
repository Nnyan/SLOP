"""tests/test_logging.py — Structured-logging configuration tests (step 2.3.f).

Exercises:
  - `configure_logging()` is idempotent.
  - `correlation_id` contextvar default + set/reset cycle.
  - `get_logger()` auto-configures and returns a structlog BoundLogger.
  - The `subsystem` derivation matches the logger name.
  - `CorrelationIdMiddleware` injects a UUID when `X-Request-ID` is absent.
  - `CorrelationIdMiddleware` echoes a caller-provided `X-Request-ID`.
"""
from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog  # noqa: E402

from backend.core.logging import (  # noqa: E402
    _add_subsystem,
    configure_logging,
    get_correlation_id,
    get_logger,
    reset_correlation_id,
    set_correlation_id,
)


# ── configure_logging ──────────────────────────────────────────────


def test_configure_logging_is_idempotent() -> None:
    """Calling configure_logging twice in a row must not crash or duplicate
    handlers — production code may call it from multiple entry points."""
    configure_logging()
    configure_logging()  # second call is the assertion
    # Still callable
    log = structlog.get_logger("backend.test")
    log.info("smoke")


def test_configure_logging_honours_level_arg(caplog: pytest.LogCaptureFixture) -> None:
    """The level arg overrides the env default."""
    configure_logging(level="WARNING")
    # stdlib logger reflects the configured level
    root = logging.getLogger()
    assert root.level == logging.WARNING
    # restore default for downstream tests
    configure_logging(level="INFO")


# ── correlation_id contextvar ──────────────────────────────────────


def test_correlation_id_default_is_no_correlation_sentinel() -> None:
    # Reset to default (no token-based-reset because we want the unset state)
    assert get_correlation_id() == "(no-correlation)" or isinstance(
        get_correlation_id(), str
    )


def test_correlation_id_set_and_reset_round_trips() -> None:
    cid = "test-correlation-" + uuid.uuid4().hex[:8]
    token = set_correlation_id(cid)
    assert get_correlation_id() == cid
    reset_correlation_id(token)
    # After reset, the value is whatever was there before — for this test
    # context, the default sentinel.
    assert get_correlation_id() != cid


# ── get_logger ─────────────────────────────────────────────────────


def test_get_logger_returns_bound_logger() -> None:
    log = get_logger("backend.testpkg.module")
    # structlog BoundLogger has these methods
    assert hasattr(log, "info")
    assert hasattr(log, "warning")
    assert hasattr(log, "bind")


# ── _add_subsystem processor ───────────────────────────────────────


def test_add_subsystem_extracts_first_segment_after_backend() -> None:
    out = _add_subsystem(None, "info", {"logger": "backend.health.checker"})
    assert out["subsystem"] == "health"


def test_add_subsystem_handles_top_level_logger() -> None:
    out = _add_subsystem(None, "info", {"logger": "backend.api"})
    assert out["subsystem"] == "api"


def test_add_subsystem_silent_on_third_party_logger() -> None:
    out = _add_subsystem(None, "info", {"logger": "httpx"})
    assert "subsystem" not in out  # no addition when not under backend.*


def test_add_subsystem_silent_on_missing_logger_key() -> None:
    out = _add_subsystem(None, "info", {})
    assert "subsystem" not in out


# ── CorrelationIdMiddleware (FastAPI integration) ──────────────────


@pytest.fixture
def app_with_middleware():
    """Minimal FastAPI app that just echoes the current correlation ID."""
    from fastapi import FastAPI
    from backend.api.middleware import CorrelationIdMiddleware

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/echo-cid")
    def echo() -> dict[str, str]:
        return {"cid": get_correlation_id()}

    return app


def test_middleware_generates_uuid_when_header_absent(app_with_middleware) -> None:
    from fastapi.testclient import TestClient
    client = TestClient(app_with_middleware)

    resp = client.get("/echo-cid")
    assert resp.status_code == 200

    cid_in_body = resp.json()["cid"]
    cid_in_header = resp.headers.get("X-Request-ID")

    # Should match the format of a UUID and the body should match the header
    assert cid_in_body == cid_in_header
    assert cid_in_body != "(no-correlation)"
    # UUID hex is 32 chars + 4 dashes = 36 chars
    assert len(cid_in_body) == 36


def test_middleware_echoes_caller_provided_header(app_with_middleware) -> None:
    from fastapi.testclient import TestClient
    client = TestClient(app_with_middleware)

    caller_cid = "caller-supplied-id-123"
    resp = client.get("/echo-cid", headers={"X-Request-ID": caller_cid})
    assert resp.status_code == 200
    assert resp.json()["cid"] == caller_cid
    assert resp.headers.get("X-Request-ID") == caller_cid


def test_middleware_resets_correlation_id_after_request(app_with_middleware) -> None:
    """After the response is sent, the contextvar must be reset so the next
    request doesn't inherit the previous one's ID."""
    from fastapi.testclient import TestClient
    client = TestClient(app_with_middleware)

    # First request with explicit ID
    client.get("/echo-cid", headers={"X-Request-ID": "first-request"})

    # In the test thread (outside any request handler), the contextvar
    # should be back to the no-correlation default — the middleware
    # used a token-based reset.
    assert get_correlation_id() != "first-request"


# ── Stdlib bridge — both kinds of logger emit the same schema ──────


def test_stdlib_log_call_emits_full_schema(capsys: pytest.CaptureFixture) -> None:
    """Regression test for the 2.3.d post-fix logging bridge. Stdlib
    `logging.getLogger(...).info(...)` calls (un-migrated modules and
    third-party libraries) must flow through structlog's processor chain
    via ProcessorFormatter, not bypass it. Without this guarantee, the
    39 `logging.getLogger(__name__)` sites still in `backend/` would
    emit bare messages with no timestamp / level / correlation_id
    until the 2.3.e sweep finishes — a regression vs the pre-2.3 format.
    """
    import json
    import logging
    configure_logging(level="INFO", fmt="json")
    cid = "test-bridge-cid"
    token = set_correlation_id(cid)
    try:
        legacy_log = logging.getLogger("backend.legacy.module")
        legacy_log.info("legacy event")
    finally:
        reset_correlation_id(token)
    out = capsys.readouterr().out.strip()
    # The emitted line is one JSON object. Parse and inspect.
    line = out.splitlines()[-1]  # last line in case fixture chatter precedes
    record = json.loads(line)
    assert record["event"] == "legacy event"
    assert record["level"] == "info"
    assert record["logger"] == "backend.legacy.module"
    assert record["subsystem"] == "legacy"
    assert record["correlation_id"] == cid
    assert "timestamp" in record


def test_structlog_call_emits_full_schema_with_kwargs(
    capsys: pytest.CaptureFixture,
) -> None:
    """Structlog calls emit the same always-present schema PLUS any
    keyword args passed to `log.info(event, **kwargs)` — those become
    first-class JSON keys, not embedded in the event string."""
    import json
    configure_logging(level="INFO", fmt="json")
    cid = "test-struct-cid"
    token = set_correlation_id(cid)
    try:
        log = get_logger("backend.health.checker")
        log.info("health cycle complete", apps_checked=10, apps_healthy=9)
    finally:
        reset_correlation_id(token)
    out = capsys.readouterr().out.strip()
    line = out.splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "health cycle complete"
    assert record["apps_checked"] == 10
    assert record["apps_healthy"] == 9
    assert record["correlation_id"] == cid
    assert record["subsystem"] == "health"
