"""tests/test_infra.py

Tests for the infrastructure slot system, provider registry, swap engine,
and infra API routes.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.core import state as state_mod
from backend.core.state import StateDB, init_db
from backend.infra.base import InfraProvider, ProviderResult
from backend.infra.registry import (
    SwapResult,
    _REGISTRY,
    get_provider,
    list_providers,
    register,
    swap_slot,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "state.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def ready_db(db: Path):
    with StateDB() as s:
        s.update_platform(status="ready", domain="example.com",
                          config_root="/tmp/config", media_root="/tmp/media",
                          network_name="mediastack", cert_resolver="letsencrypt")
    return db


@pytest.fixture
def api_client(ready_db: Path):
    from backend.api.main import app
    with TestClient(app, base_url="http://localhost") as c:
        # Override the DB path AFTER lifespan runs (which sets config.db_path)
        state_mod.configure(ready_db)
        yield c


# ── ProviderResult ────────────────────────────────────────────────────────


class TestProviderResult:
    def test_success(self):
        r = ProviderResult.success("All good", data={"key": "val"})
        assert r.ok
        assert r.message == "All good"
        assert r.data["key"] == "val"

    def test_failure(self):
        r = ProviderResult.failure("Broke.", "details here")
        assert not r.ok
        assert r.detail == "details here"


# ── Registry ──────────────────────────────────────────────────────────────


class TestRegistry:
    def test_get_known_provider(self):
        p = get_provider("auth", "tinyauth")
        assert p.key == "tinyauth"
        assert p.slot == "auth"

    def test_get_unknown_provider_raises(self):
        with pytest.raises(KeyError, match="nonexistent"):
            get_provider("auth", "nonexistent")

    def test_list_all_providers(self):
        providers = list_providers()
        keys = [p["key"] for p in providers]
        assert "tinyauth" in keys
        assert "cloudflared" in keys

    def test_list_providers_filtered_by_slot(self):
        auth_providers = list_providers(slot="auth")
        assert all(p["slot"] == "auth" for p in auth_providers)

    def test_register_custom_provider(self):
        class MockProvider(InfraProvider):
            slot = "management"
            key = "mock_mgmt"
            display_name = "Mock Management"
            def deploy(self, cfg): return ProviderResult.success("ok")
            def remove(self): return ProviderResult.success("ok")
            def verify(self): return ProviderResult.success("ok")

        register(MockProvider)
        p = get_provider("management", "mock_mgmt")
        assert p.display_name == "Mock Management"
        # Cleanup
        _REGISTRY.pop(("management", "mock_mgmt"), None)


# ── Tinyauth provider ─────────────────────────────────────────────────────


class TestTinyauthProvider:
    def test_deploy_fails_no_docker(self, ready_db: Path):
        p = get_provider("auth", "tinyauth")
        with patch("backend.infra.providers.auth_tinyauth.write_fragment") as mock_frag:
            mock_frag.return_value = Path("/tmp/tinyauth.yaml")
            with patch("backend.infra.providers.auth_tinyauth.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="connection refused")
                with patch("pathlib.Path.mkdir"):
                    result = p.deploy({"domain": "example.com", "users": "admin:hash"})
        assert not result.ok
        assert "failed to start" in result.message.lower() or "tinyauth" in result.message.lower()

    def test_deploy_success(self, ready_db: Path):
        p = get_provider("auth", "tinyauth")
        with patch("backend.infra.providers.auth_tinyauth.write_fragment") as mock_frag:
            mock_frag.return_value = Path("/tmp/tinyauth.yaml")
            with patch("backend.infra.providers.auth_tinyauth.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                with patch("pathlib.Path.mkdir"):
                    result = p.deploy({"domain": "example.com", "users": "admin:hash"})
        assert result.ok
        # Verify slot was updated
        with StateDB() as s:
            slot = s.get_slot("auth")
        assert slot.provider == "tinyauth"
        assert slot.status == "active"

    def test_verify_container_not_running(self):
        p = get_provider("auth", "tinyauth")
        with patch("backend.infra.providers.auth_tinyauth.docker_client.get_container",
                   return_value=None):
            result = p.verify()
        assert not result.ok
        assert "not running" in result.message

    def test_verify_container_running(self):
        p = get_provider("auth", "tinyauth")
        mock_c = MagicMock()
        mock_c.status = "running"
        mock_c.health = "healthy"
        with patch("backend.infra.providers.auth_tinyauth.docker_client.get_container",
                   return_value=mock_c):
            with patch("backend.infra.providers.auth_tinyauth.httpx.get") as mock_http:
                mock_http.return_value = MagicMock(status_code=200)
                result = p.verify()
        assert result.ok

    def test_protect_is_noop(self):
        p = get_provider("auth", "tinyauth")
        result = p.protect("sonarr.example.com")
        assert result.ok

    def test_export_users(self, ready_db: Path):
        with StateDB() as s:
            s.update_slot("auth", provider="tinyauth", status="active",
                          config={"users": "admin:$2b$10$hash1,user2:$2b$10$hash2"})
        p = get_provider("auth", "tinyauth")
        result = p.export_users()
        assert result.ok
        assert result.data is not None


# ── Cloudflare provider ───────────────────────────────────────────────────


class TestCloudflareTunnelProvider:
    def test_deploy_success(self, ready_db: Path):
        p = get_provider("tunnel", "cloudflared")
        with patch("backend.infra.providers.tunnel_cloudflare.write_fragment") as mock_frag:
            mock_frag.return_value = Path("/tmp/cloudflared.yaml")
            with patch("backend.infra.providers.tunnel_cloudflare.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                result = p.deploy({"domain": "example.com", "auto_register": True})
        assert result.ok
        with StateDB() as s:
            tp = s.get_tunnel_provider("cloudflared")
        assert tp is not None
        assert tp["status"] == "active"

    def test_list_hostnames_empty(self, ready_db: Path):
        p = get_provider("tunnel", "cloudflared")
        result = p.list_hostnames()
        assert result.ok
        assert result.data["hostnames"] == []

    def test_verify_not_running(self):
        p = get_provider("tunnel", "cloudflared")
        with patch("backend.infra.providers.tunnel_cloudflare.docker_client.get_container",
                   return_value=None):
            result = p.verify()
        assert not result.ok


# ── Swap engine ───────────────────────────────────────────────────────────


class TestSwapEngine:
    def test_swap_unknown_provider_fails(self, ready_db: Path):
        result = swap_slot("auth", "tinyauth", "nonexistent_auth", {})
        assert not result.ok
        assert "nonexistent_auth" in result.error

    def test_swap_records_migration(self, ready_db: Path):
        # Mock both providers to succeed
        with patch("backend.infra.registry.get_provider") as mock_get:
            mock_old = MagicMock()
            mock_new = MagicMock()
            mock_old.key = "tinyauth"
            mock_new.key = "authelia"
            mock_old.pre_migration_snapshot.return_value = ProviderResult.success("ok", data={})
            mock_new.deploy.return_value = ProviderResult.success("deployed")
            mock_new.verify.return_value = ProviderResult.success("verified")
            mock_old.remove.return_value = ProviderResult.success("removed")
            mock_old.export_users.return_value = ProviderResult.success("exported", data={"users": []})
            mock_get.side_effect = lambda slot, key: mock_old if key == "tinyauth" else mock_new

            result = swap_slot("auth", "tinyauth", "authelia", {})

        assert result.ok
        assert not result.rolled_back
        step_names = [s.name for s in result.steps]
        assert "snapshot" in step_names
        assert "deploy_new" in step_names
        assert "verify_new" in step_names
        assert "remove_old" in step_names

    def test_swap_rolls_back_on_verify_failure(self, ready_db: Path):
        with patch("backend.infra.registry.get_provider") as mock_get:
            mock_old = MagicMock()
            mock_new = MagicMock()
            mock_old.key = "tinyauth"
            mock_new.key = "authelia"
            mock_old.pre_migration_snapshot.return_value = ProviderResult.success("ok", data={})
            mock_new.deploy.return_value = ProviderResult.success("deployed")
            mock_new.verify.return_value = ProviderResult.failure("Authelia not responding")
            mock_old.restore_from_snapshot.return_value = ProviderResult.success("restored")
            mock_old.export_users.return_value = ProviderResult.success("ok", data={"users": []})
            mock_get.side_effect = lambda slot, key: mock_old if key == "tinyauth" else mock_new

            result = swap_slot("auth", "tinyauth", "authelia", {})

        assert not result.ok
        assert result.rolled_back
        assert any(s.name == "rollback" and s.status == "ok" for s in result.steps)


# ── Infra API routes ──────────────────────────────────────────────────────


class TestInfraAPI:
    @pytest.fixture(autouse=True)
    def reset_slots(self, ready_db):
        """Reset all infra slots to empty state before each test."""
        import backend.core.state as _sm
        _sm.configure(ready_db)          # ensure correct DB before reset
        with StateDB() as s:
            for slot in ("auth", "tunnel", "vpn", "management", "dashboard"):
                s.update_slot(slot, status="empty", provider=None, config={})

    @pytest.fixture(autouse=True)
    def mock_docker(self):
        with patch("backend.core.docker_client._connect", return_value=MagicMock()):
            yield

    def test_get_all_slots(self, api_client: TestClient):
        r = api_client.get("/api/infra/slots")
        assert r.status_code == 200
        slots = r.json()
        slot_names = [s["slot"] for s in slots]
        assert set(slot_names) == {"auth", "tunnel", "vpn", "management", "dashboard"}

    def test_get_single_slot(self, api_client: TestClient):
        r = api_client.get("/api/infra/slots/auth")
        assert r.status_code == 200
        data = r.json()
        assert data["slot"] == "auth"
        assert data["status"] == "empty"

    def test_get_unknown_slot(self, api_client: TestClient):
        r = api_client.get("/api/infra/slots/notaslot")
        assert r.status_code == 404

    def test_list_all_providers(self, api_client: TestClient):
        r = api_client.get("/api/infra/providers")
        assert r.status_code == 200
        providers = r.json()
        keys = [p["key"] for p in providers]
        assert "tinyauth" in keys
        assert "cloudflared" in keys

    def test_list_providers_for_slot(self, api_client: TestClient):
        r = api_client.get("/api/infra/providers/auth")
        assert r.status_code == 200
        providers = r.json()
        assert all(p["slot"] == "auth" for p in providers)
        assert any(p["key"] == "tinyauth" for p in providers)

    def test_deploy_to_empty_slot(self, api_client: TestClient):
        with patch("backend.api.infra.get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.deploy.return_value = ProviderResult.success("Deployed.")
            mock_get.return_value = mock_provider
            r = api_client.post("/api/infra/auth/deploy",
                                json={"provider": "tinyauth", "config": {}})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_deploy_to_active_slot_blocked(self, api_client: TestClient, ready_db: Path):
        with StateDB() as s:
            s.update_slot("auth", provider="tinyauth", status="active")
        r = api_client.post("/api/infra/auth/deploy",
                            json={"provider": "authelia", "config": {}})
        assert r.status_code == 409

    def test_swap_no_active_provider_blocked(self, api_client: TestClient):
        r = api_client.post("/api/infra/auth/swap",
                            json={"to_provider": "authelia", "config": {}})
        assert r.status_code == 409

    def test_swap_same_provider_blocked(self, api_client: TestClient, ready_db: Path):
        with StateDB() as s:
            s.update_slot("auth", provider="tinyauth", status="active")
        r = api_client.post("/api/infra/auth/swap",
                            json={"to_provider": "tinyauth", "config": {}})
        assert r.status_code == 400

    def test_verify_no_provider(self, api_client: TestClient):
        r = api_client.post("/api/infra/auth/verify")
        assert r.status_code == 404

    def test_get_migrations_empty(self, api_client: TestClient):
        r = api_client.get("/api/infra/migrations")
        assert r.status_code == 200
        assert r.json() == []
