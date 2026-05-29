"""tests/test_session_a.py

Tests for Session A:
  - CF hostname auto-registration in install_app / remove_app
  - Smoke tests (TCP connectivity + HTTP check post-install)
  - Health scheduler (start/stop, cycle timing, settings)
  - DNS-only A record for media apps
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import json
import time

import pytest

from backend.core.state import StateDB, init_db
from backend.manifests.loader import clear_cache, load_manifest
from backend.manifests.executor import (
    _get_active_tunnel_provider,
    _register_app_hostname,
    _unregister_app_hostname,
    _run_smoke_test,
)
from backend.health.scheduler import (
    start_scheduler,
    stop_scheduler,
    scheduler_status,
    _load_cycle_config,
    DEFAULT_INTERVAL,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "state.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def platform_stub(db: Path):
    """Configure a ready platform in the test DB."""
    with StateDB() as s:
        s.update_platform(
            status="ready",
            domain="testdomain.com",
            config_root="/tmp/config",
            media_root="/tmp/media",
            network_name="mediastack",
            cert_resolver="letsencrypt",
        )
    return db


# ── CF hostname registration ───────────────────────────────────────────────


class TestCFHostnameRegistration:
    def test_no_tunnel_returns_skipped(self, db: Path):
        """When no tunnel is active, hostname registration is skipped gracefully."""
        manifest = load_manifest("sonarr")
        with patch("backend.manifests.executor.StateDB") as mock_db_cls:
            mock_db = MagicMock()
            mock_db.__enter__ = lambda s: mock_db
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.get_slot.return_value = MagicMock(status="empty", provider=None)
            mock_db_cls.return_value = mock_db
            provider = _get_active_tunnel_provider()
        assert provider is None

    def test_register_management_app(self, platform_stub: Path):
        """Management apps get a CF Tunnel ingress registration."""
        manifest = load_manifest("sonarr")
        assert manifest.service_type == "management"

        mock_provider = MagicMock()
        mock_provider.register_hostname.return_value = MagicMock(
            ok=True,
            message="Hostname sonarr.testdomain.com registered.",
        )

        with patch("backend.manifests.executor._get_active_tunnel_provider",
                   return_value=mock_provider):
            with StateDB() as db:
                platform = db.get_platform()
            step = _register_app_hostname("sonarr", manifest, platform)

        assert step.status == "ok"
        mock_provider.register_hostname.assert_called_once()
        call_args = mock_provider.register_hostname.call_args[0]
        assert "sonarr.testdomain.com" in call_args[0]
        assert "sonarr" in call_args[1]  # target URL contains app key

    def test_register_media_app_uses_dns_only(self, platform_stub: Path):
        """Media apps get a DNS-only A record, not a CF Tunnel ingress."""
        manifest = load_manifest("plex")
        assert manifest.service_type == "media"

        mock_provider = MagicMock(spec=["register_hostname", "register_dns_only_record"])
        mock_provider.register_dns_only_record.return_value = MagicMock(
            ok=True,
            message="DNS-only A record created.",
        )

        with patch("backend.manifests.executor._get_active_tunnel_provider",
                   return_value=mock_provider):
            with StateDB() as db:
                platform = db.get_platform()
            step = _register_app_hostname("plex", manifest, platform)

        # Should call dns_only, not register_hostname
        mock_provider.register_dns_only_record.assert_called_once()
        mock_provider.register_hostname.assert_not_called()

    def test_media_app_without_dns_only_method_skips(self, platform_stub: Path):
        """If provider lacks register_dns_only_record, skip with guidance."""
        manifest = load_manifest("jellyfin")
        assert manifest.service_type == "media"

        mock_provider = MagicMock(spec=["register_hostname"])  # no dns_only_record
        del mock_provider.register_dns_only_record  # ensure attribute missing

        with patch("backend.manifests.executor._get_active_tunnel_provider",
                   return_value=mock_provider):
            with StateDB() as db:
                platform = db.get_platform()
            step = _register_app_hostname("jellyfin", manifest, platform)

        assert step.status == "skipped"
        assert "DNS-only" in step.message or "manually" in step.message.lower()

    def test_internal_app_always_skipped(self, platform_stub: Path):
        """Internal service_type apps never get external hostname registration."""
        manifest = load_manifest("sonarr")
        object.__setattr__(manifest, "service_type", "internal")

        mock_provider = MagicMock()
        with patch("backend.manifests.executor._get_active_tunnel_provider",
                   return_value=mock_provider):
            with StateDB() as db:
                platform = db.get_platform()
            step = _register_app_hostname("sonarr", manifest, platform)

        assert step.status == "skipped"
        mock_provider.register_hostname.assert_not_called()

    def test_registration_failure_returns_warning_not_error(self, platform_stub: Path):
        """Hostname registration failure is a warning — install still succeeds."""
        manifest = load_manifest("sonarr")
        mock_provider = MagicMock()
        mock_provider.register_hostname.return_value = MagicMock(
            ok=False,
            message="CF API credentials not configured.",
            detail="Set CF_DNS_API_TOKEN.",
        )

        with patch("backend.manifests.executor._get_active_tunnel_provider",
                   return_value=mock_provider):
            with StateDB() as db:
                platform = db.get_platform()
            step = _register_app_hostname("sonarr", manifest, platform)

        # Non-fatal: install should continue
        assert step.status == "warning"
        assert step.name == "hostname_register"

    def test_unregister_calls_provider(self, platform_stub: Path):
        manifest = load_manifest("sonarr")
        mock_provider = MagicMock()
        mock_provider.unregister_hostname.return_value = MagicMock(ok=True)

        with patch("backend.manifests.executor._get_active_tunnel_provider",
                   return_value=mock_provider):
            _unregister_app_hostname("sonarr", manifest)

        mock_provider.unregister_hostname.assert_called_once()
        called_hostname = mock_provider.unregister_hostname.call_args[0][0]
        assert "testdomain.com" in called_hostname

    def test_unregister_no_tunnel_does_nothing(self, db: Path):
        manifest = load_manifest("sonarr")
        # No tunnel configured — function must return cleanly with no provider calls
        with patch("backend.manifests.executor._get_active_tunnel_provider",
                   return_value=None) as mock_get:
            result = _unregister_app_hostname("sonarr", manifest)
            # Assert: provider lookup was called, no tunnel provider was invoked
            mock_get.assert_called_once()
            assert result is None, "Should return None when no tunnel provider active"

    def test_no_domain_skips_registration(self, db: Path):
        manifest = load_manifest("sonarr")
        mock_provider = MagicMock()

        # Platform has no domain set
        with StateDB() as s:
            s.update_platform(status="ready", domain="",
                              config_root="/tmp/c", media_root="/tmp/m",
                              network_name="ms", cert_resolver="le")

        with patch("backend.manifests.executor._get_active_tunnel_provider",
                   return_value=mock_provider):
            with StateDB() as db_:
                platform = db_.get_platform()
            step = _register_app_hostname("sonarr", manifest, platform)

        assert step.status == "skipped"
        mock_provider.register_hostname.assert_not_called()


# ── Smoke tests ───────────────────────────────────────────────────────────


@pytest.mark.real_smoke_test
class TestSmokeTests:
    def test_no_port_skips(self):
        """Apps without a web port skip the smoke test."""
        manifest = load_manifest("sonarr")
        # Temporarily zero out the port
        object.__setattr__(manifest, "web_port", None)
        step = _run_smoke_test("sonarr", manifest)
        assert step.status == "skipped"
        assert step.name == "smoke_test"

    def test_tcp_refused_returns_error(self, db: Path):
        """TCP connection refused → smoke test error, app marked unhealthy."""
        manifest = load_manifest("sonarr")  # port 8989
        # sonarr's manifest sets start_grace_s=90 — override to 1 so the
        # smoke-test poll loop completes inside the 15s pytest-timeout.
        # The behaviour under test (refused → error) is timing-independent.
        object.__setattr__(manifest, "start_grace_s", 1)

        with patch("socket.create_connection", side_effect=ConnectionRefusedError):
            step = _run_smoke_test("sonarr", manifest)

        assert step.status == "error"
        assert "not listening" in step.message.lower() or "refused" in step.message.lower()

    def test_tcp_success_records_ok(self, db: Path):
        """TCP success with no HTTP check defined → smoke test ok."""
        manifest = load_manifest("sonarr")
        object.__setattr__(manifest, "health_checks", [])  # no HTTP checks

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: mock_sock
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("socket.create_connection", return_value=mock_sock):
            step = _run_smoke_test("sonarr", manifest)

        assert step.status == "ok"
        assert "accepting connections" in step.message.lower() or "port" in step.message.lower()

    def test_tcp_success_http_200_is_ok(self, db: Path):
        """TCP + HTTP 200 → fully passing smoke test."""
        manifest = load_manifest("sonarr")

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: mock_sock
        mock_sock.__exit__ = MagicMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("socket.create_connection", return_value=mock_sock):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                step = _run_smoke_test("sonarr", manifest)

        assert step.status == "ok"

    def test_tcp_success_http_fail_is_warning(self, db: Path):
        """TCP works but HTTP fails → warning (may still be starting up)."""
        manifest = load_manifest("sonarr")

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: mock_sock
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("socket.create_connection", return_value=mock_sock):
            with patch("urllib.request.urlopen", side_effect=Exception("connection reset")):
                step = _run_smoke_test("sonarr", manifest)

        assert step.status == "warning"
        assert "initialising" in step.message.lower() or "starting" in step.message.lower()

    def test_smoke_test_writes_health_check(self, db: Path):
        """Smoke test result is persisted to the health_checks table."""
        manifest = load_manifest("sonarr")
        object.__setattr__(manifest, "health_checks", [])

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: mock_sock
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("socket.create_connection", return_value=mock_sock):
            step = _run_smoke_test("sonarr", manifest)

        with StateDB() as s:
            row = s._c.execute(
                "SELECT * FROM health_checks WHERE subject_key='sonarr' AND check_name='smoke_test'"
            ).fetchone()
        assert row is not None
        assert row["status"] in ("ok", "warning", "error")


# ── Health scheduler ──────────────────────────────────────────────────────


class TestHealthScheduler:
    def teardown_method(self, method):
        """Clean up any running scheduler after each test."""
        stop_scheduler()

    def test_initial_status_not_started(self):
        """Before start(), scheduler reports not_started."""
        stop_scheduler()  # ensure clean state
        status = scheduler_status()
        assert status["running"] is False

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        """start_scheduler() creates a running asyncio task."""
        stop_scheduler()
        start_scheduler()
        await asyncio.sleep(0)  # let event loop process task creation
        status = scheduler_status()
        assert status["running"] is True
        stop_scheduler()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop_scheduler() cancels the task."""
        start_scheduler()
        await asyncio.sleep(0)
        stop_scheduler()
        await asyncio.sleep(0.05)
        status = scheduler_status()
        assert status["running"] is False

    @pytest.mark.asyncio
    async def test_double_start_idempotent(self):
        """Calling start_scheduler() twice doesn't create duplicate tasks."""
        start_scheduler()
        await asyncio.sleep(0)
        start_scheduler()  # second call should be no-op
        await asyncio.sleep(0)
        status = scheduler_status()
        assert status["running"] is True

    @pytest.mark.asyncio
    async def test_load_cycle_config_defaults(self, db: Path):
        """Default config is returned when no settings are stored."""
        cfg = await _load_cycle_config()
        assert cfg["interval"] >= 10
        assert cfg["ollama_url"].startswith("http")  # default is http://localhost:11434 or http://ollama:11434
        assert cfg["ntfy_topic"] == "mediastack"

    @pytest.mark.asyncio
    async def test_load_cycle_config_from_db(self, db: Path):
        """Custom interval is read from settings DB."""
        with StateDB() as s:
            s.set_setting("health_check_interval_secs", "60")
            s.set_setting("ntfy_topic", "my-alerts")
        cfg = await _load_cycle_config()
        assert cfg["interval"] == 60
        assert cfg["ntfy_topic"] == "my-alerts"

    @pytest.mark.asyncio
    async def test_interval_minimum_30s_async(self, db: Path):
        """Interval is floored at 30 seconds — matches DNS challenge delay."""
        with StateDB() as s:
            s.set_setting("health_check_interval_secs", "2")
        cfg = await _load_cycle_config()
        assert cfg["interval"] == 30

    def test_default_interval_value(self):
        assert DEFAULT_INTERVAL == 60  # raised from 30 — gives room for DNS propagation


# ── Health API scheduler endpoints ────────────────────────────────────────


class TestHealthSchedulerAPI:
    @pytest.fixture
    def api_client(self, db: Path):
        import backend.core.state as sm
        from backend.api.main import app
        from fastapi.testclient import TestClient
        with TestClient(app, base_url="http://localhost") as c:
            sm.configure(db)
            yield c

    def test_get_scheduler_status(self, api_client):
        r = api_client.get("/api/health/scheduler")
        assert r.status_code == 200
        data = r.json()
        assert "running" in data
        assert "state" in data

    def test_update_health_settings_interval(self, api_client):
        r = api_client.put("/api/health/settings?interval_secs=45")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["updated"]["health_check_interval_secs"] == 45

    def test_update_health_settings_ntfy(self, api_client):
        r = api_client.put("/api/health/settings?ntfy_topic=homelab-alerts")
        assert r.status_code == 200

    def test_update_health_settings_floor(self, api_client):
        """Interval below 30 is floored to 30."""
        r = api_client.put("/api/health/settings?interval_secs=3")
        assert r.status_code == 200
        assert r.json()["updated"]["health_check_interval_secs"] == 30


# ── CF provider DNS-only method ───────────────────────────────────────────


class TestCFDNSOnlyRecord:
    def test_method_exists_on_provider(self):
        """CloudflareTunnelProvider has register_dns_only_record method."""
        from backend.infra.providers.tunnel_cloudflare import CloudflareTunnelProvider
        p = CloudflareTunnelProvider()
        assert hasattr(p, "register_dns_only_record")
        assert callable(p.register_dns_only_record)

    def test_returns_failure_without_credentials(self):
        """Without CF credentials, register_dns_only_record returns failure."""
        from backend.infra.providers.tunnel_cloudflare import CloudflareTunnelProvider
        p = CloudflareTunnelProvider()
        with patch.object(p, "_load_cf_credentials",
                          return_value=(None, None, None, None)):
            result = p.register_dns_only_record("plex.example.com")
        assert result.ok is False
        assert "credentials" in result.message.lower()

    def test_get_public_ip_succeeds(self):
        """_get_public_ip returns an IP string when ipify responds."""
        from backend.infra.providers.tunnel_cloudflare import CloudflareTunnelProvider
        mock_resp = MagicMock()
        mock_resp.text = "1.2.3.4"
        with patch("httpx.get", return_value=mock_resp):
            ip = CloudflareTunnelProvider._get_public_ip()
        assert ip == "1.2.3.4"

    def test_get_public_ip_fails_gracefully(self):
        """_get_public_ip returns None when all services fail."""
        from backend.infra.providers.tunnel_cloudflare import CloudflareTunnelProvider
        with patch("httpx.get", side_effect=Exception("network error")):
            ip = CloudflareTunnelProvider._get_public_ip()
        assert ip is None
