"""tests/test_agent_watcher.py

Unit tests for backend/agent/watcher.py — Phase F of the LLM agent.

Coverage (≥4 required):
  1. test_die_event_calls_listener
       mock subprocess emits die event for mediastack-sonarr-1 →
       install_failure_listener called with app_key="sonarr" and
       step_log["status"] == "error".
  2. test_oom_event_calls_listener
       Same pattern for Action="oom".
  3. test_health_unhealthy_event_calls_listener
       Action="health_status", health_status="unhealthy" → listener called.
  4. test_health_healthy_event_is_ignored
       Action="health_status", health_status="healthy" → listener NOT called.
  5. test_non_mediastack_container_is_ignored
       Container name "some-random-nginx-1" → listener NOT called.
  6. test_watcher_cancels_cleanly
       Cancel the running watcher task; no unexpected exception propagates.

Mock strategy:
  - asyncio.create_subprocess_exec is patched to return a mock process
    whose stdout yields one event line then EOF.
  - After EOF the loop calls asyncio.sleep(5) before restarting; we patch
    sleep with AsyncMock(side_effect=asyncio.CancelledError) to stop the loop.
  - install_failure_listener is patched with AsyncMock to avoid DB writes.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.watcher import _extract_app_key, _handle_event, _watch_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _AsyncLineStream:
    """Async iterable over a list of byte lines (simulates proc.stdout)."""

    def __init__(self, lines: list) -> None:
        self._lines = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._lines)
        except StopIteration:
            raise StopAsyncIteration


class _HangingStream:
    """Async iterable that blocks forever (simulates an idle docker stream)."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(9999)  # cancelled by task.cancel()
        raise StopAsyncIteration


def _event_bytes(action: str, name: str, exit_code: str = "0", **extra_attrs) -> bytes:
    """Build a JSON-encoded docker event line as bytes."""
    attrs = {"name": name, "exitCode": exit_code}
    attrs.update(extra_attrs)
    event = {"Action": action, "Actor": {"Attributes": attrs}}
    return json.dumps(event).encode() + b"\n"


def _mock_proc(lines: list) -> MagicMock:
    """Return a mock process whose stdout is an _AsyncLineStream."""
    proc = MagicMock()
    proc.stdout = _AsyncLineStream(lines)
    proc.kill = MagicMock()
    return proc


def _run_watcher_single_event(event_line: bytes) -> AsyncMock:
    """
    Run _watch_loop with one event line; stop the loop by cancelling at
    the asyncio.sleep(5) restart pause.  Returns the listener AsyncMock.
    """
    proc = _mock_proc([event_line])
    mock_listener = AsyncMock()

    async def _run() -> None:
        # Patch sleep so the loop is cancelled instead of sleeping 5 s.
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock,
                   return_value=proc):
            with patch("backend.agent.watcher.install_failure_listener",
                       mock_listener):
                with patch("asyncio.sleep",
                           new_callable=AsyncMock,
                           side_effect=asyncio.CancelledError):
                    try:
                        await _watch_loop()
                    except asyncio.CancelledError:
                        pass  # expected

    asyncio.run(_run())
    return mock_listener


# ---------------------------------------------------------------------------
# _extract_app_key unit tests (pure function, no async needed)
# ---------------------------------------------------------------------------

def test_extract_app_key_standard_format():
    assert _extract_app_key("mediastack-sonarr-1") == "sonarr"


def test_extract_app_key_leading_slash():
    assert _extract_app_key("/mediastack-radarr-1") == "radarr"


def test_extract_app_key_non_mediastack_returns_none():
    assert _extract_app_key("some-random-nginx-1") is None


# ---------------------------------------------------------------------------
# Full loop tests (mock subprocess)
# ---------------------------------------------------------------------------

def test_die_event_calls_listener():
    """die event on a mediastack container → listener called with app_key + error status."""
    line = _event_bytes("die", "mediastack-sonarr-1", exit_code="1")
    mock_listener = _run_watcher_single_event(line)

    mock_listener.assert_called_once()
    app_key, step_log = mock_listener.call_args.args
    assert app_key == "sonarr"
    assert step_log["status"] == "error"
    assert step_log["name"] == "docker_event"
    assert "die" in step_log["message"]


def test_oom_event_calls_listener():
    """oom event on a mediastack container → listener called with app_key + error status."""
    line = _event_bytes("oom", "mediastack-radarr-1")
    mock_listener = _run_watcher_single_event(line)

    mock_listener.assert_called_once()
    app_key, step_log = mock_listener.call_args.args
    assert app_key == "radarr"
    assert step_log["status"] == "error"
    assert "oom" in step_log["detail"]


def test_health_unhealthy_event_calls_listener():
    """health_status=unhealthy → listener called."""
    line = _event_bytes(
        "health_status", "mediastack-lidarr-1",
        health_status="unhealthy",
    )
    mock_listener = _run_watcher_single_event(line)

    mock_listener.assert_called_once()
    app_key, step_log = mock_listener.call_args.args
    assert app_key == "lidarr"
    assert step_log["status"] == "error"


def test_health_healthy_event_is_ignored():
    """health_status=healthy → listener NOT called."""
    line = _event_bytes(
        "health_status", "mediastack-sonarr-1",
        health_status="healthy",
    )
    mock_listener = _run_watcher_single_event(line)

    mock_listener.assert_not_called()


def test_non_mediastack_container_is_ignored():
    """Container not matching mediastack-*-N → listener NOT called."""
    line = _event_bytes("die", "some-random-nginx-1", exit_code="137")
    mock_listener = _run_watcher_single_event(line)

    mock_listener.assert_not_called()


def test_watcher_cancels_cleanly():
    """Cancel the running watcher task; no unexpected exception propagates."""
    proc = MagicMock()
    proc.stdout = _HangingStream()
    proc.kill = MagicMock()

    async def _run() -> None:
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock,
                   return_value=proc):
            with patch("backend.agent.watcher.install_failure_listener",
                       AsyncMock()):
                task = asyncio.create_task(_watch_loop())
                await asyncio.sleep(0)   # let the task start and reach the stream
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # expected — watcher cancelled cleanly

    asyncio.run(_run())
    # If we reach here without an unhandled exception, the test passes.
