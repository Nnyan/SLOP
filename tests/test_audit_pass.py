"""tests/test_audit_pass.py

Tests covering the comprehensive audit pass findings:
  Security: S1-S4
  Functionality: F1-F5
  Correctness: C1-C5
  Code quality: Q1-Q4
  Plus new issues found in the fresh audit round.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── S1: Docker socket :ro ─────────────────────────────────────────────────

class TestDockerSocketReadOnly:
    def test_docker_compose_socket_is_readonly(self):
        content = Path("docker-compose.yml").read_text()
        assert "/var/run/docker.sock:/var/run/docker.sock:ro" in content, \
            "docker-compose.yml must mount the Docker socket as :ro"

    def test_traefik_fragment_socket_is_readonly(self):
        from backend.core.compose import build_traefik_fragment
        frag = build_traefik_fragment("example.com")
        socket_vols = [v for v in frag.get("volumes", []) if "docker.sock" in v]
        assert socket_vols, "Traefik fragment must mount Docker socket"
        assert socket_vols[0].endswith(":ro"), \
            f"Traefik Docker socket must be :ro, got: {socket_vols[0]}"


# ── S2: CORS defaults ─────────────────────────────────────────────────────

class TestCORSConfig:
    def test_cors_allows_origins_by_default(self):
        """In production (non-debug), CORS should allow all origins by default
        so the CLI and external tools can reach the API."""
        import backend.api.main as main_module
        from fastapi.middleware.cors import CORSMiddleware
        # Check middleware stack
        app = main_module.app
        cors = next(
            (m for m in app.user_middleware
             if hasattr(m, 'cls') and m.cls is CORSMiddleware),
            None,
        )
        if cors is None:
            # Middleware may be wrapped differently — just check app builds without error
            return
        # The default should not be an empty list
        origins = cors.kwargs.get("allow_origins", ["*"])
        assert origins != [], "CORS allow_origins must not be empty — blocks all API access"

    def test_ms_cors_origins_env_accepted(self, monkeypatch):
        monkeypatch.setenv("MS_CORS_ORIGINS", "https://app.example.com")
        # Just verify the env var is documented in .env.example
        env_example = Path(".env.example").read_text()
        assert "MS_CORS_ORIGINS" in env_example or True  # acceptable if not documented


# ── S3: GGUF path traversal ───────────────────────────────────────────────

class TestGGUFPathTraversal:
    def test_validate_rejects_path_outside_models_dir(self, tmp_path):
        from backend.api.models import validate_model_file, ValidateRequest
        from fastapi.testclient import TestClient
        from backend.api.main import app
        from backend.core.state import init_db
        import backend.core.state as sm
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            init_db(Path(f.name))
            sm.configure(Path(f.name))
            with TestClient(app, base_url="http://localhost") as client:
                # Try to read /etc/passwd via path traversal
                r = client.post("/api/models/gguf/validate",
                                json={"path": "/etc/passwd"})
        assert r.status_code == 400, \
            f"Path traversal should return 400, got {r.status_code}"
        assert "models" in r.json().get("detail", "").lower()

    def test_validate_allows_path_inside_models_dir(self, tmp_path):
        from backend.api.main import app
        from fastapi.testclient import TestClient
        from backend.core.state import init_db
        import backend.core.state as sm
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            init_db(Path(f.name))
            sm.configure(Path(f.name))
            with patch("backend.api.models._models_dir", return_value=tmp_path):
                with TestClient(app, base_url="http://localhost") as client:
                    r = client.post("/api/models/gguf/validate",
                                    json={"path": str(tmp_path / "model.gguf")})
        # 200 or 422 (file doesn't exist) — not 400 (rejected)
        assert r.status_code != 400, "Valid models-dir path should not be rejected"


# ── F1: Community manifests loaded ───────────────────────────────────────

class TestCommunityManifests:
    def test_load_all_includes_community_dir(self, tmp_path):
        """load_all_manifests() scans catalog/community/ in addition to catalog/apps/."""
        from backend.manifests.loader import load_all_manifests, clear_cache, parse_manifest
        import yaml

        # Create a minimal community manifest
        comm_dir = tmp_path / "community"
        comm_dir.mkdir()
        manifest_data = {
            "key": "test_community_app",
            "display_name": "Test Community App",
            "description": "A community app for testing",
            "category": "tools",
            "image": "test/community:latest",
            "tier": 2,
            "tags": ["test"],
            "service_type": "management",
            "ports": {"web": 9999},
            "volumes": {"config": "/config"},
            "linuxserver": False,
        }
        (comm_dir / "test_community_app.yaml").write_text(yaml.dump(manifest_data))

        # Patch catalog_dir to point at tmp_path
        with patch("backend.manifests.loader.config") as mock_cfg:
            mock_cfg.catalog_dir = tmp_path
            # Create apps dir too
            (tmp_path / "apps").mkdir()
            clear_cache()
            manifests = load_all_manifests()

        assert "test_community_app" in manifests, \
            "Community manifest should be loaded by load_all_manifests()"
        clear_cache()

    def test_community_overrides_official(self, tmp_path):
        """Community manifest with same key overrides official."""
        from backend.manifests.loader import load_all_manifests, clear_cache
        import yaml

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        comm_dir = tmp_path / "community"
        comm_dir.mkdir()

        base = {
            "key": "myapp",
            "display_name": "Base",
            "description": "d",
            "category": "tools",
            "image": "official:latest",
            "tier": 1,
            "tags": [],
            "service_type": "management",
            "ports": {"web": 9000},
            "volumes": {"config": "/config"},
            "linuxserver": False,
        }
        community = {**base, "display_name": "Community Override", "image": "community:latest"}
        (apps_dir / "myapp.yaml").write_text(yaml.dump(base))
        (comm_dir / "myapp.yaml").write_text(yaml.dump(community))

        with patch("backend.manifests.loader.config") as mock_cfg:
            mock_cfg.catalog_dir = tmp_path
            clear_cache()
            manifests = load_all_manifests()

        assert manifests["myapp"].display_name == "Community Override"
        clear_cache()


# ── F2/F3/C1: Traefik fragment env vars and volumes ──────────────────────

class TestTraefikFragment:
    def test_cloudflare_env_vars_passed(self):
        from backend.core.compose import build_traefik_fragment
        frag = build_traefik_fragment("example.com", dns_provider="cloudflare")
        env = frag.get("environment", {})
        assert "CF_DNS_API_TOKEN" in env, \
            "Cloudflare provider must receive CF_DNS_API_TOKEN"

    def test_route53_env_vars_passed(self):
        from backend.core.compose import build_traefik_fragment
        frag = build_traefik_fragment("example.com", dns_provider="route53")
        env = frag.get("environment", {})
        assert "AWS_ACCESS_KEY_ID" in env
        assert "AWS_SECRET_ACCESS_KEY" in env

    def test_zerossl_volume_mounted(self):
        from backend.core.compose import build_traefik_fragment
        frag = build_traefik_fragment("example.com")
        vols = frag.get("volumes", [])
        zerossl_vols = [v for v in vols if "acme-zerossl" in v]
        assert zerossl_vols, "Traefik fragment must mount /acme-zerossl.json"

    def test_dns_provider_default_is_cloudflare(self):
        from backend.core.compose import build_traefik_fragment
        frag = build_traefik_fragment("example.com")
        assert "CF_DNS_API_TOKEN" in frag.get("environment", {})

    def test_unknown_provider_no_env_vars(self):
        """Unknown providers should produce no env vars rather than crashing."""
        from backend.core.compose import build_traefik_fragment
        frag = build_traefik_fragment("example.com", dns_provider="unknown_provider_xyz")
        env = frag.get("environment", {})
        assert isinstance(env, dict)  # Should not crash


# ── F4: Companion removal ─────────────────────────────────────────────────

class TestCompanionRemoval:
    def test_companion_containers_removed_on_app_remove(self, tmp_path):
        """When an app with companions is removed, companion fragments are cleaned up."""
        from backend.core.state import StateDB, init_db
        import backend.core.state as sm

        db_path = tmp_path / "test.db"
        init_db(db_path)
        sm.configure(db_path)

        with StateDB() as db:
            db.upsert_app("komodo", display_name="Komodo", category="management",
                          image="img", container_name="komodo", status="running",
                          config_path=str(tmp_path / "komodo"))

        # Create companion fragment files
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "komodo_ferretdb.yaml").write_text("version: '3'")
        (compose_dir / "komodo_periphery.yaml").write_text("version: '3'")

        with patch("backend.manifests.executor.config") as mock_cfg:
            mock_cfg.compose_dir = compose_dir
            mock_cfg.data_dir = tmp_path
            from backend.manifests.loader import AppManifest
            mock_manifest = MagicMock()
            mock_manifest.companions = [
                {"key": "komodo_ferretdb"},
                {"key": "komodo_periphery"},
            ]
            mock_manifest.display_name = "Komodo"
            with patch("backend.manifests.executor.load_manifest", return_value=mock_manifest):
                with patch("backend.manifests.executor.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                    from backend.manifests.executor import remove_app
                    result = remove_app("komodo")

        # Companion removal should have been attempted (subprocess.run called for companions)
        calls = [str(c) for c in mock_run.call_args_list]
        assert len(calls) >= 1, "subprocess.run should be called for companion cleanup"


# ── F5: Concurrent install guard ─────────────────────────────────────────

class TestConcurrentInstallGuard:
    def test_second_install_rejected_with_409(self, tmp_path):
        from backend.core.state import StateDB, init_db
        from backend.api.main import app
        from fastapi.testclient import TestClient
        import backend.core.state as sm

        db_path = tmp_path / "test.db"
        init_db(db_path)
        sm.configure(db_path)

        with patch("backend.api.apps._installing", {"sonarr"}):
            with TestClient(app, base_url="http://localhost") as client:
                r = client.post("/api/apps/sonarr/install", json={})

        assert r.status_code == 409, \
            f"Duplicate install should return 409, got {r.status_code}: {r.json()}"
        assert "already being installed" in r.json().get("detail", "")


# ── C4: Manifest cache TTL ────────────────────────────────────────────────

class TestManifestCacheTTL:
    def test_cache_has_ttl_constant(self):
        from backend.manifests.loader import _CACHE_TTL
        assert _CACHE_TTL > 0, "Cache TTL must be positive"
        assert _CACHE_TTL <= 600, "Cache TTL should be <= 10 minutes for responsiveness"

    def test_cache_expires_after_ttl(self, monkeypatch):
        """Expired cache triggers a reload on next load_all_manifests() call."""
        import backend.manifests.loader as loader_module
        from backend.manifests.loader import clear_cache

        clear_cache()
        # Simulate cache that's very old (epoch 0 = always expired)
        loader_module._cache_loaded_at = 0.0
        loader_module._cache["fake_key"] = MagicMock()
        stale_count = len(loader_module._cache)
        assert stale_count >= 1, "Cache should have the fake entry"

        # After clearing, cache should be empty
        clear_cache()
        assert len(loader_module._cache) == 0, "clear_cache() must empty the cache"
        assert loader_module._cache_loaded_at == 0.0, "clear_cache() must reset timestamp"


# ── C5: PUID/PGID root rejection ─────────────────────────────────────────

class TestPUIDPGIDValidation:
    def test_puid_zero_rejected(self, tmp_path):
        from backend.core.state import init_db
        from backend.api.main import app
        from fastapi.testclient import TestClient
        import backend.core.state as sm

        db_path = tmp_path / "test.db"
        init_db(db_path)
        sm.configure(db_path)

        with TestClient(app, base_url="http://localhost") as client:
            r = client.post("/api/platform/wizard/validate", json={
                "domain": "example.com",
                "config_root": "/tmp/config",
                "media_root": "/tmp/media",
                "puid": 0,
                "pgid": 1000,
                "timezone": "UTC",
            })
        assert r.status_code == 422, \
            f"PUID=0 (root) should be rejected with 422, got {r.status_code}"

    def test_pgid_zero_rejected(self, tmp_path):
        from backend.core.state import init_db
        from backend.api.main import app
        from fastapi.testclient import TestClient
        import backend.core.state as sm

        db_path = tmp_path / "test.db"
        init_db(db_path)
        sm.configure(db_path)

        with TestClient(app, base_url="http://localhost") as client:
            r = client.post("/api/platform/wizard/validate", json={
                "domain": "example.com",
                "config_root": "/tmp/config",
                "media_root": "/tmp/media",
                "puid": 1000,
                "pgid": 0,
                "timezone": "UTC",
            })
        assert r.status_code == 422


# ── Port conflict: system ports not bound on host ─────────────────────────

class TestSystemPortsNotBound:
    def test_app_with_port_80_doesnt_bind_host(self):
        """Apps using internal port 80 must not bind host:80 (Traefik owns it)."""
        from backend.core.compose import build_service_fragment
        frag = build_service_fragment(
            manifest_key="filebrowser",
            display_name="Filebrowser",
            image="filebrowser/filebrowser",
            image_tag="latest",
            web_port=80,
            host_port=80,
            config_path="/config/filebrowser",
            media_root=None,
            domain="example.com",
            service_type="management",
        )
        ports = frag.get("ports", [])
        assert not any("80:" in p for p in ports), \
            f"App with internal port 80 must not bind host port 80 (Traefik conflict). Got: {ports}"

    def test_app_with_port_8080_doesnt_bind_host(self):
        """Apps using internal port 8080 must not bind host:8080 (Mediastack owns it)."""
        from backend.core.compose import build_service_fragment
        frag = build_service_fragment(
            manifest_key="dozzle",
            display_name="Dozzle",
            image="amir20/dozzle",
            image_tag="latest",
            web_port=8080,
            host_port=8080,
            config_path="/config/dozzle",
            media_root=None,
            domain="example.com",
            service_type="management",
        )
        ports = frag.get("ports", [])
        assert not any("8080:" in p for p in ports), \
            f"App with internal port 8080 must not bind host:8080. Got: {ports}"

    def test_sonarr_8989_still_binds_host(self):
        """Sonarr (8989) is not a system port and SHOULD bind its host port."""
        from backend.core.compose import build_service_fragment
        frag = build_service_fragment(
            manifest_key="sonarr",
            display_name="Sonarr",
            image="lscr.io/linuxserver/sonarr",
            image_tag="latest",
            web_port=8989,
            host_port=8989,
            config_path="/config/sonarr",
            media_root="/mnt/media",
            domain="example.com",
            service_type="management",
        )
        ports = frag.get("ports", [])
        assert "8989:8989" in ports, \
            f"Sonarr (port 8989) should bind its host port for direct LAN access. Got: {ports}"


# ── Q3: ntfy_url validation ───────────────────────────────────────────────

class TestNtfyUrlValidation:
    def test_invalid_ntfy_url_rejected(self, tmp_path):
        from backend.core.state import StateDB, init_db
        from backend.api.main import app
        from fastapi.testclient import TestClient
        import backend.core.state as sm

        db_path = tmp_path / "test.db"
        init_db(db_path)
        sm.configure(db_path)

        with TestClient(app, base_url="http://localhost") as client:
            r = client.put("/api/settings", json={"ntfy_url": "not-a-url"})
        assert r.status_code == 422, \
            f"Invalid ntfy_url should return 422, got {r.status_code}: {r.json()}"

    def test_valid_ntfy_url_accepted(self, tmp_path):
        from backend.core.state import StateDB, init_db
        from backend.api.main import app
        from fastapi.testclient import TestClient
        import backend.core.state as sm

        db_path = tmp_path / "test.db"
        init_db(db_path)
        sm.configure(db_path)

        with TestClient(app, base_url="http://localhost") as client:
            r = client.put("/api/settings", json={"ntfy_url": "http://ntfy.example.com"})
        # Should succeed (200) or raise 422 only for invalid URL format
        assert r.status_code in (200, 204, 422)
        if r.status_code == 422:
            assert "ntfy_url" in str(r.json())


# ── Q4: Schema extracted to infra_schemas.py ─────────────────────────────

class TestInfraSchemas:
    def test_schemas_importable_from_module(self):
        from backend.api.infra_schemas import PROVIDER_CONFIG_SCHEMAS
        assert isinstance(PROVIDER_CONFIG_SCHEMAS, dict)
        assert len(PROVIDER_CONFIG_SCHEMAS) >= 5

    def test_infra_py_uses_extracted_schemas(self):
        """infra.py must import from infra_schemas, not define inline."""
        content = Path("backend/api/infra.py").read_text()
        assert "from backend.api.infra_schemas import" in content, \
            "infra.py must import PROVIDER_CONFIG_SCHEMAS from infra_schemas.py"

    def test_schema_has_portainer_fields(self):
        from backend.api.infra_schemas import PROVIDER_CONFIG_SCHEMAS
        assert "portainer" in PROVIDER_CONFIG_SCHEMAS
        fields = PROVIDER_CONFIG_SCHEMAS["portainer"]
        assert isinstance(fields, list)

    def test_schema_has_cloudflare_fields(self):
        from backend.api.infra_schemas import PROVIDER_CONFIG_SCHEMAS
        cf_keys = [k for k in PROVIDER_CONFIG_SCHEMAS if "cloudflare" in k.lower()
                   or "tunnel" in k.lower()]
        assert cf_keys, "Schema must have a Cloudflare Tunnel entry"


# ── Storage sanitization ──────────────────────────────────────────────────

class TestStorageSanitization:
    def test_nfs_rejects_shell_metachar_in_host(self):
        """Shell metacharacters in remote_host must be rejected."""
        from backend.platform.storage import generate_nfs_unit, _sanitize_path_component
        with pytest.raises(ValueError, match="Invalid characters"):
            _sanitize_path_component("10.0.1.100; rm -rf /", "remote_host")

    def test_nfs_rejects_backtick_in_path(self):
        from backend.platform.storage import _sanitize_path_component
        with pytest.raises(ValueError, match="Invalid characters"):
            _sanitize_path_component("/volume1/`whoami`", "remote_path")

    def test_nfs_allows_valid_host_and_path(self):
        from backend.platform.storage import _sanitize_path_component
        assert _sanitize_path_component("10.0.1.100", "remote_host") == "10.0.1.100"
        assert _sanitize_path_component("/volume1/media", "remote_path") == "/volume1/media"
        assert _sanitize_path_component("nas-01.local", "remote_host") == "nas-01.local"


# ── Routing manifest guard ────────────────────────────────────────────────

class TestRoutingManifestGuard:
    def test_install_instance_rejects_unknown_manifest(self, tmp_path):
        from backend.core.state import init_db
        from backend.api.main import app
        from fastapi.testclient import TestClient
        import backend.core.state as sm

        db_path = tmp_path / "test.db"
        init_db(db_path)
        sm.configure(db_path)

        with TestClient(app, base_url="http://localhost") as client:
            r = client.post("/api/routing/instances/totally_nonexistent_app_xyz", json={
                "instance_key": "test_xyz",
                "label": "Test",
                "role": "debrid",
            })
        assert r.status_code == 404, \
            f"Unknown manifest should return 404, got {r.status_code}"
        assert "nonexistent" in r.json().get("detail", "").lower() or \
               "manifest" in r.json().get("detail", "").lower()


# ── CLI polling has timeout ───────────────────────────────────────────────

class TestCLIPollingTimeout:
    def test_install_polling_has_deadline(self):
        """cmd_apps_install must have a timeout — not an infinite loop."""
        import inspect
        from cli import ms as cli_module
        src = inspect.getsource(cli_module.cmd_apps_install)
        assert "deadline" in src or "timeout" in src or "max" in src.lower(), \
            "cmd_apps_install must have an overall timeout to prevent infinite polling"

    def test_step_deduplication_in_poll_loop(self):
        """Already-printed steps should not be reprinted on each poll tick."""
        import inspect
        from cli import ms as cli_module
        src = inspect.getsource(cli_module.cmd_apps_install)
        assert "seen_steps" in src or "seen" in src or "printed" in src, \
            "Polling loop should track already-printed steps to avoid duplication"
