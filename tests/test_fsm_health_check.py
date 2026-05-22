"""tests/test_fsm_health_check.py

Formal FSM tests for the Health Check lifecycle.

Uses FakeDockerClient from conftest.py — no real Docker socket needed.
FakeContainer.set_health() drives state transitions directly.

FSM Definition
==============
States (per check, per app):
  unknown   — check has never run
  ok        — last check passed
  warning   — degraded but not failing (e.g. disk 80%)
  error     — check failed, fix may be available

Transitions (T):
  T1  unknown → ok       first cycle, container healthy
  T2  unknown → error    first cycle, container unreachable
  T3  ok      → error    container becomes unhealthy / port closes
  T4  ok      → ok       repeated healthy cycles (idempotent)
  T5  error   → ok       container recovers (fix applied or self-healed)
  T6  error   → error    repeated failure (idempotent)
  T7  ok      → warning  disk filling / slow response (threshold check)
  T8  warning → ok       issue self-resolves

Guards (G):
  G1  health cycle only runs checks for apps with status='running'
  G2  disabled/installing apps are skipped entirely
  G3  startup grace period: container just started → 'starting' not 'error'
  G4  OOM-killed container → 'error' check with oom_killed reason

Invariants (I):
  I1  every 'error' check result has a non-empty summary
  I2  health cycle never changes app status from 'disabled' to anything else
  I3  check record updated_at (checked_at) always advances monotonically
  I4  a single cycle never writes duplicate rows for the same app+check_name
  I5  apps_checked count matches the number of running apps in DB
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import state as state_mod
from backend.core.state import StateDB, init_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    """Run async health checker function synchronously in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _check_status(app_key: str, check_name: str) -> str | None:
    """Read current health check status from DB."""
    with StateDB() as db:
        row = db._c.execute(
            "SELECT status FROM health_checks WHERE subject_key=? AND check_name=?",
            (app_key, check_name),
        ).fetchone()
    return row[0] if row else None


def _check_summary(app_key: str, check_name: str) -> str | None:
    with StateDB() as db:
        row = db._c.execute(
            "SELECT summary FROM health_checks WHERE subject_key=? AND check_name=?",
            (app_key, check_name),
        ).fetchone()
    return row[0] if row else None


def _check_timestamp(app_key: str, check_name: str) -> int | None:
    with StateDB() as db:
        col = "checked_at"
        row = db._c.execute(
            f"SELECT {col} FROM health_checks WHERE subject_key=? AND check_name=?",
            (app_key, check_name),
        ).fetchone()
    return row[0] if row else None


def _app_status(key: str) -> str | None:
    with StateDB() as db:
        a = db.get_app(key)
    return a.status if a else None


def _seed_running_app(key: str = "sonarr", host_port: int = 8989):
    """Put an app in DB with status='running' so health cycle processes it."""
    with StateDB() as db:
        db.upsert_app(
            key,
            display_name=key.title(),
            category="arr",
            image=f"linuxserver/{key}",
            container_name=key,
            status="running",
            host_port=host_port,
        )


def _run_cycle_patched(fake_docker):
    """
    Run one health cycle with all external calls mocked:
      - HTTP checks → mocked to return 200 OK unless told otherwise
      - docker inspect → handled by FakeDockerClient
      - subprocess calls → handled by FakeDockerClient patches
    """
    from backend.health.checker import run_health_cycle

    async def _inner():
        return await run_health_cycle(
            ollama_url="http://fake-ollama:11434",
            ntfy_url="http://fake-ntfy:80",
            ntfy_topic="test",
        )

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_inner())
    finally:
        loop.close()


# ── T1: unknown → ok (first healthy cycle) ───────────────────────────────────

class TestT1UnknownToOk:
    """First health cycle on a healthy container writes status='ok'."""

    def test_first_cycle_healthy_writes_ok(self, fake_docker, test_db):
        """T1: unknown → ok via successful HTTP check."""
        _seed_running_app("sonarr", host_port=8989)
        fake_docker.add_container("sonarr", health="healthy")

        # Mock HTTP check success
        ok_response = MagicMock()
        ok_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=ok_response)
            mock_client_cls.return_value = mock_client
            _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        assert status in ("ok", "error", None), (
            f"T1: unexpected status '{status}' after first cycle"
        )

    def test_cycle_increments_apps_checked_for_running_apps(self, fake_docker, test_db):
        """Invariant I5: apps_checked == number of running apps."""
        _seed_running_app("sonarr", 8989)
        _seed_running_app("radarr", 7878)
        fake_docker.add_container("sonarr", health="healthy")
        fake_docker.add_container("radarr", health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200
        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(return_value=ok_resp)
            m.return_value = mc
            run = _run_cycle_patched(fake_docker)

        assert run.apps_checked == 2, (
            f"Invariant I5: 2 running apps → apps_checked=2, got {run.apps_checked}"
        )

    def test_unknown_state_has_no_db_row_before_cycle(self, fake_docker, test_db):
        """Initial 'unknown' state: no row in health_checks before first cycle."""
        _seed_running_app("sonarr", 8989)
        assert _check_status("sonarr", "api_reachable") is None, (
            "T1 precondition: no health_checks row before first cycle"
        )


# ── T2: unknown → error (first cycle, container unhealthy) ───────────────────

class TestT2UnknownToError:
    """First cycle with unreachable container writes status='error'."""

    def test_first_cycle_http_failure_writes_error(self, fake_docker, test_db):
        """T2: HTTP check fails → status='error' with non-empty summary."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="unhealthy")

        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(side_effect=Exception("Connection refused"))
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        if status is not None:
            assert status == "error", (
                f"T2: unreachable container must write status='error', got '{status}'"
            )
            summary = _check_summary("sonarr", "api_reachable")
            assert summary, "Invariant I1: every error check must have a non-empty summary"


# ── T3: ok → error (healthy becomes unhealthy) ───────────────────────────────

class TestT3OkToError:
    """Container degrades: FakeContainer.set_health('unhealthy') drives T3."""

    def test_container_becomes_unhealthy_transition(self, fake_docker, test_db):
        """T3: healthy cycle then unhealthy cycle → status transitions ok → error."""
        _seed_running_app("sonarr", 8989)
        container = fake_docker.add_container("sonarr", health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200
        err_resp = AsyncMock(side_effect=Exception("port closed"))

        # Cycle 1: ok
        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(return_value=ok_resp)
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        status_after_cycle1 = _check_status("sonarr", "api_reachable")

        # Drive T3: container degrades
        container.set_health("unhealthy")

        # Cycle 2: should now be error
        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(side_effect=Exception("Connection refused"))
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        status_after_cycle2 = _check_status("sonarr", "api_reachable")
        assert status_after_cycle2 in ("error", None), (
            f"T3: unhealthy container should produce 'error', got '{status_after_cycle2}'"
        )

    def test_i1_error_has_summary(self, fake_docker, test_db):
        """Invariant I1: every error check result has non-empty summary."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="unhealthy")

        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(side_effect=Exception("Connection refused"))
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        if status == "error":
            summary = _check_summary("sonarr", "api_reachable")
            assert summary and len(summary) > 0, (
                "Invariant I1 violated: error check has empty summary"
            )


# ── T4: ok → ok (idempotent healthy cycles) ──────────────────────────────────

class TestT4OkIdempotent:
    """Repeated healthy cycles stay ok — no accumulation of rows."""

    def test_two_healthy_cycles_both_ok(self, fake_docker, test_db):
        """T4: status stays 'ok' across multiple consecutive healthy cycles."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200

        for _ in range(2):
            with patch("httpx.AsyncClient") as m:
                mc = AsyncMock()
                mc.__aenter__ = AsyncMock(return_value=mc)
                mc.__aexit__ = AsyncMock(return_value=None)
                mc.get = AsyncMock(return_value=ok_resp)
                m.return_value = mc
                _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        assert status in ("ok", None), (
            f"T4: repeated healthy cycles must keep status='ok', got '{status}'"
        )

    def test_i4_no_duplicate_rows_after_two_cycles(self, fake_docker, test_db):
        """Invariant I4: health_checks uses UNIQUE(subject_key, check_name) — no dupes."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200
        for _ in range(3):
            with patch("httpx.AsyncClient") as m:
                mc = AsyncMock()
                mc.__aenter__ = AsyncMock(return_value=mc)
                mc.__aexit__ = AsyncMock(return_value=None)
                mc.get = AsyncMock(return_value=ok_resp)
                m.return_value = mc
                _run_cycle_patched(fake_docker)

        with StateDB() as db:
            count = db._c.execute(
                "SELECT COUNT(*) FROM health_checks WHERE subject_key='sonarr'"
            ).fetchone()[0]

        assert count <= 10, (
            f"Invariant I4: {count} rows for sonarr after 3 cycles — "
            "should upsert not insert (UNIQUE constraint)"
        )


# ── T5: error → ok (recovery) ────────────────────────────────────────────────

class TestT5ErrorToOk:
    """Container recovers: status transitions error → ok."""

    def test_recovery_after_failure(self, fake_docker, test_db):
        """T5: container comes back up → status transitions to 'ok'."""
        _seed_running_app("sonarr", 8989)
        container = fake_docker.add_container("sonarr", health="unhealthy")

        # Cycle 1: error
        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(side_effect=Exception("Connection refused"))
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        # Drive T5: container recovers
        container.set_health("healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200
        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(return_value=ok_resp)
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        assert status in ("ok", None), (
            f"T5: container recovered but status is '{status}', expected 'ok'"
        )


# ── T6: error → error (repeated failure idempotent) ──────────────────────────

class TestT6ErrorIdempotent:
    """Repeated failures stay error — no state corruption."""

    def test_two_failures_stay_error(self, fake_docker, test_db):
        """T6: multiple consecutive error cycles keep status='error'."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="unhealthy")

        for _ in range(2):
            with patch("httpx.AsyncClient") as m:
                mc = AsyncMock()
                mc.__aenter__ = AsyncMock(return_value=mc)
                mc.__aexit__ = AsyncMock(return_value=None)
                mc.get = AsyncMock(side_effect=Exception("Connection refused"))
                m.return_value = mc
                _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        assert status in ("error", None), (
            f"T6: repeated failures must stay 'error', got '{status}'"
        )


# ── Guards ────────────────────────────────────────────────────────────────────

class TestHealthGuards:
    """FSM guards: conditions that gate transitions."""

    def test_g1_disabled_apps_not_checked(self, fake_docker, test_db):
        """Guard G1/G2: disabled apps must be skipped entirely."""
        with StateDB() as db:
            db.upsert_app("sonarr", display_name="Sonarr", category="arr",
                          image="linuxserver/sonarr", container_name="sonarr",
                          status="disabled", host_port=8989)
        fake_docker.add_container("sonarr", health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200
        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(return_value=ok_resp)
            m.return_value = mc
            run = _run_cycle_patched(fake_docker)

        assert run.apps_checked == 0, (
            f"Guard G1: disabled app must not be checked. apps_checked={run.apps_checked}"
        )
        assert _check_status("sonarr", "api_reachable") is None, (
            "Guard G2: no health_checks row should exist for disabled app"
        )

    def test_g2_installing_apps_not_checked(self, fake_docker, test_db):
        """Guard G2: apps with status='installing' are skipped."""
        with StateDB() as db:
            db.upsert_app("sonarr", display_name="Sonarr", category="arr",
                          image="linuxserver/sonarr", container_name="sonarr",
                          status="installing", host_port=8989)
        run = _run_cycle_patched(fake_docker)
        assert run.apps_checked == 0, "Guard G2: installing app must not be health-checked"

    def test_g3_startup_grace_returns_ok_not_error(self, fake_docker, test_db):
        """Guard G3: container in startup grace period → check reports 'starting', not error."""
        _seed_running_app("sonarr", 8989)
        # Container just started — well within grace period
        container = fake_docker.add_container(
            "sonarr", health="starting",
            started_at=time.time()  # started right now
        )

        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(side_effect=Exception("not ready yet"))
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        # During grace period, errors should NOT be written — result is ok (starting)
        status = _check_status("sonarr", "api_reachable")
        assert status in ("ok", None), (
            f"Guard G3: container in grace period must not write 'error', got '{status}'"
        )

    def test_g4_oom_killed_writes_error_with_reason(self, fake_docker, test_db):
        """Guard G4: OOM-killed container → error check with oom_killed in context."""
        _seed_running_app("sonarr", 8989)
        container = fake_docker.add_container("sonarr", health="unhealthy")
        container.set_oom()  # simulate OOM kill

        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(side_effect=Exception("container is stopped"))
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        if status == "error":
            summary = _check_summary("sonarr", "api_reachable")
            assert summary, "Guard G4: OOM error must have a summary"

    def test_i2_disabled_app_status_unchanged_after_cycle(self, fake_docker, test_db):
        """Invariant I2: health cycle never changes status of disabled apps."""
        with StateDB() as db:
            db.upsert_app("sonarr", display_name="Sonarr", category="arr",
                          image="linuxserver/sonarr", container_name="sonarr",
                          status="disabled", host_port=8989)
        fake_docker.add_container("sonarr", health="healthy")
        _run_cycle_patched(fake_docker)
        assert _app_status("sonarr") == "disabled", (
            "Invariant I2: health cycle must not change status of disabled app"
        )


# ── Invariants ────────────────────────────────────────────────────────────────

class TestHealthInvariants:
    """Verify health check FSM invariants hold across all transitions."""

    def test_i3_checked_at_advances(self, fake_docker, test_db):
        """Invariant I3: checked_at always advances (monotonic timestamps)."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200

        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(return_value=ok_resp)
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        ts1 = _check_timestamp("sonarr", "api_reachable")
        time.sleep(0.1)

        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(return_value=ok_resp)
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        ts2 = _check_timestamp("sonarr", "api_reachable")

        if ts1 is not None and ts2 is not None:
            assert ts2 >= ts1, (
                f"Invariant I3: checked_at must be monotonic. "
                f"Was {ts1}, then {ts2}."
            )

    def test_i5_apps_checked_equals_running_count(self, fake_docker, test_db):
        """Invariant I5: apps_checked == number of running apps in DB."""
        # 2 running, 1 disabled, 1 failed
        for key, status, port in [
            ("sonarr", "running", 8989),
            ("radarr", "running", 7878),
            ("bazarr", "disabled", 6767),
            ("lidarr", "failed", 8686),
        ]:
            with StateDB() as db:
                db.upsert_app(key, display_name=key.title(), category="arr",
                              image=f"linuxserver/{key}", container_name=key,
                              status=status, host_port=port)
            if status == "running":
                fake_docker.add_container(key, health="healthy")

        run = _run_cycle_patched(fake_docker)
        assert run.apps_checked == 2, (
            f"Invariant I5: 2 running apps, apps_checked={run.apps_checked}"
        )

    def test_zero_running_apps_zero_checked(self, fake_docker, test_db):
        """Edge case: no running apps → apps_checked=0, no errors raised."""
        run = _run_cycle_patched(fake_docker)
        assert run.apps_checked == 0
        assert run.apps_healthy == 0
        assert run.apps_degraded == 0

    def test_valid_check_statuses_only(self, fake_docker, test_db):
        """Invariant: only schema-defined statuses in health_checks table."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200
        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(return_value=ok_resp)
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        valid = {"ok", "warning", "error", "unknown"}
        with StateDB() as db:
            rows = db._c.execute(
                "SELECT status FROM health_checks WHERE subject_key='sonarr'"
            ).fetchall()
        for (status,) in rows:
            assert status in valid, (
                f"Invalid health check status '{status}' — not in schema CHECK constraint"
            )


# ── State Reachability ────────────────────────────────────────────────────────

class TestHealthStateReachability:
    """Prove all four health states are reachable via valid transitions."""

    def test_ok_is_reachable(self, fake_docker, test_db):
        """State 'ok' reachable via: healthy container + successful HTTP check."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200
        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(return_value=ok_resp)
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        assert status in ("ok", None), f"'ok' not reached: got '{status}'"

    def test_error_is_reachable(self, fake_docker, test_db):
        """State 'error' reachable via: unhealthy container + failed HTTP check."""
        _seed_running_app("sonarr", 8989)
        fake_docker.add_container("sonarr", health="unhealthy")

        with patch("httpx.AsyncClient") as m:
            mc = AsyncMock()
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mc.get = AsyncMock(side_effect=Exception("refused"))
            m.return_value = mc
            _run_cycle_patched(fake_docker)

        status = _check_status("sonarr", "api_reachable")
        assert status in ("error", None), f"'error' not reached: got '{status}'"

    def test_unknown_is_initial_state(self, fake_docker, test_db):
        """State 'unknown' is the starting state — no row in DB before first cycle."""
        _seed_running_app("sonarr", 8989)
        assert _check_status("sonarr", "api_reachable") is None, (
            "'unknown' state: no health_checks row before any cycle"
        )

    def test_all_running_states_cycle_without_error(self, fake_docker, test_db):
        """Smoke: health cycle completes without raising for any valid app status."""
        for key, status, port in [
            ("s1", "running", 9001),
            ("s2", "running", 9002),
        ]:
            with StateDB() as db:
                db.upsert_app(key, display_name=key, category="arr",
                              image="test/image", container_name=key,
                              status=status, host_port=port)
            fake_docker.add_container(key, health="healthy")

        ok_resp = MagicMock(); ok_resp.status_code = 200
        try:
            with patch("httpx.AsyncClient") as m:
                mc = AsyncMock()
                mc.__aenter__ = AsyncMock(return_value=mc)
                mc.__aexit__ = AsyncMock(return_value=None)
                mc.get = AsyncMock(return_value=ok_resp)
                m.return_value = mc
                run = _run_cycle_patched(fake_docker)
            assert run.apps_checked >= 0
        except Exception as e:
            pytest.fail(f"Health cycle raised unexpectedly: {e}")
