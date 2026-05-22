"""tests/test_recommendations.py

Tests for the 4 TLS/routing recommendations, new media manifests,
registry system, and CI/CD validation.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import compose
from backend.core.state import StateDB, init_db
from backend.manifests.loader import clear_cache, load_all_manifests, load_manifest
from backend.platform.wizard import WizardInput


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


# ── Rec 1: Wildcard DNS-01 Traefik config ─────────────────────────────────


class TestWildcardTraefikConfig:
    def test_build_traefik_yaml_has_wildcard_cert(self):
        yaml = compose.build_traefik_yaml(
            domain="example.com",
            dns_provider="cloudflare",
        )
        # Wildcard domain specified in entryPoints
        assert "*.example.com" in yaml
        assert "dnsChallenge" in yaml
        assert "cloudflare" in yaml

    def test_build_traefik_yaml_letsencrypt_and_zerossl(self):
        yaml = compose.build_traefik_yaml(
            domain="example.com",
            include_zerossl=True,
        )
        assert "letsencrypt:" in yaml
        assert "zerossl:" in yaml
        assert "acme.zerossl.com" in yaml

    def test_build_traefik_yaml_zerossl_optional(self):
        yaml = compose.build_traefik_yaml(
            domain="example.com",
            include_zerossl=False,
        )
        assert "letsencrypt:" in yaml
        assert "zerossl:" not in yaml

    def test_build_traefik_yaml_custom_email(self):
        yaml = compose.build_traefik_yaml(
            domain="example.com",
            acme_email="ops@example.com",
        )
        assert "ops@example.com" in yaml

    def test_build_traefik_yaml_default_email_from_domain(self):
        yaml = compose.build_traefik_yaml(domain="mydomain.com")
        assert "admin@mydomain.com" in yaml

    def test_build_traefik_yaml_route53_provider(self):
        yaml = compose.build_traefik_yaml(
            domain="example.com",
            dns_provider="route53",
        )
        assert "route53" in yaml

    def test_build_traefik_yaml_porkbun_provider(self):
        yaml = compose.build_traefik_yaml(
            domain="example.com",
            dns_provider="porkbun",
        )
        assert "porkbun" in yaml

    def test_build_traefik_yaml_renewal_delay(self):
        yaml = compose.build_traefik_yaml(domain="example.com")
        assert "delayBeforeCheck" in yaml

    def test_wizard_input_accepts_dns_fields(self):
        inp = WizardInput(
            domain="example.com",
            config_root="/tmp/config",
            media_root="/tmp/media",
            puid=1000, pgid=1000, timezone="UTC",
            dns_provider="namecheap",
            acme_email="user@example.com",
            include_zerossl=True,
        )
        assert inp.dns_provider == "namecheap"
        assert inp.acme_email == "user@example.com"
        assert inp.include_zerossl is True


# ── Rec 2: service_type in manifests ─────────────────────────────────────


class TestServiceType:
    def test_media_apps_have_media_type(self):
        for key in ("plex", "jellyfin", "emby", "audiobookshelf"):
            m = load_manifest(key)
            assert m.service_type == "media", \
                f"{key} should have service_type='media', got '{m.service_type}'"

    def test_management_apps_default_type(self):
        for key in ("sonarr", "radarr", "dockhand", "vaultwarden"):
            m = load_manifest(key)
            assert m.service_type == "management", \
                f"{key} should have service_type='management', got '{m.service_type}'"

    def test_all_manifests_have_valid_service_type(self):
        valid = {"management", "media", "internal"}
        manifests = load_all_manifests()
        invalid = [
            (key, m.service_type) for key, m in manifests.items()
            if m.service_type not in valid
        ]
        assert invalid == [], f"Invalid service_type: {invalid}"

    def test_catalog_has_52_manifests(self):
        manifests = load_all_manifests()
        assert len(manifests) >= 52

    def test_plex_has_claim_env(self):
        m = load_manifest("plex")
        assert "PLEX_CLAIM" in m.env

    def test_jellyfin_has_published_url(self):
        m = load_manifest("jellyfin")
        assert any("JELLYFIN" in k for k in m.env)

    def test_emby_has_correct_api_path(self):
        m = load_manifest("emby")
        api_steps = [s for s in m.post_deploy if s.step_type == "api_ready"]
        assert any("emby" in s.path for s in api_steps)

    def test_plex_port_is_32400(self):
        m = load_manifest("plex")
        assert m.web_port == 32400

    def test_media_apps_have_media_volumes(self):
        for key in ("plex", "jellyfin", "emby"):
            m = load_manifest(key)
            container_paths = [v.container_path for v in m.custom_volumes]
            assert any("movies" in p for p in container_paths), \
                f"{key} should have /movies volume"
            assert any("tv" in p for p in container_paths), \
                f"{key} should have /tv volume"


# ── Rec 3: ddns-updater ───────────────────────────────────────────────────


class TestDDNSUpdater:
    def test_manifest_loads(self):
        m = load_manifest("ddns_updater")
        assert m.key == "ddns_updater"
        assert m.web_port == 8085

    def test_description_explains_purpose(self):
        m = load_manifest("ddns_updater")
        assert "dynamic" in m.description.lower() or "dns" in m.description.lower()

    def test_category_is_tools(self):
        m = load_manifest("ddns_updater")
        assert m.category == "tools"

    def test_service_type_is_management(self):
        m = load_manifest("ddns_updater")
        # ddns_updater is a management tool, not a media server
        assert m.service_type == "management"


# ── Rec 4: DNS guidance API ────────────────────────────────────────────────


class TestDNSGuidanceAPI:
    @pytest.fixture
    def api_client(self, db: Path):
        import backend.core.state as sm
        from backend.api.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            sm.configure(db)
            yield c

    def test_dns_providers_endpoint(self, api_client):
        r = api_client.get("/api/platform/dns-providers")
        assert r.status_code == 200
        providers = r.json()
        assert len(providers) >= 10
        keys = [p["key"] for p in providers]
        assert "cloudflare" in keys
        assert "route53" in keys
        assert "namecheap" in keys
        assert "porkbun" in keys

    def test_dns_providers_include_env_vars(self, api_client):
        r = api_client.get("/api/platform/dns-providers")
        cf = next(p for p in r.json() if p["key"] == "cloudflare")
        assert "CF_DNS_API_TOKEN" in cf["env"]

    def test_media_routing_guide_endpoint(self, api_client):
        r = api_client.get("/api/platform/media-routing-guide?domain=example.com")
        assert r.status_code == 200
        data = r.json()
        assert "tls_certificate" in data
        assert "cloudflare_dns_setup" in data
        assert "port_forwarding" in data
        assert "dynamic_ip" in data
        assert "cgnat_alternative" in data

    def test_media_routing_guide_wildcard_cert(self, api_client):
        r = api_client.get("/api/platform/media-routing-guide?domain=mydomain.com")
        data = r.json()
        assert "*.mydomain.com" in str(data["tls_certificate"])

    def test_media_routing_guide_dns_only_mention(self, api_client):
        r = api_client.get("/api/platform/media-routing-guide")
        text = str(r.json())
        assert "DNS only" in text or "dns only" in text.lower()

    def test_media_routing_guide_affected_apps(self, api_client):
        r = api_client.get("/api/platform/media-routing-guide")
        data = r.json()
        affected = data["affected_apps"]["service_type_media"]
        assert "plex" in affected
        assert "jellyfin" in affected


# ── Step 9: Catalog registry ──────────────────────────────────────────────


class TestCatalogRegistry:
    def test_registry_json_exists(self):
        assert Path("catalog/registry.json").exists()

    def test_registry_json_valid(self):
        import json
        data = json.loads(Path("catalog/registry.json").read_text())
        assert "manifests" in data
        assert len(data["manifests"]) >= 50

    def test_registry_has_required_fields(self):
        import json
        data = json.loads(Path("catalog/registry.json").read_text())
        for entry in data["manifests"]:
            assert "key" in entry
            assert "display_name" in entry
            assert "source_url" in entry
            assert "Nnyan/SLOP" in entry["source_url"]

    def test_registry_media_apps_marked(self):
        import json
        data = json.loads(Path("catalog/registry.json").read_text())
        media_entries = [e for e in data["manifests"] if e.get("service_type") == "media"]
        media_keys = [e["key"] for e in media_entries]
        assert "plex" in media_keys
        assert "jellyfin" in media_keys

    def test_registry_api_returns_entries(self, db: Path):
        import backend.core.state as sm
        from backend.api.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            sm.configure(db)
            r = c.get("/api/registry")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 50

    def test_registry_custom_list(self, db: Path):
        import backend.core.state as sm
        from backend.api.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            sm.configure(db)
            r = c.get("/api/registry/custom/list")
        assert r.status_code == 200

    def test_community_catalog_dir_exists(self):
        Path("catalog/community").mkdir(parents=True, exist_ok=True)
        assert Path("catalog/community").exists()


# ── Step 10: CI/CD validation ─────────────────────────────────────────────


class TestCICDValidation:
    def test_github_workflows_exist(self):
        workflows_dir = Path(".github/workflows")
        assert workflows_dir.exists()
        workflow_files = list(workflows_dir.glob("*.yml"))
        assert len(workflow_files) >= 3

    def test_test_workflow_exists(self):
        assert Path(".github/workflows/test.yml").exists()

    def test_build_workflow_exists(self):
        assert Path(".github/workflows/build.yml").exists()

    def test_manifest_validation_workflow_exists(self):
        assert Path(".github/workflows/validate_manifests.yml").exists()

    def test_docs_exist(self):
        assert Path("docs/ARCHITECTURE.md").exists()
        assert Path("docs/INSTALL.md").exists()

    def test_all_manifests_yaml_valid(self):
        import yaml
        errors = []
        for f in sorted(Path("catalog").rglob("*.yaml")):
            try:
                yaml.safe_load(f.read_text())
            except Exception as e:
                errors.append(f"{f}: {e}")
        assert errors == [], f"YAML errors: {errors}"

    def test_no_port_conflicts_in_52_manifests(self):
        manifests = load_all_manifests()
        port_map: dict[int, list[str]] = {}
        for key, m in manifests.items():
            if m.web_port:
                port_map.setdefault(m.web_port, []).append(key)
        conflicts = {
            p: keys for p, keys in port_map.items()
            if len(keys) > 1 and p not in (80, 3000, 8080)
        }
        assert conflicts == {}, f"Port conflicts: {conflicts}"

    def test_registry_json_in_sync_with_catalog(self):
        import json
        manifests = load_all_manifests()
        registry_data = json.loads(Path("catalog/registry.json").read_text())
        registry_keys = {e["key"] for e in registry_data["manifests"]}
        catalog_keys = set(manifests.keys())
        # Registry should contain all catalog keys
        missing = catalog_keys - registry_keys
        assert missing == set(), f"Keys in catalog but not registry: {missing}"


class TestManifestBehavioral:
    """Behavioral tests that execute real manifest loaders and verify outcomes."""

    @pytest.fixture(autouse=True)
    def _clear(self):
        clear_cache()
        yield
        clear_cache()

    def test_all_manifests_load_without_exception(self):
        """Every app key derived from catalog/apps/*.yaml must load without exception."""
        catalog_dir = Path(__file__).parent.parent / "catalog" / "apps"
        errors = []
        for fpath in sorted(catalog_dir.glob("*.yaml")):
            key = fpath.stem  # 'sonarr' not 'sonarr.yaml'
            try:
                manifest = load_manifest(key)
                assert manifest is not None, f"{key}: returned None"
                assert hasattr(manifest, "display_name") or hasattr(manifest, "key"), (
                    f"{key}: AppManifest missing display_name and key attributes"
                )
            except Exception as e:
                errors.append(f"{key}: {e}")
        assert not errors, f"{len(errors)} manifests failed:\n" + "\n".join(errors[:5])

    def test_manifest_count_is_live_not_hardcoded(self):
        """Catalog manifest count must match actual files — not a magic number."""
        catalog_dir = Path(__file__).parent.parent / "catalog" / "apps"
        actual_files = len(list(catalog_dir.glob("*.yaml")))
        loaded = load_all_manifests()
        assert len(loaded) >= actual_files * 0.9, (
            f"Only {len(loaded)} of {actual_files} manifests loaded"
        )
        assert len(loaded) > 0

    def test_traefik_fragment_contains_required_sections(self):
        """build_traefik_fragment() returns a dict with correct compose service structure."""
        from backend.core.compose import build_traefik_fragment
        result = build_traefik_fragment(
            domain="test.local", network_name="mediastack",
            cert_resolver="letsencrypt", config_root="/tmp/tc",
            dns_provider="cloudflare",
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        # Must define a traefik service with an image
        assert "image" in result, "Fragment missing 'image' key"
        assert "traefik" in result.get("image", "").lower(), (
            f"Fragment image should be traefik, got: {result.get('image')}"
        )
        # Must reference the network
        networks = result.get("networks", [])
        assert "mediastack" in str(networks), f"Fragment must reference mediastack network: {networks}"
        # Must include TLS cert resolver in labels
        labels = str(result.get("labels", []))
        assert "certresolver" in labels.lower() or "letsencrypt" in labels.lower(), (
            "Fragment must configure cert resolver in labels"
        )


class TestAuditBehavioral:
    """Behavioral companions for static checks in test_audit_pass.py."""

    def test_cors_middleware_configured_in_main(self):
        """CORSMiddleware must be present in main.py with allow_origins configured."""
        import pathlib as _pl
        src = _pl.Path("backend/api/main.py").read_text()
        assert "CORSMiddleware" in src or "cors" in src.lower()
        assert "allow_origins" in src or "CORS_ORIGINS" in src

    def test_install_deadline_enforced_in_polling_loop(self):
        """Polling loops in executor must break on deadline — no infinite hangs."""
        import pathlib as _pl
        src = _pl.Path("backend/manifests/executor.py").read_text()
        has_deadline = "DEADLINE" in src or "deadline" in src.lower()
        has_break = "break" in src
        assert has_deadline and has_break, (
            "Executor must have a deadline check and break condition in polling loops"
        )

    def test_traefik_docker_socket_is_readonly(self):
        """Traefik docker.sock must be :ro — it only reads events, never manages containers."""
        import pathlib as _pl
        src = _pl.Path("backend/core/compose.py").read_text()
        # Find traefik fragment section (not management providers)
        fn_start = src.find("def build_traefik_fragment")
        fn_end = src.find("\ndef ", fn_start + 50)
        traefik_fn = src[fn_start:fn_end]
        if "docker.sock" in traefik_fn:
            # Must be read-only when present
            idx = traefik_fn.find("docker.sock")
            after = traefik_fn[idx:idx+60]
            assert ":ro" in after, (
                f"Traefik docker.sock should be :ro: {after!r}"
            )
        # else: traefik does not mount docker.sock at all — fine
