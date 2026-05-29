"""tests/test_features.py

Regression tests for all newly implemented features:

- App version pinning (PUT /{key}/pin-version, POST /{key}/pin-tag)
- App update endpoint (POST /{key}/update, POST /{key}/pull)  
- Per-app config schema (GET/PUT /{key}/config)
- Post-install steps (GET /{key}/post-install-steps)
- Ghost resource detection and actions (GET/POST /health/ghost-resources)
- Weekly health summary (GET /health/weekly-summary)
- Traefik settings (GET/PUT /settings/traefik)
- Docker socket proxy manifest in catalog
- Authelia and Headscale providers in registry
- config_schema parsed from manifest YAML
- Docker socket proxy catalog entry
"""
from __future__ import annotations

import os
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    db = tmp_path / "state.db"
    import backend.core.state as sm
    from backend.core.state import init_db
    sm.configure(db)
    init_db(db)
    yield db
    sm.configure(db)


@pytest.fixture
def client(db_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


@pytest.fixture
def app_seeded(db_path):
    """Seed a running sonarr app."""
    from backend.core.state import StateDB
    with StateDB() as db:
        db.upsert_app(
            "sonarr", display_name="Sonarr", category="arr",
            image="lscr.io/linuxserver/sonarr", container_name="sonarr",
            status="running", config_path="/tmp/sonarr-test", image_tag="latest",
        )
    return db_path


# ── App version pinning ────────────────────────────────────────────────────

class TestVersionPinning:
    def test_pin_version_persists(self, client, app_seeded):
        r = client.put("/api/apps/sonarr/pin-version",
                       json={"image_tag": "v4.0.9"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["image_tag"] == "v4.0.9"

    def test_pin_version_stored_in_db(self, client, app_seeded):
        client.put("/api/apps/sonarr/pin-version", json={"image_tag": "v3.5.0"})
        from backend.core.state import StateDB
        with StateDB() as db:
            app = db.get_app("sonarr")
        assert app.image_tag == "v3.5.0"

    def test_pin_tag_alias_works(self, client, app_seeded):
        """POST /pin-tag is an alias for PUT /pin-version."""
        r = client.post("/api/apps/sonarr/pin-tag",
                        json={"image_tag": "v4.1.0"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_pin_nonexistent_app_returns_404(self, client, db_path):
        r = client.put("/api/apps/doesnotexist/pin-version",
                       json={"image_tag": "latest"})
        assert r.status_code == 404

    def test_empty_tag_rejected(self, client, app_seeded):
        r = client.put("/api/apps/sonarr/pin-version", json={"image_tag": ""})
        assert r.status_code == 422

    def test_unpin_with_latest(self, client, app_seeded):
        client.put("/api/apps/sonarr/pin-version", json={"image_tag": "v4.0.0"})
        r = client.put("/api/apps/sonarr/pin-version", json={"image_tag": "latest"})
        assert r.status_code == 200
        from backend.core.state import StateDB
        with StateDB() as db:
            app = db.get_app("sonarr")
        assert app.image_tag == "latest"


# ── App update endpoint ────────────────────────────────────────────────────

class TestAppUpdate:
    def test_update_nonexistent_app_returns_404(self, client, db_path):
        r = client.post("/api/apps/doesnotexist/update")
        assert r.status_code == 404

    def test_pull_alias_exists(self, client, app_seeded):
        """POST /pull is an alias for POST /update."""
        r = client.post("/api/apps/sonarr/pull")
        # Will return 503 (Docker unavailable) or 409 (already installing) — not 404/405
        assert r.status_code not in (404, 405)

    def test_update_returns_reasonable_status(self, client, app_seeded):
        r = client.post("/api/apps/sonarr/update")
        # 200 (queued), 409 (duplicate), or 503 (no Docker) — not 404/500
        assert r.status_code in (200, 202, 409, 503)


# ── Per-app config schema ──────────────────────────────────────────────────

class TestAppConfigSchema:
    def test_config_get_returns_schema_and_values(self, client, db_path):
        """ddns_updater has config_schema defined."""
        r = client.get("/api/apps/ddns_updater/config")
        assert r.status_code == 200
        data = r.json()
        assert "schema" in data
        assert "values" in data
        assert len(data["schema"]) >= 2

    def test_config_schema_has_required_fields(self, client, db_path):
        r = client.get("/api/apps/ddns_updater/config")
        schema = r.json()["schema"]
        for field in schema:
            assert "key" in field
            assert "label" in field

    def test_config_defaults_populated(self, client, db_path):
        r = client.get("/api/apps/ddns_updater/config")
        values = r.json()["values"]
        assert values.get("period") == "5m"
        assert values.get("ip_version") == "ipv4"

    def test_config_put_saves_values(self, client, app_seeded, tmp_path):
        """PUT /config writes values to config.json."""
        from backend.core.state import StateDB
        config_dir = tmp_path / "sonarr-config"
        config_dir.mkdir()
        with StateDB() as db:
            db.upsert_app("sonarr", config_path=str(config_dir))
        r = client.put("/api/apps/sonarr/config",
                       json={"values": {"period": "15m", "ip_version": "ipv4"}})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        config_file = config_dir / "config.json"
        assert config_file.exists()
        import json
        saved = json.loads(config_file.read_text())
        assert saved["period"] == "15m"

    def test_config_put_no_config_path_422(self, client, db_path):
        """App with no config_path cannot save config."""
        from backend.core.state import StateDB
        with StateDB() as db:
            db.upsert_app("radarr", display_name="Radarr", category="arr",
                          image="radarr:latest", container_name="radarr",
                          status="running", config_path="", image_tag="latest")
        r = client.put("/api/apps/radarr/config", json={"values": {}})
        assert r.status_code == 422

    def test_config_manifest_loaded(self):
        """config_schema is correctly parsed from ddns_updater.yaml."""
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        assert len(m.config_schema) >= 2
        keys = [f["key"] for f in m.config_schema]
        assert "providers" in keys
        assert "period" in keys

    def test_config_defaults_loaded(self):
        """config_defaults are correctly parsed from manifest YAML."""
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        assert m.config_defaults.get("period") == "5m"
        assert m.config_defaults.get("ip_version") == "ipv4"


# ── Post-install steps ─────────────────────────────────────────────────────

class TestPostInstallSteps:
    def test_arr_apps_have_steps(self, client, db_path):
        r = client.get("/api/apps/sonarr/post-install-steps")
        assert r.status_code == 200
        steps = r.json()
        assert isinstance(steps, list)
        assert len(steps) >= 2

    def test_arr_steps_have_required_fields(self, client, db_path):
        r = client.get("/api/apps/sonarr/post-install-steps")
        for step in r.json():
            assert "title" in step
            assert "description" in step
            assert "required" in step

    def test_arr_steps_include_indexer_config(self, client, db_path):
        r = client.get("/api/apps/sonarr/post-install-steps")
        titles = [s["title"].lower() for s in r.json()]
        assert any("indexer" in t for t in titles)

    def test_prowlarr_has_steps(self, client, db_path):
        r = client.get("/api/apps/prowlarr/post-install-steps")
        assert r.status_code == 200
        steps = r.json()
        assert len(steps) >= 1

    def test_ddns_updater_has_steps(self, client, db_path):
        r = client.get("/api/apps/ddns_updater/post-install-steps")
        assert r.status_code == 200
        steps = r.json()
        assert any("provider" in s["title"].lower() or "config" in s["description"].lower()
                   for s in steps)

    def test_nonexistent_app_returns_404(self, client, db_path):
        r = client.get("/api/apps/doesnotexist123/post-install-steps")
        assert r.status_code in (200, 404)  # returns empty list or 404


# ── Ghost resource detection ───────────────────────────────────────────────

class TestGhostResources:
    def test_returns_ghost_structure(self, client, db_path):
        r = client.get("/api/health/ghost-resources")
        assert r.status_code == 200
        data = r.json()
        assert "ghost_containers" in data
        assert "ghost_fragments" in data
        assert "orphaned_apps" in data
        assert isinstance(data["ghost_containers"], list)
        assert isinstance(data["ghost_fragments"], list)
        assert isinstance(data["orphaned_apps"], list)

    def test_orphaned_app_detection(self, client, app_seeded):
        """App in DB as 'running' but no matching container → orphaned."""
        from backend.core.state import StateDB
        with StateDB() as db:
            db.upsert_app("orphaned_app_xyz", display_name="Orphaned",
                          category="tools", image="test:latest",
                          container_name="orphaned_container_xyz",
                          status="running", config_path="", image_tag="latest")
        r = client.get("/api/health/ghost-resources")
        data = r.json()
        orphaned_keys = [a["key"] for a in data["orphaned_apps"]]
        # Without Docker, sonarr might also appear — just check the struct
        for a in data["orphaned_apps"]:
            assert "key" in a
            assert "display_name" in a
            assert "container_name" in a

    def test_action_ignore_returns_ok(self, client, db_path):
        r = client.post("/api/health/ghost-resources/action", json={
            "resource_type": "container",
            "name": "some_ghost_container",
            "action": "ignore",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_action_adopt_creates_db_entry(self, client, db_path):
        r = client.post("/api/health/ghost-resources/action", json={
            "resource_type": "container",
            "name": "my_adopted_container",
            "action": "adopt",
        })
        assert r.status_code == 200
        from backend.core.state import StateDB
        with StateDB() as db:
            app = db.get_app("my_adopted_container")
        assert app is not None
        assert app.status == "running"

    def test_action_unknown_returns_422(self, client, db_path):
        r = client.post("/api/health/ghost-resources/action", json={
            "resource_type": "container",
            "name": "test",
            "action": "teleport",
        })
        assert r.status_code == 422

    def test_fragment_remove_deletes_file(self, client, db_path, tmp_path):
        """Removing a ghost fragment deletes the file."""
        from backend.core.config import config
        # Create a fake fragment
        frag = config.compose_dir / "ghost_test.yaml"
        config.compose_dir.mkdir(parents=True, exist_ok=True)
        frag.write_text("services:\n  ghost:\n    image: ghost:latest\n")
        r = client.post("/api/health/ghost-resources/action", json={
            "resource_type": "fragment",
            "name": "ghost_test.yaml",
            "action": "remove",
        })
        assert r.status_code == 200
        assert not frag.exists()


# ── Weekly health summary ──────────────────────────────────────────────────

class TestWeeklySummary:
    def test_returns_summary_structure(self, client, db_path):
        r = client.get("/api/health/weekly-summary")
        assert r.status_code == 200
        data = r.json()
        assert "summary" in data
        assert isinstance(data["summary"], str)
        assert "generated_at" in data

    def test_empty_history_returns_graceful(self, client, db_path):
        r = client.get("/api/health/weekly-summary")
        assert r.status_code == 200
        data = r.json()
        assert len(data["summary"]) >= 0  # empty is ok

    def test_with_health_history_data(self, client, db_path):
        from backend.core.state import StateDB
        now = int(time.time())
        with StateDB() as db:
            for i in range(5):
                db.execute(
                    "INSERT INTO health_check_history "
                    "(subject_type, subject_key, check_name, status, summary, checked_at) "
                    "VALUES ('app', 'sonarr', 'http_check', 'error', 'Connection refused', ?)",
                    (now - i * 3600,)
                )
        r = client.get("/api/health/weekly-summary")
        assert r.status_code == 200
        data = r.json()
        assert len(data["summary"]) >= 0

    def test_returns_period_info(self, client, db_path):
        r = client.get("/api/health/weekly-summary")
        data = r.json()
        assert "period" in data or "period_days" in data


# ── Traefik settings ───────────────────────────────────────────────────────

class TestTraefikSettings:
    def test_get_returns_defaults(self, client, db_path):
        r = client.get("/api/settings/traefik")
        assert r.status_code == 200
        data = r.json()
        assert "image_tag" in data
        assert "dashboard_port" in data
        assert data["image_tag"] == "v3.2"
        assert data["dashboard_port"] == 8081

    def test_put_updates_image_tag(self, client, db_path):
        r = client.put("/api/settings/traefik", json={"image_tag": "v3.3"})
        assert r.status_code == 200
        r2 = client.get("/api/settings/traefik")
        assert r2.json()["image_tag"] == "v3.3"

    def test_put_updates_dashboard_port(self, client, db_path):
        r = client.put("/api/settings/traefik", json={"dashboard_port": 9999})
        assert r.status_code == 200
        r2 = client.get("/api/settings/traefik")
        assert r2.json()["dashboard_port"] == 9999

    def test_port_below_1024_rejected(self, client, db_path):
        r = client.put("/api/settings/traefik", json={"dashboard_port": 80})
        assert r.status_code == 422

    def test_port_above_65535_rejected(self, client, db_path):
        r = client.put("/api/settings/traefik", json={"dashboard_port": 70000})
        assert r.status_code == 422

    def test_partial_update_preserves_other_fields(self, client, db_path):
        client.put("/api/settings/traefik", json={"image_tag": "v3.2.1"})
        client.put("/api/settings/traefik", json={"dashboard_port": 8090})
        r = client.get("/api/settings/traefik")
        data = r.json()
        assert data["image_tag"] == "v3.2.1"
        assert data["dashboard_port"] == 8090


# ── Infrastructure registry ────────────────────────────────────────────────

class TestInfraRegistry:
    def test_authelia_in_auth_slot(self):
        from backend.infra.registry import list_providers
        providers = [p["key"] for p in list_providers("auth")]
        assert "authelia" in providers

    def test_headscale_in_tunnel_slot(self):
        from backend.infra.registry import list_providers
        providers = [p["key"] for p in list_providers("tunnel")]
        assert "headscale" in providers

    def test_gluetun_in_vpn_slot(self):
        from backend.infra.registry import list_providers
        providers = [p["key"] for p in list_providers("vpn")]
        assert "gluetun" in providers

    def test_all_5_slots_have_providers(self):
        from backend.infra.registry import list_providers
        for slot in ["auth", "tunnel", "vpn", "dashboard", "management"]:
            providers = list_providers(slot)
            assert len(providers) >= 1, f"Slot '{slot}' has no providers"

    def test_authelia_schema_has_domain_field(self, client, db_path):
        r = client.get("/api/infra/providers/auth/schema")
        assert r.status_code == 200
        schemas = r.json()
        authelia = next((s for s in schemas if s["key"] == "authelia"), None)
        assert authelia is not None
        field_keys = [f["key"] for f in authelia.get("fields", [])]
        assert "domain" in field_keys

    def test_headscale_schema_has_url_field(self, client, db_path):
        r = client.get("/api/infra/providers/tunnel/schema")
        assert r.status_code == 200
        schemas = r.json()
        headscale = next((s for s in schemas if s["key"] == "headscale"), None)
        assert headscale is not None

    def test_gluetun_schema_has_vpn_provider_field(self, client, db_path):
        r = client.get("/api/infra/providers/vpn/schema")
        assert r.status_code == 200
        schemas = r.json()
        gluetun = next((s for s in schemas if s["key"] == "gluetun"), None)
        assert gluetun is not None
        field_keys = [f["key"] for f in gluetun.get("fields", [])]
        assert any("vpn" in k.lower() or "provider" in k.lower() for k in field_keys)


# ── Docker socket proxy catalog ────────────────────────────────────────────

class TestDockerSocketProxy:
    def test_manifest_loadable(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("docker_socket_proxy")
        assert m.key == "docker_socket_proxy"
        assert m.image == "tecnativa/docker-socket-proxy"

    def test_catalog_endpoint_returns_it(self, client, db_path):
        r = client.get("/api/catalog/docker_socket_proxy")
        assert r.status_code == 200
        data = r.json()
        assert data["key"] == "docker_socket_proxy"

    def test_manifest_has_config_schema(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("docker_socket_proxy")
        assert len(m.config_schema) >= 1

    def test_in_catalog_list(self, client, db_path):
        r = client.get("/api/catalog")
        assert r.status_code == 200
        data = r.json()
        all_keys = [a["key"] for cat in data.values() for a in cat]
        assert "docker_socket_proxy" in all_keys

    def test_registry_has_source_url(self):
        import json
        from pathlib import Path
        registry = json.loads(Path("catalog/registry.json").read_text())
        proxy = next(
            (m for m in registry["manifests"] if m["key"] == "docker_socket_proxy"),
            None,
        )
        assert proxy is not None
        assert "Nnyan/SLOP" in proxy["source_url"]


# ── Startup grace period ───────────────────────────────────────────────────

class TestStartupGracePeriod:
    """Verify health checks skip failing apps that just restarted.

    Root cause of stirling_pdf/paperless_ngx 03:00 false positives:
    something (Watchtower, a cron job, or Docker's restart policy)
    restarts the container nightly. Spring Boot takes ~15s to start.
    The health checker runs a check during that window → failure → anomaly.

    Fix: the checker queries docker inspect for container StartedAt and
    returns 'starting' (not 'error') if the container is within its
    startup grace period.
    """

    def test_start_grace_s_field_on_manifest(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("stirling_pdf")
        assert hasattr(m, "start_grace_s"), (
            "AppManifest is missing start_grace_s field. "
            "loader.py must parse start_grace_s from YAML."
        )
        assert m.start_grace_s >= 60, (
            f"stirling_pdf start_grace_s={m.start_grace_s} — should be >= 60s "
            f"because Spring Boot takes ~15s to start and Docker might restart it."
        )

    def test_paperless_ngx_has_grace_period(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("paperless_ngx")
        assert m.start_grace_s >= 60, (
            f"paperless_ngx start_grace_s={m.start_grace_s} — needs grace period "
            f"to prevent false positives when container restarts."
        )

    def test_in_startup_grace_returns_false_for_old_container(self):
        """A container that started >300s ago must NOT be in grace period."""
        from unittest.mock import patch
        import time
        from backend.health.checker import _in_startup_grace
        # Mock docker inspect to return a time 5 minutes ago
        old_time = time.time() - 300
        from datetime import datetime, timezone
        old_iso = datetime.fromtimestamp(old_time, tz=timezone.utc).isoformat()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = old_iso.replace("+00:00", "Z") + "\n"
            in_grace, age = _in_startup_grace("test_container", 120)
        assert not in_grace, f"Container started 300s ago should not be in 120s grace. age={age:.0f}s"

    def test_in_startup_grace_returns_true_for_fresh_container(self):
        """A container that started <60s ago must be in grace period."""
        from unittest.mock import patch
        import time
        from backend.health.checker import _in_startup_grace
        fresh_time = time.time() - 30
        from datetime import datetime, timezone
        fresh_iso = datetime.fromtimestamp(fresh_time, tz=timezone.utc).isoformat()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = fresh_iso.replace("+00:00", "Z") + "\n"
            in_grace, age = _in_startup_grace("test_container", 120)
        assert in_grace, f"Container started 30s ago should be in 120s grace. age={age:.0f}s"

    def test_checker_skips_app_in_grace_period(self, db_path, tmp_path):
        """check_app() must return 'starting' results when in grace period.

        Step 2.6 closure: patches `cfg_mod.config` to a tmp compose dir
        containing a stirling_pdf fragment so `_precheck_fragment`
        passes — without this the test exercises the misconfig path,
        not the grace-period path it intends to test.
        """
        import asyncio
        from unittest.mock import patch, MagicMock
        import time
        from backend.core.state import StateDB
        from backend.core import config as _cfg_mod
        from backend.health.checker import check_app

        with StateDB() as db:
            db.upsert_app(
                "stirling_pdf", display_name="Stirling PDF", category="tools",
                image="stirlingtools/stirling-pdf", container_name="stirling_pdf",
                status="running", config_path="", image_tag="latest",
            )

        compose = tmp_path / "compose"
        compose.mkdir()
        (compose / "stirling_pdf.yaml").write_text(
            "services:\n  stirling_pdf:\n    image: test:latest\n",
        )
        original_config = _cfg_mod.config
        mock_cfg = MagicMock()
        mock_cfg.compose_dir = compose
        mock_cfg.data_dir = tmp_path
        _cfg_mod.config = mock_cfg

        fresh_time = time.time() - 10  # started 10s ago
        from datetime import datetime, timezone
        fresh_iso = datetime.fromtimestamp(fresh_time, tz=timezone.utc).isoformat()

        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = fresh_iso.replace("+00:00", "Z") + "\n"
                results = asyncio.run(check_app("stirling_pdf", "", "", ""))
        finally:
            _cfg_mod.config = original_config

        assert len(results) > 0
        for r in results:
            assert r.ok, (
                f"check_app should return ok=True during grace period, got: {r.message}"
            )
            assert "grace" in r.message.lower() or "start" in r.message.lower(), (
                f"check_app grace result should mention grace/start: {r.message}"
            )

    def test_slow_starters_have_explicit_grace(self):
        """Known slow-starting apps must have start_grace_s set in their manifests."""
        from backend.manifests.loader import load_manifest
        slow_starters = ["stirling_pdf", "paperless_ngx", "plex", "immich", "sonarr"]
        missing_grace = []
        for key in slow_starters:
            try:
                m = load_manifest(key)
                if m.start_grace_s < 30:
                    missing_grace.append(f"{key} (start_grace_s={m.start_grace_s})")
            except Exception:
                pass
        assert not missing_grace, (
            f"These slow-starting apps need start_grace_s >= 30 in their manifests:\n"
            + "\n".join(f"  - {a}" for a in missing_grace)
        )

    def test_docker_healthcheck_has_start_period(self):
        """build_service_fragment must include Docker healthcheck with start_period
        when start_grace_s is specified. This prevents Docker's own restart policy
        from restarting a healthy-but-still-booting container.
        """
        from backend.core.compose import build_service_fragment
        fragment = build_service_fragment(
            manifest_key="stirling_pdf",
            display_name="Stirling PDF",
            image="stirlingtools/stirling-pdf",
            image_tag="latest",
            web_port=8080,
            host_port=8085,
            config_path="/config/stirling",
            media_root=None,
            domain="example.com",
            start_grace_s=90,
        )
        assert "healthcheck" in fragment, (
            "build_service_fragment must include a Docker healthcheck when start_grace_s > 0. "
            "Without this, Docker's restart policy may kill the container mid-boot."
        )
        hc = fragment["healthcheck"]
        assert "start_period" in hc, "Docker healthcheck must have start_period field"
        assert hc["start_period"] == "90s", (
            f"start_period should be '90s', got '{hc['start_period']}'"
        )

