"""tests/test_platform.py

Tests for the platform wizard, compose builder, and API routes.
"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.core import state as state_mod
from backend.core.compose import (
    build_service_fragment,
    build_traefik_fragment,
    build_traefik_yaml,
    merge_fragments,
    write_fragment,
)
from backend.core.state import StateDB, init_db
from backend.platform.wizard import (
    WizardInput,
    step_complete,
    step_config_dirs,
    step_network,
    step_preflight,
    step_traefik_config,
    step_traefik_healthy,
    validate_wizard,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "state.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def wizard_input(tmp_path: Path) -> WizardInput:
    return WizardInput(
        domain="example.com",
        config_root=str(tmp_path / "config"),
        media_root=str(tmp_path / "media"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        cert_resolver="letsencrypt",
        network_name="mediastack",
    )


@pytest.fixture
def api_client(db: Path):
    from backend.api.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        state_mod.configure(db)
        yield c


# ── Compose fragment builder ──────────────────────────────────────────────


class TestComposeFragments:
    def test_traefik_fragment_structure(self):
        frag = build_traefik_fragment("example.com", config_root="/config")
        assert "traefik:v3.2" in frag["image"]
        assert frag["restart"] == "unless-stopped"
        assert any("80:80" in p for p in frag["ports"])
        assert any("443:443" in p for p in frag["ports"])
        assert any("/var/run/docker.sock" in v for v in frag["volumes"])

    def test_traefik_fragment_labels_include_domain(self):
        frag = build_traefik_fragment("nyrdalyrt.com", config_root="/config")
        labels = frag["labels"]
        assert any("traefik.nyrdalyrt.com" in lbl for lbl in labels)

    def test_traefik_yaml_contains_domain(self):
        yml = build_traefik_yaml("example.com")
        assert "example.com" in yml
        assert "cloudflare" in yml
        assert "letsencrypt" in yml
        assert ":443" in yml

    def test_service_fragment_linuxserver(self):
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
            puid=1000,
            pgid=1000,
            timezone="UTC",
            linuxserver=True,
        )
        assert frag["image"] == "lscr.io/linuxserver/sonarr:latest"
        assert frag["environment"]["PUID"] == "1000"
        assert frag["environment"]["TZ"] == "UTC"
        assert "8989:8989" in frag["ports"]
        assert any("sonarr" in v for v in frag["volumes"])

    def test_service_fragment_no_linuxserver(self):
        frag = build_service_fragment(
            manifest_key="ollama",
            display_name="Ollama",
            image="ollama/ollama",
            image_tag="latest",
            web_port=11434,
            host_port=11434,
            config_path="/config/ollama",
            media_root=None,
            domain="example.com",
            linuxserver=False,
        )
        env = frag.get("environment", {})
        assert "PUID" not in env
        assert "PGID" not in env

    def test_service_fragment_traefik_labels_two_router(self):
        frag = build_service_fragment(
            manifest_key="sonarr",
            display_name="Sonarr",
            image="img",
            image_tag="latest",
            web_port=8989,
            host_port=8989,
            config_path="/c",
            media_root=None,
            domain="example.com",
            tinyauth_enabled=True,
            lan_subnet="10.0.0.0/22",
        )
        labels = frag.get("labels", [])
        # Should have both -lan router and catch-all router
        assert any("-lan" in lbl for lbl in labels)
        assert any("tinyauth-auth@docker" in lbl for lbl in labels)

    def test_service_fragment_no_media(self):
        frag = build_service_fragment(
            manifest_key="bazarr",
            display_name="Bazarr",
            image="img",
            image_tag="latest",
            web_port=6767,
            host_port=6767,
            config_path="/config/bazarr",
            media_root=None,
            domain="example.com",
        )
        assert all("/data" not in v for v in frag.get("volumes", []))

    def test_merge_fragments(self, tmp_path: Path):
        from backend.core import config as cfg_mod
        import backend.core.compose as compose_mod
        # Patch compose_dir to use tmp_path
        original = compose_mod.config
        mock_cfg = MagicMock()
        mock_cfg.compose_dir = tmp_path
        compose_mod.config = mock_cfg

        write_fragment("sonarr", {
            "image": "sonarr:latest",
            "container_name": "sonarr",
        })
        write_fragment("radarr", {
            "image": "radarr:latest",
            "container_name": "radarr",
        })
        merged = merge_fragments()

        compose_mod.config = original

        assert "sonarr" in merged
        assert "radarr" in merged
        assert "services:" in merged


# ── Wizard steps (unit) ───────────────────────────────────────────────────


class TestWizardSteps:
    def test_preflight_fails_no_docker(self, wizard_input: WizardInput):
        from backend.core.docker_client import DockerError
        with patch(
            "backend.platform.wizard.docker_client.daemon_info",
            side_effect=DockerError("No socket"),
        ):
            result = step_preflight(wizard_input)
        assert result.status == "error"
        assert "Docker" in result.message

    def test_preflight_fails_port_conflict(self, wizard_input: WizardInput):
        with patch("backend.platform.wizard.docker_client.daemon_info", return_value={}):
            with patch(
                "backend.platform.wizard.docker_client.ports_in_use",
                return_value={80: "nginx", 443: "nginx"},
            ):
                result = step_preflight(wizard_input)
        assert result.status == "error"
        assert "80" in result.message or "443" in result.message

    def test_preflight_passes(self, wizard_input: WizardInput):
        with patch("backend.platform.wizard.docker_client.daemon_info", return_value={}):
            with patch("backend.platform.wizard.docker_client.ports_in_use", return_value={}):
                result = step_preflight(wizard_input)
        assert result.status == "ok"

    def test_network_creates_new(self, wizard_input: WizardInput):
        with patch(
            "backend.platform.wizard.docker_client.get_network", return_value=None
        ):
            with patch(
                "backend.platform.wizard.docker_client.create_network",
                return_value=MagicMock(name="mediastack"),
            ):
                result = step_network(wizard_input)
        assert result.status == "ok"
        assert "Created" in result.message

    def test_network_skips_existing(self, wizard_input: WizardInput):
        mock_net = MagicMock()
        mock_net.name = "mediastack"
        with patch(
            "backend.platform.wizard.docker_client.get_network", return_value=mock_net
        ):
            result = step_network(wizard_input)
        assert result.status == "skipped"

    def test_config_dirs_creates_acme(self, wizard_input: WizardInput):
        result = step_config_dirs(wizard_input)
        assert result.status == "ok"
        acme = Path(wizard_input.config_root) / "traefik" / "acme.json"
        assert acme.exists()
        # acme.json must be 600
        assert oct(acme.stat().st_mode)[-3:] == "600"

    def test_traefik_config_written(self, wizard_input: WizardInput):
        # config_dirs must run first to create the directory
        step_config_dirs(wizard_input)
        result = step_traefik_config(wizard_input)
        assert result.status == "ok"
        traefik_yml = Path(wizard_input.config_root) / "traefik" / "traefik.yml"
        assert traefik_yml.exists()
        content = traefik_yml.read_text()
        assert "example.com" in content
        assert "cloudflare" in content

    def test_traefik_healthy_skips_when_running(self, wizard_input: WizardInput):
        mock_c = MagicMock()
        mock_c.status = "running"
        mock_c.health = "healthy"
        with patch(
            "backend.platform.wizard.docker_client.get_container", return_value=mock_c
        ):
            result = step_traefik_healthy(wizard_input, timeout=1)
        assert result.status == "ok"

    def test_traefik_healthy_times_out(self, wizard_input: WizardInput):
        with patch("backend.platform.wizard.docker_client.get_container", return_value=None):
            result = step_traefik_healthy(wizard_input, timeout=1)
        assert result.status == "error"
        assert "healthy" in result.message.lower() or "timeout" in result.message.lower() \
               or "seconds" in result.message.lower()

    def test_step_complete_updates_db(self, wizard_input: WizardInput, db: Path):
        result = step_complete(wizard_input)
        assert result.status == "ok"
        with StateDB() as s:
            p = s.get_platform()
        assert p.status == "ready"
        assert p.domain == "example.com"


# ── Wizard validation ─────────────────────────────────────────────────────


class TestWizardValidation:
    def test_valid_input_no_issues(self, wizard_input: WizardInput):
        issues = validate_wizard(wizard_input)
        assert issues == []

    def test_missing_domain(self, wizard_input: WizardInput):
        wizard_input.domain = ""
        issues = validate_wizard(wizard_input)
        assert any(i["field"] == "domain" for i in issues)

    def test_domain_without_dot(self, wizard_input: WizardInput):
        wizard_input.domain = "nodot"
        issues = validate_wizard(wizard_input)
        assert any(i["field"] == "domain" for i in issues)

    def test_relative_config_root(self, wizard_input: WizardInput):
        wizard_input.config_root = "relative/path"
        issues = validate_wizard(wizard_input)
        assert any(i["field"] == "config_root" for i in issues)

    def test_relative_media_root(self, wizard_input: WizardInput):
        wizard_input.media_root = "not/absolute"
        issues = validate_wizard(wizard_input)
        assert any(i["field"] == "media_root" for i in issues)


# ── API routes ────────────────────────────────────────────────────────────


class TestPlatformAPI:
    def test_health_endpoint(self, api_client: TestClient):
        r = api_client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_platform_status_default(self, api_client: TestClient):
        r = api_client.get("/api/platform/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert data["domain"] is None

    def test_wizard_steps(self, api_client: TestClient):
        r = api_client.get("/api/platform/wizard/steps")
        assert r.status_code == 200
        steps = r.json()
        names = [s["name"] for s in steps]
        assert "preflight" in names
        assert "traefik_deploy" in names
        assert "complete" in names
        assert len(steps) == 7

    def test_wizard_validate_valid(self, api_client: TestClient):
        r = api_client.post("/api/platform/wizard/validate", json={
            "domain": "example.com",
            "config_root": "/srv/mediastack/config",
            "media_root": "/mnt/media",
            "puid": 1000,
            "pgid": 1000,
            "timezone": "UTC",
        })
        assert r.status_code == 200
        assert r.json()["valid"] is True

    def test_wizard_validate_bad_domain(self, api_client: TestClient):
        r = api_client.post("/api/platform/wizard/validate", json={
            "domain": "nodot",
            "config_root": "/config",
            "media_root": "/media",
            "puid": 1000,
            "pgid": 1000,
            "timezone": "UTC",
        })
        # Pydantic catches the dot check and returns 422
        assert r.status_code == 422

    def test_wizard_run_blocked_when_ready(self, api_client: TestClient, db: Path):
        # Manually mark platform as ready
        with StateDB() as s:
            s.update_platform(status="ready")
        r = api_client.post("/api/platform/wizard/run", json={
            "domain": "example.com",
            "config_root": "/config",
            "media_root": "/media",
            "puid": 1000,
            "pgid": 1000,
            "timezone": "UTC",
        })
        assert r.status_code == 409

    def test_platform_reset(self, api_client: TestClient, db: Path):
        with StateDB() as s:
            s.update_platform(status="ready")
        r = api_client.post("/api/platform/reset")
        assert r.status_code == 200
        r2 = api_client.get("/api/platform/status")
        assert r2.json()["status"] == "pending"

    def test_catalog_endpoint(self, api_client: TestClient):
        r = api_client.get("/api/catalog")
        assert r.status_code == 200
        data = r.json()
        # Should have at least our 6 example manifests grouped by category
        all_keys = [e["key"] for entries in data.values() for e in entries]
        assert "sonarr" in all_keys
        assert "ollama" in all_keys

    def test_catalog_detail(self, api_client: TestClient):
        r = api_client.get("/api/catalog/sonarr")
        assert r.status_code == 200
        data = r.json()
        assert data["key"] == "sonarr"
        assert data["web_port"] == 8989
        assert len(data["wiring"]) >= 2

    def test_catalog_unknown_key(self, api_client: TestClient):
        r = api_client.get("/api/catalog/doesnotexist")
        assert r.status_code == 404
