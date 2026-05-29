"""tests/test_agent_verify.py

Unit tests for backend.agent.verify.verify_container_healthy.

All docker_client calls are monkeypatched — no real Docker socket required.
Sleeps are also monkeypatched so tests run instantly.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.agent import verify as verify_mod
from backend.agent.verify import verify_container_healthy
from backend.core.docker_client import ContainerInfo, DockerError


def _make_info(status: str, health: str) -> ContainerInfo:
    return ContainerInfo(
        id="abc123",
        name="test_app",
        image="test:latest",
        status=status,
        state=status,
        health=health,
        created=0,
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Prevent real sleeps in all tests."""
    monkeypatch.setattr(verify_mod.time, "sleep", lambda _: None)


# ---------------------------------------------------------------------------
# (a) Healthy: running + health == healthy
# ---------------------------------------------------------------------------

def test_healthy_running_and_healthy(monkeypatch):
    monkeypatch.setattr(verify_mod, "get_container", lambda _: _make_info("running", "healthy"))
    ok, summary = verify_container_healthy("myapp", attempts=3, interval_s=0.0)
    assert ok is True
    assert "running" in summary
    assert "healthy" in summary


# ---------------------------------------------------------------------------
# (b) Running, no healthcheck defined (health == "none") → treated as healthy
# ---------------------------------------------------------------------------

def test_running_no_healthcheck(monkeypatch):
    monkeypatch.setattr(verify_mod, "get_container", lambda _: _make_info("running", "none"))
    ok, summary = verify_container_healthy("myapp", attempts=3, interval_s=0.0)
    assert ok is True
    assert "none" in summary


# ---------------------------------------------------------------------------
# (c) Container present but still restarting across ALL attempts → False
# ---------------------------------------------------------------------------

def test_still_restarting_all_attempts(monkeypatch):
    monkeypatch.setattr(verify_mod, "get_container", lambda _: _make_info("restarting", "none"))
    ok, summary = verify_container_healthy("myapp", attempts=4, interval_s=0.0)
    assert ok is False
    assert "restarting" in summary
    assert "4" in summary  # attempts count in message


def test_exited_all_attempts(monkeypatch):
    monkeypatch.setattr(verify_mod, "get_container", lambda _: _make_info("exited", "none"))
    ok, summary = verify_container_healthy("myapp", attempts=2, interval_s=0.0)
    assert ok is False
    assert "exited" in summary


# ---------------------------------------------------------------------------
# (d) Running but healthcheck reports unhealthy → False
# ---------------------------------------------------------------------------

def test_running_but_unhealthy_healthcheck(monkeypatch):
    monkeypatch.setattr(verify_mod, "get_container", lambda _: _make_info("running", "unhealthy"))
    ok, summary = verify_container_healthy("myapp", attempts=3, interval_s=0.0)
    assert ok is False
    assert "unhealthy" in summary


# ---------------------------------------------------------------------------
# (e) docker client raises DockerError → returns (False, reason)
# ---------------------------------------------------------------------------

def test_docker_error_returns_false(monkeypatch):
    def _raise(_):
        raise DockerError("socket error")

    monkeypatch.setattr(verify_mod, "get_container", _raise)
    ok, summary = verify_container_healthy("myapp", attempts=3, interval_s=0.0)
    assert ok is False
    assert "docker error" in summary.lower()
    assert "socket error" in summary


# ---------------------------------------------------------------------------
# (f) Container not found → never healthy → False
# ---------------------------------------------------------------------------

def test_container_not_found(monkeypatch):
    monkeypatch.setattr(verify_mod, "get_container", lambda _: None)
    ok, summary = verify_container_healthy("myapp", attempts=2, interval_s=0.0)
    assert ok is False
    assert "not_found" in summary


# ---------------------------------------------------------------------------
# (g) Becomes healthy on last attempt (eventual success)
# ---------------------------------------------------------------------------

def test_becomes_healthy_on_last_attempt(monkeypatch):
    call_count = {"n": 0}

    def _get_container(_):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return _make_info("restarting", "none")
        return _make_info("running", "healthy")

    monkeypatch.setattr(verify_mod, "get_container", _get_container)
    ok, summary = verify_container_healthy("myapp", attempts=3, interval_s=0.0)
    assert ok is True
    assert call_count["n"] == 3


# ---------------------------------------------------------------------------
# (h) interval_s is passed to time.sleep the right number of times
# ---------------------------------------------------------------------------

def test_sleep_called_between_attempts(monkeypatch):
    sleep_calls = []

    def _track_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(verify_mod.time, "sleep", _track_sleep)
    monkeypatch.setattr(verify_mod, "get_container", lambda _: _make_info("restarting", "none"))

    verify_container_healthy("myapp", attempts=3, interval_s=1.5)
    # sleep is called between attempts 1→2 and 2→3 (not after last)
    assert len(sleep_calls) == 2
    assert all(s == 1.5 for s in sleep_calls)
