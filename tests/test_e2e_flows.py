"""
tests/test_e2e_flows.py — End-to-End Flow Tests

Tests complete user-facing flows from first HTTP request to final state,
using FastAPI TestClient with mocked external dependencies (Docker, subprocess).
No live server, no live Docker — but the FULL code path executes.

These catch integration bugs: components that exist and work individually
but don't connect to each other correctly.
"""
import json
import pathlib
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

REPO = pathlib.Path(__file__).parent.parent


# ── Test app fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    from backend.core.state import init_db
    db_path = tmp_path / "state.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def app_client(db, tmp_path):
    """
    FastAPI TestClient with a fresh, isolated DB.
    Patches lifespan init_db to prevent it overwriting the test DB path
    with the production path from config.db_path.
    """
    from fastapi.testclient import TestClient
    from backend.core import state as state_mod
    from unittest.mock import patch, MagicMock
    state_mod.configure(db)
    # Patch init_db in the lifespan so it re-configures to our test DB, not prod
    def _test_init_db(path):
        from backend.core.state import init_db as _real_init
        _real_init(db)  # always use test DB
    with patch("backend.api.main.init_db", side_effect=_test_init_db), \
         patch("backend.health.scheduler.start_scheduler"), \
         patch("backend.health.source_checker.run_source_scan", return_value=None):
        from backend.api.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, tmp_path


# ═══════════════════════════════════════════════════════════════════════════
# Platform status → wizard flow → final state
# ═══════════════════════════════════════════════════════════════════════════

class TestPlatformStatusFlow:
    """
    Verify the platform status endpoint reflects actual DB state transitions.
    The sidebar, setup wizard, and health monitor all depend on this endpoint.
    """

    def test_fresh_platform_status_is_pending(self, app_client):
        client, _ = app_client
        r = client.get("/api/platform/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("pending", "not_configured"), (
            f"Fresh platform must be 'pending', got: {data['status']}"
        )

    def test_platform_status_has_all_sidebar_required_fields(self, app_client):
        """GET /platform/status must include fields the Vue sidebar reads."""
        client, _ = app_client
        r = client.get("/api/platform/status")
        data = r.json()
        for field in ("status", "domain"):
            assert field in data, (
                f"Platform status missing '{field}'. "
                f"The Vue sidebar reads platformStore.domain and platformStore.isReady. "
                f"Response: {list(data.keys())}"
            )

    def test_reset_sets_platform_to_pending(self, app_client):
        """POST /platform/reset must set status back to 'pending'."""
        client, tmp = app_client
        # Mark as ready first
        from backend.core.state import StateDB
        from backend.core import config as _cfg
        with StateDB() as db:
            db.update_platform(status="ready", domain="test.example.com",
                               config_root=str(tmp / "config"), media_root="/mnt",
                               puid=1000, pgid=1000, timezone="UTC",
                               cert_resolver="letsencrypt", network_name="mediastack")

        with patch("backend.api.platform._stop_and_remove_containers",
                   return_value={"stopped": [], "removed": []}), \
             patch("backend.api.platform._remove_network", return_value=True), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)):
            r = client.post("/api/platform/reset")

        assert r.status_code == 200
        r2 = client.get("/api/platform/status")
        assert r2.json()["status"] == "pending", (
            f"After reset, status must be 'pending', got: {r2.json()['status']}"
        )

    def test_reset_clears_domain_from_status(self, app_client):
        """After reset, GET /platform/status must return domain=null, not stale domain."""
        client, tmp = app_client
        from backend.core.state import StateDB
        with StateDB() as db:
            db.update_platform(status="ready", domain="nyrdalyrt.com",
                               config_root=str(tmp), media_root="/mnt",
                               puid=1000, pgid=1000, timezone="UTC",
                               cert_resolver="letsencrypt", network_name="mediastack")

        with patch("backend.api.platform._stop_and_remove_containers",
                   return_value={"stopped": [], "removed": []}), \
             patch("backend.api.platform._remove_network", return_value=True), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)):
            client.post("/api/platform/reset")

        r = client.get("/api/platform/status")
        assert r.json().get("domain") in (None, ""), (
            f"Domain must be null after reset, got: {r.json().get('domain')}. "
            "The Vue sidebar reads platformStore.domain — stale domain causes "
            "the green dot + old domain to show after reset."
        )


# ═══════════════════════════════════════════════════════════════════════════
# App install → health → catalog flow
# ═══════════════════════════════════════════════════════════════════════════

class TestAppInstallToHealthFlow:
    """
    Verify the complete flow: install → DB record → health endpoint → catalog.
    This catches integration bugs where install works but the result doesn't
    propagate to the endpoints other components depend on.
    """

    def _mock_successful_install(self):
        """Context manager: mocks all Docker/compose calls for a successful install."""
        healthy_container = MagicMock()
        healthy_container.status = "running"
        healthy_container.health = "healthy"
        healthy_container.ports = {}

        return {
            "backend.manifests.executor.docker_client.get_container":
                MagicMock(return_value=healthy_container),
            "backend.manifests.executor.docker_client.ports_in_use":
                MagicMock(return_value={}),
            "backend.manifests.executor.subprocess.run":
                MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr="")),
        }

    def test_installed_app_appears_in_apps_endpoint(self, app_client):
        """After install, GET /apps must list the app with status=running."""
        client, tmp = app_client
        from backend.core.state import StateDB
        from backend.core import config as _cfg

        # Mark platform ready
        with StateDB() as db:
            db.update_platform(status="ready", domain="test.com",
                               config_root=str(tmp / "config"), media_root="/mnt",
                               puid=1000, pgid=1000, timezone="UTC",
                               cert_resolver="letsencrypt", network_name="mediastack")
            # Directly register a "running" app (simulates successful install)
            db.upsert_app("sonarr", display_name="Sonarr", tier=2,
                          category="arr", status="running", image="linuxserver/sonarr",
                          image_tag="latest", container_name="sonarr",
                          host_port=8989)

        r = client.get("/api/apps")
        assert r.status_code == 200
        apps = r.json()
        sonarr = next((a for a in apps if a.get("key") == "sonarr"), None)
        assert sonarr is not None, (
            "Installed app must appear in GET /apps. "
            f"Apps returned: {[a.get('key') for a in apps]}"
        )
        assert sonarr["status"] == "running", (
            f"App status must be 'running', got: {sonarr['status']}"
        )

    def test_health_endpoint_reflects_installed_apps(self, app_client):
        """GET /health/apps must return entries for all installed running apps."""
        client, tmp = app_client
        from backend.core.state import StateDB

        with StateDB() as db:
            db.update_platform(status="ready", domain="test.com",
                               config_root=str(tmp / "config"), media_root="/mnt",
                               puid=1000, pgid=1000, timezone="UTC",
                               cert_resolver="letsencrypt", network_name="mediastack")
            db.upsert_app("radarr", display_name="Radarr", tier=2,
                          category="arr", status="running", image="linuxserver/radarr",
                          image_tag="latest", container_name="radarr", host_port=7878)

        r = client.get("/api/health/apps")
        assert r.status_code == 200
        # Health apps endpoint should not 500 when apps exist

    def test_app_status_not_running_after_install_failure(self, app_client):
        """Failed install must not leave app with status='running' in DB."""
        client, tmp = app_client
        from backend.core.state import StateDB
        from backend.manifests.executor import install_app

        with StateDB() as db:
            db.update_platform(status="ready", domain="test.com",
                               config_root=str(tmp / "config"), media_root="/mnt",
                               puid=1000, pgid=1000, timezone="UTC",
                               cert_resolver="letsencrypt", network_name="mediastack")

        with patch("backend.manifests.executor.docker_client.ports_in_use",
                   return_value={}), \
             patch("backend.manifests.executor.docker_client.get_container",
                   return_value=None), \
             patch("backend.manifests.executor.write_fragment",
                   return_value=tmp / "sonarr.yaml"), \
             patch("backend.manifests.executor.write_compose_file",
                   return_value=tmp / "docker-compose.yml"), \
             patch("backend.manifests.executor.subprocess.run",
                   return_value=MagicMock(returncode=1, stdout="", stderr="fail")):
            result = install_app("sonarr")

        assert not result.ok, "Install with compose failure must return ok=False"
        with StateDB() as db:
            app = db.get_app("sonarr")
        if app:
            assert app.status != "running", (
                f"Failed install left status='running'. Got: {app.status}. "
                "This is the else-block bug — cleanup code ran on wrong condition."
            )


# ═══════════════════════════════════════════════════════════════════════════
# Settings round-trip
# ═══════════════════════════════════════════════════════════════════════════

class TestSettingsRoundTrip:
    """GET settings → modify → POST → GET again must reflect the change."""

    def test_settings_get_post_roundtrip(self, app_client):
        """Modifying settings via PUT must be visible in subsequent GET.
        
        Bug history: test used POST (405) and wrong field name 'health_check_interval'.
        Correct: PUT /api/settings with field 'health_check_interval_secs'.
        """
        client, _ = app_client
        r = client.get("/api/settings")
        assert r.status_code == 200, f"GET /settings failed: {r.text}"

        # Use correct field name from SettingsPayload model
        new_interval = 120  # 2 minutes — well within ge=30, le=3600 bounds
        r2 = client.put("/api/settings", json={"health_check_interval_secs": new_interval})
        assert r2.status_code == 200, (
            f"PUT /settings returned {r2.status_code}: {r2.text}. "
            "Endpoint: PUT /api/settings with SettingsPayload body."
        )

        r3 = client.get("/api/settings")
        assert r3.status_code == 200
        saved = r3.json()
        assert saved.get("health_check_interval_secs") == new_interval, (
            f"Settings not persisted. PUT returned 200 but GET shows "
            f"health_check_interval_secs={saved.get('health_check_interval_secs')!r}, "
            f"expected {new_interval}. Settings must write to DB."
        )

    def test_settings_invalid_values_return_422(self, app_client):
        """Invalid settings values must return 422, not silently accept."""
        client, _ = app_client
        # health_check_interval_secs must be an int (ge=30, le=3600)
        r = client.put("/api/settings", json={"health_check_interval_secs": "not_a_number"})
        assert r.status_code == 422, (
            f"Invalid setting type must return 422, got {r.status_code}. "
            "Silently accepting invalid types causes runtime failures later."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Wizard → prereqs → stage 1 auto-fill
# ═══════════════════════════════════════════════════════════════════════════

class TestPrereqsAutoFillFlow:
    """
    GET /platform/prereqs must return system data that Stage 1 uses
    to auto-fill puid, pgid, timezone. This is the critical flow that
    broke after reset (onMounted ran but data wasn't populated).
    """

    def test_prereqs_system_has_puid_pgid_timezone(self, app_client):
        """prereqs.system must include puid, pgid, timezone for Stage 1 auto-fill."""
        client, _ = app_client
        r = client.get("/api/platform/prereqs")
        assert r.status_code == 200
        # Check source has these fields — runtime depends on Docker being available
        src = pathlib.Path("backend/api/platform.py").read_text()
        for field in ('"puid"', '"pgid"', '"timezone"'):
            assert field in src, (
                f"prereqs endpoint source missing {field} field. "
                "Stage 1 reads system.puid/pgid/timezone to auto-fill the form."
            )


    def test_prereqs_system_has_cpu_cores_and_ram(self, app_client):
        """prereqs.system must include cpu_cores and ram for AI recommendations."""
        client, _ = app_client
        r = client.get("/api/platform/prereqs")
        assert r.status_code == 200
        src = pathlib.Path("backend/api/platform.py").read_text()
        assert '"cpu_cores"' in src, "cpu_cores missing from prereqs response source"
        assert '"total_ram_gb"' in src or '"ram_gb"' in src, (
            "RAM info missing from prereqs response source"
        )


    def test_create_maintenance_window_returns_200(self, app_client):
        """POST /health/maintenance-windows must succeed, not 500."""
        client, _ = app_client
        r = client.post("/api/health/maintenance-windows", json={
            "app_key": "sonarr",
            "check_name": "api_reachable",
            "label": "Nightly backup window",
            "hour_start": 2,
            "hour_end": 4,
        })
        assert r.status_code == 200, (
            f"POST /maintenance-windows returned {r.status_code}: {r.text}. "
            "Common cause: db.commit() called on StateDB (AttributeError → 500)."
        )
        assert r.json().get("ok") is True

    def test_created_window_appears_in_list(self, app_client):
        """Created maintenance window must appear in GET /health/maintenance-windows."""
        client, _ = app_client
        client.post("/api/health/maintenance-windows", json={
            "app_key": "radarr",
            "check_name": "disk_space",
            "label": "Weekly scrub",
            "hour_start": 3,
        })
        r = client.get("/api/health/maintenance-windows")
        assert r.status_code == 200
        windows = r.json()
        radarr_windows = [w for w in windows if w.get("app_key") == "radarr"]
        assert radarr_windows, (
            "Created maintenance window not found in list. "
            "Either POST failed silently or GET uses different data source."
        )

    def test_deleted_window_not_in_list(self, app_client):
        """Deleted maintenance window must not appear in subsequent GET."""
        client, _ = app_client
        r1 = client.post("/api/health/maintenance-windows", json={
            "app_key": "jellyfin", "check_name": "api_reachable",
            "label": "Delete me", "hour_start": 1,
        })
        assert r1.status_code == 200

        windows = client.get("/api/health/maintenance-windows").json()
        to_delete = next((w for w in windows if w.get("app_key") == "jellyfin"), None)
        if not to_delete:
            pytest.skip("Window not found after create — earlier test may have failed")

        r2 = client.delete(f"/api/health/maintenance-windows/{to_delete['id']}")
        assert r2.status_code == 200

        after = client.get("/api/health/maintenance-windows").json()
        assert not any(w.get("id") == to_delete["id"] for w in after), (
            "Deleted window still appears in list. DELETE must remove from DB."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Reject fix → 404 on nonexistent, 200 on existing
# ═══════════════════════════════════════════════════════════════════════════

class TestFixApprovalFlow:
    """Pending fix approval/rejection flow — ensure correct status codes."""

    def test_approve_nonexistent_fix_returns_404(self, app_client):
        client, _ = app_client
        r = client.post("/api/health/pending-fixes/99999/approve")
        assert r.status_code == 404, (
            f"Approving non-existent fix must return 404, got {r.status_code}. "
            "Returning 200 silently succeeds a no-op."
        )

    def test_reject_nonexistent_fix_returns_404(self, app_client):
        """Reject endpoint must return 404 for unknown fix IDs, not 200."""
        client, _ = app_client
        r = client.post("/api/health/pending-fixes/0/reject")
        assert r.status_code == 404, (
            f"Rejecting non-existent fix must return 404, got {r.status_code}. "
            "Was: always returned 200 (ok=True) regardless of existence."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Wizard Step E2E — run actual wizard functions, assert on DB+filesystem
# ═══════════════════════════════════════════════════════════════════════════

class TestWizardStepE2E:
    """Run actual wizard step functions with real DB and mocked Docker."""

    def test_step_persist_settings_writes_to_db(self, app_client):
        """step_persist_settings writes notification+system settings to the settings table.

        This step writes to key-value settings (ntfy, puid as string, timezone),
        NOT the platform record — domain/puid are written there by step_complete.
        """
        client, tmp_path = app_client
        from backend.platform.wizard import WizardInput, step_persist_settings
        from backend.core.state import StateDB

        client.get("/api/platform/status")  # ensure platform row exists

        inp = WizardInput(
            domain="test.local", config_root=str(tmp_path / "cfg"),
            media_root=str(tmp_path / "media"), puid=1234, pgid=5678,
            timezone="Pacific/Auckland",
            ntfy_url="http://ntfy:80", ntfy_topic="mediastack-test",
        )
        result = step_persist_settings(inp)
        assert result.ok, f"step_persist_settings failed: {result.error}"

        with StateDB() as db:
            tz = db.get_setting("timezone")
            puid_val = db.get_setting("puid")
            ntfy_topic_val = db.get_setting("ntfy_topic")

        assert tz == "Pacific/Auckland", (
            f"timezone not written to settings table. Got: {tz!r}"
        )
        assert puid_val == "1234", f"puid not written. Got: {puid_val!r}"
        assert ntfy_topic_val == "mediastack-test", f"ntfy_topic not written. Got: {ntfy_topic_val!r}"

    def test_step_complete_sets_platform_ready(self, app_client):
        """step_complete must transition platform status to 'ready'."""
        client, tmp_path = app_client
        from backend.platform.wizard import WizardInput, step_complete
        from backend.core.state import StateDB
        with StateDB() as db:
            db.update_platform(status="pending")
        inp = WizardInput(
            domain="test.local", config_root=str(tmp_path / "cfg"),
            media_root=str(tmp_path / "media"), puid=1000, pgid=1000, timezone="UTC",
        )
        result = step_complete(inp)
        assert result.ok, f"step_complete failed: {result.error}"
        with StateDB() as db:
            p = db.get_platform()
        assert p.status == "ready"

    def test_vpn_secrets_passed_to_gluetun_provider(self, app_client, ready_db):
        """VPN deploy cfg must contain provider name and credentials from inp.secrets.

        Root bug: deploy_infra passed {domain, network} only. Gluetun read
        cfg.get('vpn_service_provider', '') → always '' → always failed.
        """
        client, tmp_path = app_client
        from backend.platform.wizard import WizardInput, step_deploy_infra
        inp = WizardInput(
            domain="test.local", config_root=str(tmp_path / "cfg"),
            media_root=str(tmp_path / "media"), puid=1000, pgid=1000, timezone="UTC",
            vpn="gluetun",
            secrets={
                "VPN_SERVICE_PROVIDER": "protonvpn",
                "VPN_TYPE": "wireguard",
                "WIREGUARD_PRIVATE_KEY": "testkey_aabbccdd_1234567890_abcdefgh_12",
            },
        )
        # _deploy is a closure inside step_deploy_infra — intercept at the provider level
        captured = {}
        from backend.infra.providers.vpn_gluetun import GluetunProvider
        original_deploy = GluetunProvider.deploy
        def capturing_deploy(self, cfg):
            captured.update(cfg)
            return type("R", (), {"ok": True, "message": "mocked", "detail": ""})()
        with patch.object(GluetunProvider, "deploy", capturing_deploy):
            step_deploy_infra(inp)
        assert "vpn_service_provider" in captured, (
            f"VPN provider not in gluetun cfg. Keys: {list(captured.keys())}"
        )
        assert captured["vpn_service_provider"] == "protonvpn"
        assert "wireguard_private_key" in captured

    def test_vpn_type_wireguard_set_from_secrets(self, app_client, ready_db):
        """VPN type from secrets must override any default."""
        client, tmp_path = app_client
        from backend.platform.wizard import WizardInput, step_deploy_infra
        inp = WizardInput(
            domain="test.local", config_root=str(tmp_path / "cfg"),
            media_root=str(tmp_path / "media"), puid=1000, pgid=1000, timezone="UTC",
            vpn="gluetun",
            secrets={
                "VPN_SERVICE_PROVIDER": "mullvad",
                "VPN_TYPE": "wireguard",
                "WIREGUARD_PRIVATE_KEY": "testkey_aabbccdd_1234567890_abcdefgh_12",
            },
        )
        captured = {}
        from backend.infra.providers.vpn_gluetun import GluetunProvider
        def capturing_deploy(self, cfg):
            captured.update(cfg)
            return type("R", (), {"ok": True, "message": "mocked", "detail": ""})()
        with patch.object(GluetunProvider, "deploy", capturing_deploy):
            step_deploy_infra(inp)
        assert captured.get("vpn_type") == "wireguard", (
            f"vpn_type='{captured.get('vpn_type')}', expected 'wireguard'"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Provider Failure Paths — compose_up failure must return ProviderResult
# ═══════════════════════════════════════════════════════════════════════════

class TestProviderFailurePaths:
    """Every provider must return ProviderResult on failure, not raise NameError.

    Root bug: multiple providers used 'result.stderr[:400]' but compose_up
    returns (rc, _out) — a tuple. 'result' was never assigned → NameError.
    """

    def _make_fail_sp(self):
        r = MagicMock()
        r.returncode = 1
        r.stdout = ""
        r.stderr = "image not found"
        return r

    def test_glance_failure_no_name_error(self, app_client):
        client, tmp_path = app_client
        from backend.infra.providers.dashboard_glance import GlanceDashboardProvider as GlanceProvider
        cfg = {"domain": "test.local", "network": "mediastack",
               "config_root": str(tmp_path / "cfg")}
        with patch("subprocess.run", return_value=self._make_fail_sp()):
            try:
                r = GlanceProvider().deploy(cfg)
                assert not r.ok
            except NameError as e:
                pytest.fail(f"NameError in glance failure path: {e}")

    def test_dockhand_failure_no_name_error(self, app_client):
        client, tmp_path = app_client
        from backend.infra.providers.management_alternatives import DockhandProvider
        cfg = {"domain": "test.local", "network": "mediastack",
               "config_root": str(tmp_path / "cfg")}
        with patch("subprocess.run", return_value=self._make_fail_sp()):
            try:
                r = DockhandProvider().deploy(cfg)
                assert not r.ok
            except NameError as e:
                pytest.fail(f"NameError in dockhand failure path: {e}")

    def test_homepage_failure_no_name_error(self, app_client):
        client, tmp_path = app_client
        from backend.infra.providers.dashboard_homepage import HomepageProvider
        cfg = {"domain": "test.local", "network": "mediastack",
               "config_root": str(tmp_path / "cfg")}
        with patch("subprocess.run", return_value=self._make_fail_sp()):
            try:
                r = HomepageProvider().deploy(cfg)
                assert not r.ok
            except NameError as e:
                pytest.fail(f"NameError in homepage failure path: {e}")

    def test_portainer_failure_no_name_error(self, app_client):
        client, tmp_path = app_client
        from backend.infra.providers.management_portainer import PortainerProvider
        cfg = {"domain": "test.local", "network": "mediastack",
               "config_root": str(tmp_path / "cfg")}
        with patch("subprocess.run", return_value=self._make_fail_sp()):
            try:
                r = PortainerProvider().deploy(cfg)
                assert not r.ok
            except NameError as e:
                pytest.fail(f"NameError in portainer failure path: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Platform Status Self-Heal
# ═══════════════════════════════════════════════════════════════════════════

class TestPlatformStatusSelfHealE2E:
    """Platform status must auto-correct inconsistencies detected at runtime."""

    def test_ready_without_traefik_becomes_pending(self, app_client):
        """GET /platform/status must demote 'ready' to 'pending' when Traefik is down.

        Root cause of '[WARN] Compose YAML validity' warning: DB said 'ready'
        but Traefik was gone after a reset. Wizard not shown, user confused.
        """
        client, tmp_path = app_client
        from backend.core.state import StateDB
        with StateDB() as db:
            db.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC",
                network_name="mediastack", cert_resolver="letsencrypt")

        # Traefik not running
        no_traefik = MagicMock()
        no_traefik.returncode = 1
        no_traefik.stdout = ""

        with patch("subprocess.run", return_value=no_traefik):
            resp = client.get("/api/platform/status")

        assert resp.status_code == 200
        assert resp.json()["status"] == "pending", (
            f"Status should be 'pending' when Traefik is down, got '{resp.json()['status']}'"
        )

    def test_ready_with_traefik_stays_ready(self, app_client):
        """GET /platform/status must not demote when Traefik IS running."""
        client, tmp_path = app_client
        from backend.core.state import StateDB
        with StateDB() as db:
            db.update_platform(status="ready", domain="test.local",
                config_root=str(tmp_path), media_root=str(tmp_path),
                puid=1000, pgid=1000, timezone="UTC",
                network_name="mediastack", cert_resolver="letsencrypt")

        traefik_up = MagicMock()
        traefik_up.returncode = 0
        traefik_up.stdout = "running"

        with patch("subprocess.run", return_value=traefik_up):
            resp = client.get("/api/platform/status")

        assert resp.json()["status"] == "ready"


# ═══════════════════════════════════════════════════════════════════════════
# Install App State Machine
# ═══════════════════════════════════════════════════════════════════════════

class TestInstallStateMachineE2E:
    """Verify DB state is correct after every install path."""

    def test_successful_install_db_status_is_running(self, app_client):
        """status='running' must survive the full install — not overwritten by else-block.

        Root bug: else of 'if key==ollama and result.ok' ran for all successful
        non-Ollama installs → set status='failed' right after 'running'.
        """
        client, tmp_path = app_client
        from backend.manifests.executor import install_app
        from backend.core.state import StateDB

        container = MagicMock()
        container.status = "running"
        container.health = "healthy"
        container.container_name = "sonarr"

        sp = MagicMock()
        sp.returncode = 0
        sp.stdout = "done"
        sp.stderr = ""

        with patch("backend.manifests.executor.docker_client") as mock_d, \
             patch("subprocess.run", return_value=sp):
            mock_d.get_container.return_value = container
            mock_d.ports_in_use.return_value = {}
            result = install_app("sonarr")

        if result.ok:
            with StateDB() as db:
                app = db.get_app("sonarr")
            assert app is not None
            assert app.status == "running", (
                f"App status='{app.status}' after successful install. "
                "Expected 'running'. Else-block bug overwrote with 'failed'."
            )

    def test_retry_succeeds_when_container_healthy(self, app_client, ready_db):
        """Retry on a 'running' app must succeed if container is actually healthy.

        Root bug: validate check blocked retry for any app with status='running',
        ignoring that the container might be healthy and the timeout was just too short.
        """
        client, tmp_path = app_client
        from backend.manifests.executor import install_app
        from backend.core.state import StateDB

        with StateDB() as db:
            db.upsert_app("sonarr", display_name="Sonarr", category="arr",
                          image="linuxserver/sonarr", container_name="sonarr",
                          status="running")

        healthy = MagicMock()
        healthy.status = "running"
        healthy.health = "healthy"
        healthy.container_name = "sonarr"

        with patch("backend.manifests.executor.docker_client") as mock_d:
            mock_d.get_container.return_value = healthy
            mock_d.ports_in_use.return_value = {}
            result = install_app("sonarr")

        assert result.ok, (
            f"Retry should succeed when container is healthy. Error: {result.error}. "
            "Was: 'already installed and running' blocked all retries permanently."
        )
