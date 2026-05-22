"""Regression tests for the _scheduler_loop refactor (step 1.4.d, refactor 5/5).

`_scheduler_loop` previously had cyclomatic complexity 26. The refactor
extracts six post-cycle ambient-check helpers (`_check_docker_daemon_health`,
`_check_and_restart_traefik`, `_check_managed_services_health`,
`_check_disk_space`, `_maybe_start_source_scan`, plus `_execute_cycle` and
the `_set_setting_silently` thin wrapper) and turns the loop into a 30-line
orchestrator.

These tests exercise the helpers via mocks of their external dependencies
(docker, shutil, source_checker). End-to-end loop coverage remains in
test_health_scheduler.py.
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.state import StateDB, init_db  # noqa: E402
from backend.health.scheduler import (  # noqa: E402
    _check_and_restart_traefik,
    _check_disk_space,
    _check_docker_daemon_health,
    _check_managed_services_health,
    _maybe_start_source_scan,
    _set_setting_silently,
)


@pytest.fixture(autouse=True, scope="module")
def _fresh_state_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("scheduler_refactor") / "state.db"
    init_db(db_path)
    return db_path


# ── _set_setting_silently ──────────────────────────────────────────


def test_set_setting_silently_writes_value() -> None:
    _set_setting_silently("scheduler_test_key", "hello")
    with StateDB() as db:
        assert db.get_setting("scheduler_test_key") == "hello"


def test_set_setting_silently_swallows_exceptions() -> None:
    """The wrapper must never propagate — an unhealthy DB must not bring
    down the scheduler loop."""
    with patch("backend.core.state.StateDB", side_effect=RuntimeError("db down")):
        _set_setting_silently("any_key", "any_value")  # must not raise


# ── _check_docker_daemon_health ────────────────────────────────────


def test_docker_daemon_health_records_zero_when_fast(caplog: pytest.LogCaptureFixture) -> None:
    """A sub-3000ms `docker ps` should clear the slow indicator."""
    fake_run = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    with patch("subprocess.run", return_value=fake_run):
        _set_setting_silently("docker_daemon_slow_ms", "9999")
        _check_docker_daemon_health()
    with StateDB() as db:
        assert db.get_setting("docker_daemon_slow_ms") == "0"


def test_docker_daemon_health_logs_when_unreachable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`docker ps` raising should log an error, not crash."""
    with caplog.at_level(logging.ERROR, logger="backend.health.scheduler"):
        with patch("subprocess.run",
                   side_effect=RuntimeError("daemon not running")):
            _check_docker_daemon_health()
    assert any("Docker daemon unreachable" in r.message for r in caplog.records)


# ── _check_and_restart_traefik ─────────────────────────────────────


def test_traefik_helper_no_op_when_running() -> None:
    """When Traefik is already running, no compose-up subprocess fires."""
    fake_running = SimpleNamespace(status="running", health="healthy", id="t")
    with patch("backend.core.docker_client.get_container",
               return_value=fake_running), \
         patch("subprocess.run") as mock_run:
        _check_and_restart_traefik()
    mock_run.assert_not_called()


def test_traefik_helper_no_op_when_no_container_object() -> None:
    """When docker_client returns None (Traefik not in apps table), the
    helper short-circuits — preserves original behaviour."""
    with patch("backend.core.docker_client.get_container", return_value=None), \
         patch("subprocess.run") as mock_run:
        _check_and_restart_traefik()
    mock_run.assert_not_called()


def test_traefik_helper_swallows_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If docker_client itself errors, the helper logs at debug and returns."""
    with patch("backend.core.docker_client.get_container",
               side_effect=RuntimeError("docker dead")):
        _check_and_restart_traefik()  # must not raise


# ── _check_managed_services_health ─────────────────────────────────


def test_managed_services_warns_on_unhealthy(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_results = {
        "postgres": {"healthy": False, "message": "connection refused"},
        "redis": {"healthy": True, "message": "ok"},
    }
    with caplog.at_level(logging.WARNING, logger="backend.health.scheduler"):
        with patch("backend.health.managed_services.check_managed_services",
                   return_value=fake_results):
            _check_managed_services_health()
    msgs = [r.message for r in caplog.records]
    assert any("postgres" in m and "connection refused" in m for m in msgs)
    # Should NOT warn about the healthy one
    assert not any("redis" in m and "unhealthy" in m for m in msgs)


def test_managed_services_swallows_exceptions() -> None:
    with patch("backend.health.managed_services.check_managed_services",
               side_effect=RuntimeError("module unavailable")):
        _check_managed_services_health()  # must not raise


# ── _check_disk_space ──────────────────────────────────────────────


def test_disk_space_logs_critical_above_95(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_usage = SimpleNamespace(total=100, used=96, free=4)
    with caplog.at_level(logging.ERROR, logger="backend.health.scheduler"):
        with patch("shutil.disk_usage", return_value=fake_usage):
            _check_disk_space()
    assert any("CRITICAL" in r.message for r in caplog.records)


def test_disk_space_logs_warning_above_80(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_usage = SimpleNamespace(total=100, used=85, free=15)
    with caplog.at_level(logging.WARNING, logger="backend.health.scheduler"):
        with patch("shutil.disk_usage", return_value=fake_usage):
            _check_disk_space()
    msgs = [r.message for r in caplog.records]
    assert any("low disk space" in m for m in msgs)
    # Must NOT escalate to CRITICAL at this level
    assert not any("CRITICAL" in m for m in msgs)


def test_disk_space_silent_when_plenty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_usage = SimpleNamespace(total=100, used=50, free=50)
    with caplog.at_level(logging.WARNING, logger="backend.health.scheduler"):
        with patch("shutil.disk_usage", return_value=fake_usage):
            _check_disk_space()
    # No messages at WARNING or above
    assert not any(r.levelno >= logging.WARNING and "disk" in r.message
                   for r in caplog.records)


def test_disk_space_swallows_exceptions() -> None:
    with patch("shutil.disk_usage", side_effect=OSError("path missing")):
        _check_disk_space()  # must not raise


# ── _maybe_start_source_scan ───────────────────────────────────────


def test_source_scan_does_not_start_when_not_due() -> None:
    with patch("backend.health.source_checker.due_for_scan", return_value=False), \
         patch("asyncio.create_task") as mock_task:
        _maybe_start_source_scan()
    mock_task.assert_not_called()


def test_source_scan_swallows_exceptions() -> None:
    """If source_checker module has issues, the helper logs and returns."""
    with patch("backend.health.source_checker.due_for_scan",
               side_effect=ImportError("bad module")):
        _maybe_start_source_scan()  # must not raise
