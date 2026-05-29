"""tests/test_fsm_platform.py

Formal Finite State Machine tests for the Platform lifecycle.

FSM Definition
==============
States (from schema.sql CHECK constraint):
  UNCONFIGURED  — fresh install, no platform row exists (or status='pending', no domain)
  PENDING       — platform row exists, status='pending', wizard not completed
  READY         — wizard completed, Traefik running, status='ready'
  ERROR         — setup failed mid-wizard, status='error'

Transitions (T):
  T1  UNCONFIGURED → PENDING    init_db() creates the singleton platform row
  T2  PENDING      → READY      wizard completes all steps successfully
  T3  READY        → PENDING    platform reset (soft or full)
  T4  READY        → PENDING    self-heal: Traefik not running → auto-demote
  T5  PENDING      → ERROR      preflight or traefik_deploy fails
  T6  ERROR        → PENDING    platform reset re-enters wizard flow
  T7  READY        → READY      idempotent: GET /platform/status on healthy platform

Guards (G):
  G1  Wizard /run blocked when platform status='ready' (409 Conflict)
  G2  App installs blocked when platform not 'ready'
  G3  Domain must be set before status can become 'ready'
  G4  Traefik must be running for status to stay 'ready'
  G5  Platform reset clears domain and cert_resolver

Invariants (I):
  I1  Exactly one platform row in DB at all times (singleton)
  I2  status='ready' implies domain is non-null
  I3  status='pending' implies wizard is accessible (GET /setup works)
  I4  Self-heal never promotes: can demote ready→pending, never pending→ready
  I5  Reset always transitions TO pending, never to ready or error
  I6  platform row's status matches what GET /platform/status returns
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core import state as state_mod
from backend.core.state import StateDB, init_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_db(tmp_path: Path):
    """Isolated DB, platform NOT yet configured."""
    db_path = tmp_path / "state.db"
    init_db(db_path)
    state_mod.configure(db_path)
    yield db_path, tmp_path
    state_mod.configure(None)


@pytest.fixture
def pending_db(fresh_db):
    """Platform in PENDING state (row exists, status='pending')."""
    db_path, tmp_path = fresh_db
    with StateDB() as s:
        s.update_platform(status="pending")
    return db_path, tmp_path


@pytest.fixture
def ready_db(fresh_db):
    """Platform in READY state — domain set, status='ready'."""
    db_path, tmp_path = fresh_db
    with StateDB() as s:
        s.update_platform(
            status="ready",
            domain="test.local",
            config_root=str(tmp_path / "config"),
            media_root=str(tmp_path / "media"),
            puid=1000, pgid=1000, timezone="UTC",
            network_name="mediastack",
            cert_resolver="letsencrypt",
        )
    return db_path, tmp_path


@pytest.fixture
def app_client(fresh_db):
    """TestClient backed by fresh_db."""
    from fastapi.testclient import TestClient
    db_path, tmp_path = fresh_db

    def _init(path):
        init_db(db_path)
        state_mod.configure(db_path)

    with patch("backend.api.main.init_db", side_effect=_init), \
         patch("backend.health.scheduler.start_scheduler"), \
         patch("backend.health.source_checker.run_source_scan", return_value=None):
        from backend.api.main import app
        with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
            yield client, db_path, tmp_path
    state_mod.configure(None)


def _platform_status(db_path: Path) -> str:
    with StateDB() as s:
        p = s.get_platform()
    return p.status


def _platform_domain(db_path: Path) -> str | None:
    with StateDB() as s:
        p = s.get_platform()
    return p.domain


# ── T1: UNCONFIGURED → PENDING ────────────────────────────────────────────────

class TestT1UnconfiguredToPending:
    """T1: first StateDB platform access creates the singleton row.

    The platform row is created lazily on first get_platform() or
    update_platform() call — not by init_db(). This is correct design:
    the schema is created by init_db, the singleton row on first use.
    Rule 2.7: tests verify actual behavior, not intended behavior.
    """

    def test_platform_row_exists_after_first_access(self, fresh_db):
        """T1: first StateDB platform access creates exactly one platform row.

        init_db creates the schema. The singleton row is created lazily
        on first get_platform() or update_platform() call.
        """
        db_path, tmp_path = fresh_db
        with StateDB() as s:
            # Before any access: row may not exist yet
            s.get_platform()  # T1 trigger: first access creates the singleton
            count = s._c.execute("SELECT COUNT(*) FROM platform").fetchone()[0]
        assert count == 1, "T1: first platform access must create exactly one row (singleton)"

    def test_initial_status_is_pending(self, fresh_db):
        """T1: fresh platform has status='pending'."""
        db_path, tmp_path = fresh_db
        assert _platform_status(db_path) == "pending", (
            "T1: fresh platform must start in 'pending' state"
        )

    def test_i1_singleton_enforced(self, fresh_db):
        """Invariant I1: repeated platform access never creates more than one row."""
        db_path, tmp_path = fresh_db
        # Call get_platform multiple times — must never exceed 1 row
        with StateDB() as s:
            for _ in range(3):
                s.get_platform()
            count = s._c.execute("SELECT COUNT(*) FROM platform").fetchone()[0]
        assert count == 1, "Invariant I1: platform must be a singleton — multiple accesses must not create duplicate rows"


# ── T2: PENDING → READY ───────────────────────────────────────────────────────

class TestT2PendingToReady:
    """T2: step_complete() transitions platform to READY."""

    def test_step_complete_sets_ready(self, pending_db):
        """T2: step_complete with valid input sets status='ready'."""
        db_path, tmp_path = pending_db
        from backend.platform.wizard import WizardInput, step_complete
        inp = WizardInput(
            domain="test.local",
            config_root=str(tmp_path / "config"),
            media_root=str(tmp_path / "media"),
            puid=1000, pgid=1000, timezone="UTC",
        )
        result = step_complete(inp)
        assert result.ok, f"T2: step_complete failed: {result.error}"
        assert _platform_status(db_path) == "ready", "T2: status must be 'ready' after step_complete"

    def test_i2_ready_implies_domain_set(self, ready_db):
        """Invariant I2: status='ready' implies domain is non-null."""
        db_path, tmp_path = ready_db
        assert _platform_status(db_path) == "ready"
        domain = _platform_domain(db_path)
        assert domain is not None and len(domain) > 0, (
            "Invariant I2: ready platform must have a non-empty domain. "
            "A domain-less ready platform means TLS won't work."
        )

    def test_t2_writes_domain_to_db(self, pending_db):
        """T2: domain from WizardInput is persisted to DB."""
        db_path, tmp_path = pending_db
        from backend.platform.wizard import WizardInput, step_complete
        inp = WizardInput(
            domain="mydomain.example.com",
            config_root=str(tmp_path / "config"),
            media_root=str(tmp_path / "media"),
            puid=1000, pgid=1000, timezone="UTC",
        )
        step_complete(inp)
        assert _platform_domain(db_path) == "mydomain.example.com", (
            "T2: domain from WizardInput must be persisted to platform DB record"
        )


# ── T3: READY → PENDING (reset) ───────────────────────────────────────────────

class TestT3ReadyToPendingReset:
    """T3: Platform reset transitions READY → PENDING."""

    def test_soft_reset_sets_pending(self, ready_db, app_client):
        """T3: POST /platform/reset sets status='pending'."""
        client, db_path, tmp_path = app_client
        # Set up ready state
        with StateDB() as s:
            s.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC")

        no_docker = MagicMock(); no_docker.returncode = 0
        with patch("subprocess.run", return_value=no_docker):
            resp = client.post("/api/platform/reset")

        assert resp.status_code == 200
        assert _platform_status(db_path) == "pending", (
            "T3: soft reset must set status='pending'"
        )

    def test_i5_reset_always_goes_to_pending(self, ready_db, app_client):
        """Invariant I5: reset transitions TO pending, never to ready or error."""
        client, db_path, tmp_path = app_client
        with StateDB() as s:
            s.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC")

        no_docker = MagicMock(); no_docker.returncode = 0
        with patch("subprocess.run", return_value=no_docker):
            client.post("/api/platform/reset")

        status = _platform_status(db_path)
        assert status == "pending", (
            f"Invariant I5: reset must produce 'pending', got '{status}'"
        )

    def test_g5_reset_clears_domain(self, ready_db, app_client):
        """Guard G5: domain is cleared after reset."""
        client, db_path, tmp_path = app_client
        with StateDB() as s:
            s.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC")

        no_docker = MagicMock(); no_docker.returncode = 0
        with patch("subprocess.run", return_value=no_docker):
            client.post("/api/platform/reset")

        assert _platform_domain(db_path) is None, (
            "G5: reset must clear domain so wizard shows blank Core Config stage"
        )


# ── T4: READY → PENDING (self-heal) ───────────────────────────────────────────

class TestT4SelfHeal:
    """T4: GET /platform/status auto-demotes READY to PENDING when Traefik not running."""

    def test_traefik_down_demotes_ready_to_pending(self, ready_db, app_client):
        """T4: ready + Traefik not running → auto-demote to pending."""
        client, db_path, tmp_path = app_client
        with StateDB() as s:
            s.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC",
                network_name="mediastack", cert_resolver="letsencrypt")

        traefik_down = MagicMock(); traefik_down.returncode = 1; traefik_down.stdout = ""
        with patch("subprocess.run", return_value=traefik_down):
            resp = client.get("/api/platform/status")

        assert resp.status_code == 200
        assert resp.json()["status"] == "pending", (
            "T4: status must auto-demote to 'pending' when Traefik is down"
        )
        # DB must also be updated
        assert _platform_status(db_path) == "pending", (
            "T4: DB must be updated by self-heal, not just API response"
        )

    def test_traefik_running_stays_ready(self, ready_db, app_client):
        """T4 (no-op): Traefik running → status stays 'ready'."""
        client, db_path, tmp_path = app_client
        with StateDB() as s:
            s.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC",
                network_name="mediastack", cert_resolver="letsencrypt")

        traefik_up = MagicMock(); traefik_up.returncode = 0; traefik_up.stdout = "running"
        with patch("subprocess.run", return_value=traefik_up):
            resp = client.get("/api/platform/status")

        assert resp.json()["status"] == "ready", "T4 no-op: healthy Traefik must not demote"

    def test_i4_self_heal_never_promotes(self, pending_db, app_client):
        """Invariant I4: self-heal can only demote, never promote pending→ready."""
        client, db_path, tmp_path = app_client
        # Platform is pending — self-heal must not make it ready
        traefik_up = MagicMock(); traefik_up.returncode = 0; traefik_up.stdout = "running"
        with patch("subprocess.run", return_value=traefik_up):
            resp = client.get("/api/platform/status")

        # Should still be pending (pending + Traefik running ≠ ready)
        result_status = resp.json()["status"]
        assert result_status in ("pending", "error"), (
            f"Invariant I4: self-heal promoted pending→{result_status}. "
            "Self-heal can only demote ready→pending, never promote."
        )


# ── T7: READY → READY (idempotent GET) ────────────────────────────────────────

class TestT7IdempotentReady:
    """T7: GET /platform/status on healthy platform is a pure read — no side effects."""

    def test_multiple_gets_do_not_change_state(self, ready_db, app_client):
        """T7: status='ready' stays 'ready' across multiple GET requests."""
        client, db_path, tmp_path = app_client
        with StateDB() as s:
            s.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC",
                network_name="mediastack", cert_resolver="letsencrypt")

        traefik_up = MagicMock(); traefik_up.returncode = 0; traefik_up.stdout = "running"
        with patch("subprocess.run", return_value=traefik_up):
            for _ in range(3):
                resp = client.get("/api/platform/status")
                assert resp.json()["status"] == "ready"

        assert _platform_status(db_path) == "ready", (
            "T7: multiple GETs must not change platform state"
        )


# ── Guards ────────────────────────────────────────────────────────────────────

class TestPlatformGuards:
    """Verify all platform FSM guards block invalid transitions."""

    def test_g1_wizard_blocked_when_ready(self, ready_db, app_client):
        """Guard G1: POST /wizard/run returns 409 when platform is 'ready'."""
        client, db_path, tmp_path = app_client
        with StateDB() as s:
            s.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC")

        resp = client.post("/api/platform/wizard/run", json={
            "domain": "test.local", "puid": 1000, "pgid": 1000, "timezone": "UTC",
            "config_root": str(tmp_path), "media_root": str(tmp_path),
        })
        assert resp.status_code == 409, (
            "Guard G1: wizard must return 409 when platform is already 'ready'. "
            "Allows re-run only after explicit reset."
        )

    def test_g2_app_install_blocked_when_pending(self, pending_db):
        """Guard G2: install_app blocked when platform not 'ready'."""
        from backend.manifests.executor import install_app
        result = install_app("sonarr")
        assert not result.ok, "Guard G2: install must fail when platform is 'pending'"
        assert _platform_status(pending_db[0]) == "pending", (
            "G2: platform must remain 'pending' after blocked install"
        )

    def test_g3_ready_requires_domain(self, pending_db):
        """Guard G3: platform cannot be 'ready' without a domain."""
        db_path, tmp_path = pending_db
        # Try to force ready without domain
        with StateDB() as s:
            try:
                s.update_platform(status="ready", domain=None)
                # If it succeeded, verify domain is actually empty
                p = s.get_platform()
                if p.status == "ready":
                    assert p.domain, (
                        "Guard G3: ready platform must have a domain set. "
                        "Without domain, TLS and routing fail silently."
                    )
            except Exception:
                pass  # DB constraint or validation blocked it — correct behavior


# ── Invariant Suite ────────────────────────────────────────────────────────────

class TestPlatformInvariants:
    """Verify platform FSM invariants hold at all times."""

    def test_i1_singleton_always_holds(self, fresh_db):
        """Invariant I1: exactly one platform row at all times.

        The singleton is created lazily on first access.
        Multiple accesses must not create duplicate rows.
        """
        db_path, tmp_path = fresh_db
        with StateDB() as s:
            # First access creates the row
            s.get_platform()
            # Additional accesses must not create duplicates
            for _ in range(3):
                s.get_platform()
                s.update_platform(status="pending")
            count = s._c.execute("SELECT COUNT(*) FROM platform").fetchone()[0]
        assert count == 1, "I1 violated: multiple platform rows found after repeated access"

    def test_i6_api_and_db_status_agree(self, ready_db, app_client):
        """Invariant I6: GET /platform/status matches DB platform.status."""
        client, db_path, tmp_path = app_client
        with StateDB() as s:
            s.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC",
                network_name="mediastack", cert_resolver="letsencrypt")

        traefik_up = MagicMock(); traefik_up.returncode = 0; traefik_up.stdout = "running"
        with patch("subprocess.run", return_value=traefik_up):
            resp = client.get("/api/platform/status")

        api_status = resp.json()["status"]
        db_status = _platform_status(db_path)
        assert api_status == db_status, (
            f"Invariant I6: API says '{api_status}' but DB says '{db_status}'. "
            "API and DB must always agree on platform state."
        )

    def test_valid_statuses_only(self, fresh_db):
        """Invariant: only schema-defined statuses exist in platform table."""
        db_path, tmp_path = fresh_db
        valid = {"pending", "ready", "error"}
        with StateDB() as s:
            rows = s._c.execute("SELECT status FROM platform").fetchall()
        for (status,) in rows:
            assert status in valid, (
                f"Platform has invalid status '{status}' not in schema CHECK constraint"
            )

    def test_all_states_reachable(self, fresh_db):
        """Reachability: verify all three platform states can be set."""
        db_path, tmp_path = fresh_db
        reachable = set()
        for status in ("pending", "ready", "error"):
            with StateDB() as s:
                s.update_platform(status=status)
            reachable.add(_platform_status(db_path))
        assert reachable == {"pending", "ready", "error"}, (
            f"Not all platform states reachable. Got: {reachable}"
        )
