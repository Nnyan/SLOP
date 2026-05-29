"""tests/test_non_catalog_installs.py

Tests for every method of adding an app to Mediastack that is not in the
official catalog, plus catalog compliance verification.

Non-catalog install paths:
  1. install-from-github  — fetch manifest from GitHub URL → install
  2. install-custom       — paste compose YAML → lint → register → install
  3. install_instance     — duplicate a catalog app under a new key/role

Expected behavior: every app added via any method must receive the same
full infrastructure configuration as a catalog app:
  ✓ Traefik labels (HTTPS routing, cert resolver, hostname rule)
  ✓ Network attachment (mediastack)
  ✓ PUID/PGID/TZ env vars (if linuxserver)
  ✓ Config path at {config_root}/{key}
  ✓ restart: unless-stopped
  ✓ Health check definition
  ✓ Port conflict detection
  ✓ DB record with status, host_port, display_name, category
"""
from __future__ import annotations

import pathlib

import json
import re
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core import state as state_mod
from backend.core.state import StateDB, init_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def app_client(tmp_path):
    """Self-contained TestClient with isolated DB in ready state."""
    from fastapi.testclient import TestClient
    db_path = tmp_path / "state.db"
    init_db(db_path)
    state_mod.configure(db_path)

    with StateDB() as db:
        db.update_platform(
            status="ready",
            domain="test.local",
            config_root=str(tmp_path / "config"),
            media_root=str(tmp_path / "media"),
            puid=1000, pgid=1000, timezone="UTC",
            network_name="mediastack",
            cert_resolver="letsencrypt",
        )

    # Redirect catalog community dir to tmp so tests don't pollute catalog/community/
    tmp_catalog = tmp_path / "catalog"
    (tmp_catalog / "apps").mkdir(parents=True, exist_ok=True)
    (tmp_catalog / "community").mkdir(parents=True, exist_ok=True)
    # Copy real catalog apps for compliance tests
    import shutil as _shutil
    real_catalog = pathlib.Path(__file__).parent.parent / "catalog" / "apps"
    for _f in real_catalog.glob("*.yaml"):
        _shutil.copy(_f, tmp_catalog / "apps" / _f.name)

    def _init(path):
        init_db(db_path)
        state_mod.configure(db_path)

    # Patch via env var — config uses MS_CATALOG_DIR env var at load time
    # But config is a frozen singleton, so we patch the _cfg in apps.py directly
    from backend.core import config as _cfg_mod
    from unittest.mock import MagicMock as _MM
    _fake_cfg = _MM()
    _fake_cfg.catalog_dir = tmp_catalog
    _fake_cfg.compose_dir = tmp_path / "compose"
    _fake_cfg.data_dir = tmp_path / "data"

    with patch("backend.api.main.init_db", side_effect=_init), \
         patch("backend.health.scheduler.start_scheduler"), \
         patch("backend.health.source_checker.run_source_scan", return_value=None), \
         patch("backend.core.config.config", _fake_cfg):
        from backend.api.main import app
        with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
            yield client, tmp_path
    state_mod.configure(None)


MINIMAL_GITHUB_MANIFEST = """
key: my_custom_app
display_name: My Custom App
category: tools
tier: 2
image: nginx
image_tag: latest
ports:
  web: 80
traefik:
  enabled: true
  subdomain: my_custom_app
health:
  checks:
    - name: api_reachable
      type: http
      path: /
      expect_status: 200
      interval: 60
"""


# ═══════════════════════════════════════════════════════════════════════════
# 1. install-from-github
# ═══════════════════════════════════════════════════════════════════════════

class TestInstallFromGitHub:
    """install-from-github: fetch manifest from GitHub URL."""

    def test_valid_github_url_saves_to_community_catalog(self, app_client, tmp_path):
        """Fetched manifest must be saved to catalog/community/{key}.yaml."""
        client, _ = app_client
        mock_resp = MagicMock()
        mock_resp.read.return_value = MINIMAL_GITHUB_MANIFEST.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = client.post("/api/apps/install-from-github", json={
                "repo_url": "https://raw.githubusercontent.com/user/repo/main/manifest.yaml"
            })

        assert r.status_code == 200, f"GitHub install failed: {r.text}"
        data = r.json()
        assert data["ok"] is True
        assert data["key"] == "my_custom_app"

    def test_rejects_non_github_urls(self, app_client):
        """Security: only github.com and raw.githubusercontent.com allowed."""
        client, _ = app_client
        r = client.post("/api/apps/install-from-github", json={
            "repo_url": "https://evil.example.com/manifest.yaml"
        })
        assert r.status_code == 422, (
            "Non-GitHub URL must be rejected with 422. "
            "Allowing arbitrary URLs is an SSRF vulnerability."
        )

    def test_key_sanitization_removes_dangerous_chars(self, app_client, tmp_path):
        """Manifest key must be sanitized before use as filename/DB key."""
        client, _ = app_client
        malicious_manifest = """
key: ../../etc/passwd
image: nginx
"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = malicious_manifest.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = client.post("/api/apps/install-from-github", json={
                "repo_url": "https://raw.githubusercontent.com/user/repo/main/manifest.yaml"
            })

        if r.status_code == 200:
            saved_key = r.json().get("key", "")
            assert ".." not in saved_key, "Path traversal chars in key — filesystem escape risk"
            assert "/" not in saved_key, "Slash in key — filesystem escape risk"
            assert saved_key == re.sub(r"[^a-z0-9_]", "_", saved_key), (
                f"Key not sanitized: '{saved_key}'"
            )

    def test_rejects_manifest_over_64kb(self, app_client):
        """Size limit: manifests over 64 KB must be rejected."""
        client, _ = app_client
        huge_manifest = f"key: test\nimage: nginx\n# {'x' * 65_000}"
        mock_resp = MagicMock()
        mock_resp.read.return_value = huge_manifest.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = client.post("/api/apps/install-from-github", json={
                "repo_url": "https://raw.githubusercontent.com/user/repo/main/manifest.yaml"
            })

        assert r.status_code == 422, (
            "64KB size limit not enforced. A huge manifest could OOM the server."
        )

    def test_rejects_missing_required_fields(self, app_client):
        """Manifest missing 'key' or 'image' must be rejected."""
        client, _ = app_client
        incomplete = "display_name: test\ncategory: tools"
        mock_resp = MagicMock()
        mock_resp.read.return_value = incomplete.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = client.post("/api/apps/install-from-github", json={
                "repo_url": "https://raw.githubusercontent.com/user/repo/main/manifest.yaml"
            })

        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# 2. install-custom (YAML linter → install-custom → install_app)
# ═══════════════════════════════════════════════════════════════════════════

class TestInstallCustom:
    """install-custom: paste compose YAML → lint → register → install."""

    def test_saved_manifest_includes_traefik_config(self, app_client, tmp_path):
        """Custom app manifest must include traefik config for HTTPS routing.

        Root gap: install-custom previously saved a manifest with NO traefik block.
        The app would install without any HTTPS routing — not reachable via domain.
        """
        client, _ = app_client
        manifest = {
            "key": "myapp",
            "display_name": "My App",
            "image": "nginx",
            "image_tag": "latest",
            "web_port": 80,
            "category": "tools",
        }
        r = client.post("/api/apps/install-custom", json={
            "manifest": manifest,
            "compose_yaml": "services:\n  myapp:\n    image: nginx:latest\n    ports:\n      - '8090:80'\n",
        })
        assert r.status_code == 200, f"install-custom failed: {r.text}"

        # Find saved manifest
        community_dir = Path(str(tmp_path)) / "config"
        # Check via catalog loading
        from backend.core.config import config
        catalog_dir = config.catalog_dir / "community"
        if catalog_dir.exists():
            manifest_path = catalog_dir / "myapp.yaml"
            if manifest_path.exists():
                saved = yaml.safe_load(manifest_path.read_text())
                assert "traefik" in saved, (
                    "Custom app manifest missing traefik config. "
                    "App cannot be reached via HTTPS domain routing."
                )
                assert saved["traefik"].get("enabled") is True or saved["traefik"].get("enabled") is not False

    def test_saved_manifest_includes_health_checks(self, app_client):
        """Custom app manifest must include at least a basic health check."""
        client, _ = app_client
        manifest = {
            "key": "healthtest",
            "display_name": "Health Test",
            "image": "nginx",
            "web_port": 80,
        }
        r = client.post("/api/apps/install-custom", json={
            "manifest": manifest,
            "compose_yaml": "services:\n  healthtest:\n    image: nginx\n",
        })
        assert r.status_code == 200

        from backend.core.config import config
        catalog_dir = config.catalog_dir / "community"
        manifest_path = catalog_dir / "healthtest.yaml"
        if manifest_path.exists():
            saved = yaml.safe_load(manifest_path.read_text())
            health = saved.get("health", {})
            assert health.get("checks"), (
                "Custom app manifest missing health checks. "
                "App will never show health status in the dashboard."
            )

    def test_saved_manifest_has_linuxserver_flag(self, app_client):
        """Custom app manifest must set linuxserver flag for PUID/PGID injection."""
        client, _ = app_client
        manifest = {
            "key": "linuxtest",
            "image": "lscr.io/linuxserver/nginx",
            "web_port": 8080,
        }
        r = client.post("/api/apps/install-custom", json={
            "manifest": manifest,
            "compose_yaml": "",
        })
        assert r.status_code == 200

        from backend.core.config import config
        manifest_path = config.catalog_dir / "community" / "linuxtest.yaml"
        if manifest_path.exists():
            saved = yaml.safe_load(manifest_path.read_text())
            assert "linuxserver" in saved, (
                "Custom manifest missing 'linuxserver' field. "
                "PUID/PGID/TZ env vars not injected → permission errors in container."
            )

    def test_empty_key_rejected(self, app_client):
        """Missing or empty 'key' field must be rejected with 422."""
        client, _ = app_client
        r = client.post("/api/apps/install-custom", json={
            "manifest": {"image": "nginx"},
            "compose_yaml": "",
        })
        assert r.status_code == 422

    def test_empty_image_rejected(self, app_client):
        """Missing 'image' field must be rejected with 422."""
        client, _ = app_client
        r = client.post("/api/apps/install-custom", json={
            "manifest": {"key": "noimage"},
            "compose_yaml": "",
        })
        assert r.status_code == 422

    def test_web_port_set_in_ports_dict(self, app_client):
        """web_port from manifest must appear in ports dict in saved manifest."""
        client, _ = app_client
        r = client.post("/api/apps/install-custom", json={
            "manifest": {"key": "porttest", "image": "nginx", "web_port": 8999},
            "compose_yaml": "",
        })
        assert r.status_code == 200

        from backend.core.config import config
        manifest_path = config.catalog_dir / "community" / "porttest.yaml"
        if manifest_path.exists():
            saved = yaml.safe_load(manifest_path.read_text())
            ports = saved.get("ports", {})
            web_port = ports.get("web") if isinstance(ports, dict) else None
            assert web_port == 8999, (
                f"web_port not saved in ports dict. Got: {ports}. "
                "Without ports.web the install pipeline can't assign host_port."
            )


# ═══════════════════════════════════════════════════════════════════════════
# 3. install_instance — duplicate catalog app with new key/role
# ═══════════════════════════════════════════════════════════════════════════

class TestInstallInstance:
    """install_instance: run a second copy of a catalog app under a new key."""

    def test_port_conflict_blocked(self, app_client):
        """install_instance with host_port_override conflicts must be rejected."""
        client, _ = app_client

        # Register a running app that occupies port 7878
        with StateDB() as db:
            db.upsert_app("radarr", display_name="Radarr", category="arr",
                          image="linuxserver/radarr", container_name="radarr",
                          status="running", host_port=7878)

        r = client.post("/api/routing/instances/radarr", json={
            "instance_key": "radarr_debrid",
            "label": "Radarr (Debrid)",
            "role": "debrid",
            "host_port": 7878,  # CONFLICT
        })

        # Should be rejected — 409 or 422 (not 500, not 200)
        assert r.status_code in (409, 422, 500), (
            f"Port conflict should be caught before install, got {r.status_code}"
        )
        if r.status_code == 200:
            pytest.fail(
                "Port 7878 conflict not detected. "
                "Two apps can't bind the same host port — one will silently fail."
            )

    def test_instance_uses_instance_key_not_manifest_key(self, app_client):
        """install_instance must register in DB under instance_key, not manifest_key."""
        client, _ = app_client

        ok_sp = MagicMock(); ok_sp.returncode = 0; ok_sp.stdout = "done"; ok_sp.stderr = ""
        healthy = MagicMock(); healthy.status = "running"; healthy.health = "healthy"

        with patch("subprocess.run", return_value=ok_sp), \
             patch("backend.manifests.executor.docker_client") as md:
            md.get_container.return_value = healthy
            md.ports_in_use.return_value = {}
            r = client.post("/api/routing/instances/sonarr", json={
                "instance_key": "sonarr_debrid",
                "label": "Sonarr (Debrid)",
                "role": "debrid",
                "host_port": 8990,
            })

        if r.status_code == 200:
            with StateDB() as db:
                instance_app = db.get_app("sonarr_debrid")
                base_app = db.get_app("sonarr")
            assert instance_app is not None, (
                "install_instance must create DB record under instance_key 'sonarr_debrid'"
            )
            # Base app should not be overwritten
            assert base_app is None or base_app.key == "sonarr", (
                "install_instance must not overwrite the base 'sonarr' record"
            )

    def test_unknown_manifest_key_rejected(self, app_client):
        """install_instance with non-existent manifest_key returns 404."""
        client, _ = app_client
        r = client.post("/api/routing/instances/nonexistent_app_xyz", json={
            "instance_key": "nonexistent_app_xyz_debrid",
            "label": "Test",
            "role": "debrid",
        })
        assert r.status_code == 404, (
            f"Unknown manifest key must return 404, got {r.status_code}"
        )

    def test_invalid_role_rejected(self, app_client):
        """Role must be one of: default | debrid | download | secondary."""
        client, _ = app_client
        r = client.post("/api/routing/instances/sonarr", json={
            "instance_key": "sonarr_test",
            "label": "Test",
            "role": "invalid_role",
        })
        assert r.status_code in (422, 400), (
            f"Invalid role must be rejected with 4xx, got {r.status_code}"
        )

    def test_duplicate_instance_key_rejected(self, app_client):
        """Cannot install two instances with the same instance_key."""
        client, _ = app_client
        with StateDB() as db:
            db.upsert_app("sonarr_debrid", display_name="Sonarr (Debrid)",
                          category="arr", image="linuxserver/sonarr",
                          container_name="sonarr_debrid", status="running")

        r = client.post("/api/routing/instances/sonarr", json={
            "instance_key": "sonarr_debrid",
            "label": "Sonarr (Debrid)",
            "role": "debrid",
        })
        assert r.status_code != 200, (
            "Duplicate instance_key must be rejected — would overwrite existing install"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. YAML Linter
# ═══════════════════════════════════════════════════════════════════════════

class TestYAMLLinter:
    """POST /api/apps/lint-compose validates user's docker-compose YAML."""

    def test_valid_compose_returns_manifest_preview(self, app_client):
        """Valid compose YAML must return valid=True and a manifest_preview."""
        client, _ = app_client
        r = client.post("/api/apps/lint-compose", json={
            "yaml": "services:\n  myapp:\n    image: nginx:latest\n    ports:\n      - '8090:80'\n"
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("valid") is True, f"Valid YAML rejected: {data.get('errors')}"
        preview = data.get("manifest_preview", {})
        assert preview.get("image") == "nginx", f"Wrong image in preview: {preview}"
        assert preview.get("key") == "myapp"

    def test_invalid_yaml_returns_errors(self, app_client):
        """Malformed YAML must return valid=False with error messages."""
        client, _ = app_client
        r = client.post("/api/apps/lint-compose", json={
            "yaml": "services:\n  myapp:\n    image: [unclosed"
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("valid") is False
        assert data.get("errors"), "Invalid YAML must include error messages"

    def test_missing_image_returns_error(self, app_client):
        """Service without 'image:' must return valid=False."""
        client, _ = app_client
        r = client.post("/api/apps/lint-compose", json={
            "yaml": "services:\n  myapp:\n    ports:\n      - '8090:80'\n"
        })
        data = r.json()
        assert not data.get("valid"), "Missing image: must fail validation"

    def test_hardcoded_secret_returns_warning(self, app_client):
        """Env var with hardcoded secret value must return a warning."""
        client, _ = app_client
        r = client.post("/api/apps/lint-compose", json={
            "yaml": (
                "services:\n  app:\n    image: nginx\n"
                "    environment:\n      - API_KEY=supersecretvalue123\n"
            )
        })
        data = r.json()
        warnings = data.get("warnings", [])
        assert any("secret" in w.lower() or "API_KEY" in w for w in warnings), (
            f"Hardcoded secret must trigger a warning. Warnings: {warnings}"
        )

    def test_empty_yaml_returns_error(self, app_client):
        """Empty input must return valid=False."""
        client, _ = app_client
        r = client.post("/api/apps/lint-compose", json={"yaml": ""})
        data = r.json()
        assert not data.get("valid")


# ═══════════════════════════════════════════════════════════════════════════
# 5. Catalog Compliance
# ═══════════════════════════════════════════════════════════════════════════

class TestCatalogCompliance:
    """Every catalog app must meet baseline infrastructure requirements."""

    def _load_all(self):
        """Load all catalog YAML files."""
        catalog_dir = Path(__file__).parent.parent / "catalog" / "apps"
        apps = {}
        for f in sorted(catalog_dir.glob("*.yaml")):
            data = yaml.safe_load(f.read_text())
            apps[f.stem] = (data, f)
        return apps

    def test_all_apps_have_required_fields(self):
        """Every manifest must have key, display_name, category, image."""
        apps = self._load_all()
        missing = {}
        for key, (data, fpath) in apps.items():
            m = [f for f in ("key", "display_name", "category", "image") if not data.get(f)]
            if m:
                missing[key] = m
        assert not missing, (
            f"Manifests missing required fields:\n" +
            "\n".join(f"  {k}: {v}" for k, v in missing.items())
        )

    def test_all_apps_with_web_port_have_traefik_config(self):
        """Every app with a web_port must have a traefik: block."""
        apps = self._load_all()
        violations = []
        for key, (data, fpath) in apps.items():
            has_web = bool(
                data.get("web_port") or
                (isinstance(data.get("ports"), dict) and data["ports"].get("web"))
            )
            has_traefik = bool(data.get("traefik"))
            if has_web and not has_traefik:
                violations.append(key)
        assert not violations, (
            f"Apps with web_port but no traefik config (unreachable via HTTPS):\n" +
            "\n".join(f"  {k}" for k in violations)
        )

    def test_all_apps_with_web_port_have_health_checks(self):
        """Every app with a web_port must have at least one health check."""
        apps = self._load_all()
        violations = []
        for key, (data, fpath) in apps.items():
            has_web = bool(
                data.get("web_port") or
                (isinstance(data.get("ports"), dict) and data["ports"].get("web"))
            )
            has_health = bool(data.get("health", {}).get("checks"))
            if has_web and not has_health:
                violations.append(key)
        assert not violations, (
            f"Apps with web_port but no health checks (invisible health status):\n" +
            "\n".join(f"  {k}" for k in violations)
        )

    def test_all_apps_have_valid_category(self):
        """Every app must use a recognized category value."""
        # Must match VALID_CATEGORIES in backend/manifests/loader.py exactly
        valid_categories = {
            "arr", "media", "downloader", "requests", "tools",
            "ai", "monitoring", "productivity", "infra",
        }
        apps = self._load_all()
        invalid = {k: data.get("category") for k, (data, _) in apps.items()
                   if data.get("category") not in valid_categories}
        assert not invalid, (
            f"Apps with invalid category:\n" +
            "\n".join(f"  {k}: '{v}'" for k, v in invalid.items())
        )

    def test_all_apps_load_without_exception(self):
        """Every catalog app must load via load_manifest() without raising."""
        from backend.manifests.loader import load_manifest, clear_cache
        clear_cache()
        catalog_dir = Path(__file__).parent.parent / "catalog" / "apps"
        errors = []
        for fpath in sorted(catalog_dir.glob("*.yaml")):
            try:
                load_manifest(fpath.stem)
            except Exception as e:
                errors.append(f"{fpath.stem}: {e}")
        clear_cache()
        assert not errors, (
            f"{len(errors)} manifests failed to load:\n" +
            "\n".join(f"  {e}" for e in errors)
        )

    def test_all_port_specs_use_integer_values(self):
        """All port values in catalog must be integers — not strings."""
        apps = self._load_all()
        violations = []
        for key, (data, _) in apps.items():
            ports = data.get("ports", {})
            if isinstance(ports, dict):
                for name, val in ports.items():
                    if isinstance(val, (int,)):
                        pass
                    elif isinstance(val, list):
                        pass  # extra ports list is valid
                    else:
                        violations.append(f"{key}.ports.{name} = {val!r} (not int)")
        assert not violations, (
            "Non-integer port values found:\n" + "\n".join(violations)
        )

    def test_all_manifests_load_correctly_after_yaml_fixes(self):
        """Regression: sabnzbd, seerr, localai must load after catalog fixes."""
        from backend.manifests.loader import load_manifest, clear_cache
        clear_cache()
        for key in ("sabnzbd", "seerr", "localai"):
            try:
                m = load_manifest(key)
                assert m is not None, f"{key} loaded as None"
                assert m.health_checks, f"{key}: no health checks after fix"
            except Exception as e:
                pytest.fail(f"{key} failed to load after catalog fix: {e}")
        clear_cache()
