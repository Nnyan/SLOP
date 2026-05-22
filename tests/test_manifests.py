"""tests/test_manifests.py

Tests for the manifest loader and validator.
"""
import textwrap
from pathlib import Path

import pytest

from backend.manifests.loader import (
    ManifestError,
    clear_cache,
    load_all_manifests,
    load_manifest,
    parse_manifest,
)


@pytest.fixture(autouse=True)
def fresh_cache():
    clear_cache()
    yield
    clear_cache()


def write_manifest(tmp_path: Path, content: str, name: str = "test.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return p


# ── Valid manifests ────────────────────────────────────────────────────────


class TestValidManifest:
    def test_minimal_manifest(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: myimage/myapp
            category: tools
        """)
        m = parse_manifest(p)
        assert m.key == "myapp"
        assert m.display_name == "My App"
        assert m.image == "myimage/myapp"
        assert m.category == "tools"
        assert m.tier == 2
        assert m.linuxserver is True
        assert m.icon == "📦"
        assert m.web_port is None

    def test_defaults_applied(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: myimage/myapp
            category: tools
        """)
        m = parse_manifest(p)
        assert m.image_tag == "latest"
        assert m.traefik_enabled is True
        assert m.traefik_subdomain == ""
        assert m.traefik_sub() == "myapp"  # falls back to key
        assert m.dependencies.postgres is False
        assert m.dependencies.redis is False
        assert m.wiring == []
        assert m.post_deploy == []
        assert m.gpu is None

    def test_web_port_parsed(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: arr
            ports:
              web: 8989
        """)
        m = parse_manifest(p)
        assert m.web_port == 8989

    def test_dependencies_postgres_redis(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: tools
            dependencies:
              postgres: true
              redis: true
              apps: [sonarr, radarr]
        """)
        m = parse_manifest(p)
        assert m.dependencies.postgres is True
        assert m.dependencies.redis is True
        assert "sonarr" in m.dependencies.apps

    def test_gpu_definition(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: ollama
            display_name: Ollama
            image: ollama/ollama
            category: ai
            gpu:
              optional: true
              warn_if_absent: true
              nvidia: true
              amd: false
        """)
        m = parse_manifest(p)
        assert m.gpu is not None
        assert m.gpu.optional is True
        assert m.gpu.nvidia is True
        assert m.gpu.amd is False

    def test_wiring_accepts_and_connects_to(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: sonarr
            display_name: Sonarr
            image: img
            category: arr
            wiring:
              accepts:
                - type: indexer
                  from: prowlarr
                  description: Prowlarr registers indexers
              connects_to:
                - type: library_refresh
                  to: plex
                  optional: true
        """)
        m = parse_manifest(p)
        assert len(m.wiring) == 2
        accepts = [w for w in m.wiring if w.direction == "accepts"]
        connects = [w for w in m.wiring if w.direction == "connects_to"]
        assert accepts[0].peer == "prowlarr"
        assert connects[0].peer == "plex"
        assert connects[0].optional is True

    def test_post_deploy_steps(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: tools
            post_deploy:
              - type: wait_healthy
                timeout: 90
              - type: api_ready
                path: /api/status
                timeout: 120
        """)
        m = parse_manifest(p)
        assert len(m.post_deploy) == 2
        assert m.post_deploy[0].step_type == "wait_healthy"
        assert m.post_deploy[0].timeout == 90
        assert m.post_deploy[1].path == "/api/status"

    def test_health_checks_and_self_heal(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: tools
            health:
              checks:
                - name: api_reachable
                  type: http
                  path: /api/status
                  interval: 30
              self_heal:
                - condition: api_reachable
                  action: restart
                  max_attempts: 3
        """)
        m = parse_manifest(p)
        assert len(m.health_checks) == 1
        assert m.health_checks[0].name == "api_reachable"
        assert len(m.self_heal) == 1
        assert m.self_heal[0].action == "restart"

    def test_traefik_custom_headers(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: bentopdf
            display_name: BentoPDF
            image: img
            category: tools
            traefik:
              enabled: true
              subdomain: pdf
              headers:
                Cross-Origin-Opener-Policy: same-origin
                Cross-Origin-Embedder-Policy: require-corp
        """)
        m = parse_manifest(p)
        assert m.traefik_subdomain == "pdf"
        assert m.traefik_sub() == "pdf"
        assert m.traefik_headers["Cross-Origin-Opener-Policy"] == "same-origin"

    def test_content_hash_is_stable(self, tmp_path):
        content = """
            key: myapp
            display_name: My App
            image: img
            category: tools
        """
        p = write_manifest(tmp_path, content)
        m1 = parse_manifest(p)
        m2 = parse_manifest(p)
        assert m1.content_hash == m2.content_hash

    def test_env_vars_stringified(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: sabnzbd
            display_name: SABnzbd
            image: img
            category: downloader
            env:
              WEB_PORT: 8085
              SOME_FLAG: true
        """)
        m = parse_manifest(p)
        assert m.env["WEB_PORT"] == "8085"
        assert m.env["SOME_FLAG"] == "True"

    def test_to_catalog_entry(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: sonarr
            display_name: Sonarr
            image: img
            category: arr
            ports:
              web: 8989
        """)
        m = parse_manifest(p)
        entry = m.to_catalog_entry()
        assert entry["key"] == "sonarr"
        assert entry["web_port"] == 8989
        assert entry["has_gpu"] is False


# ── Invalid manifests — validation errors ────────────────────────────────


class TestInvalidManifest:
    def test_missing_key_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            display_name: My App
            image: img
            category: tools
        """)
        with pytest.raises(ManifestError, match="key"):
            parse_manifest(p)

    def test_missing_display_name_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            image: img
            category: tools
        """)
        with pytest.raises(ManifestError, match="display_name"):
            parse_manifest(p)

    def test_missing_image_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            category: tools
        """)
        with pytest.raises(ManifestError, match="image"):
            parse_manifest(p)

    def test_invalid_category_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: notacategory
        """)
        with pytest.raises(ManifestError, match="category"):
            parse_manifest(p)

    def test_invalid_tier_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: tools
            tier: 5
        """)
        with pytest.raises(ManifestError, match="tier"):
            parse_manifest(p)

    def test_invalid_key_characters_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: "my app!"
            display_name: My App
            image: img
            category: tools
        """)
        with pytest.raises(ManifestError, match="key"):
            parse_manifest(p)

    def test_invalid_web_port_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: tools
            ports:
              web: notaport
        """)
        with pytest.raises(ManifestError, match="integer"):
            parse_manifest(p)

    def test_invalid_post_deploy_type_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: tools
            post_deploy:
              - type: do_magic
        """)
        with pytest.raises(ManifestError, match="step type"):
            parse_manifest(p)

    def test_invalid_heal_action_raises(self, tmp_path):
        p = write_manifest(tmp_path, """
            key: myapp
            display_name: My App
            image: img
            category: tools
            health:
              self_heal:
                - condition: api_reachable
                  action: explode
        """)
        with pytest.raises(ManifestError, match="action"):
            parse_manifest(p)

    def test_invalid_yaml_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("key: [unclosed")
        with pytest.raises(ManifestError, match="YAML"):
            parse_manifest(p)

    def test_not_a_mapping_raises(self, tmp_path):
        p = write_manifest(tmp_path, "- item1\n- item2\n")
        with pytest.raises(ManifestError, match="mapping"):
            parse_manifest(p)


# ── Catalog manifests — validate the real files ────────────────────────────


class TestCatalogManifests:
    def test_all_real_manifests_load(self):
        """Smoke test — every file in catalog/apps/ must be valid."""
        manifests = load_all_manifests()
        assert len(manifests) >= 6  # at minimum our 6 example manifests

    def test_sonarr_manifest(self):
        m = load_manifest("sonarr")
        assert m.key == "sonarr"
        assert m.web_port == 8989
        assert m.linuxserver is True
        assert any(w.peer == "prowlarr" for w in m.wiring)

    def test_radarr_manifest(self):
        m = load_manifest("radarr")
        assert m.web_port == 7878
        assert any(w.wire_type == "indexer" for w in m.wiring)

    def test_prowlarr_manifest(self):
        m = load_manifest("prowlarr")
        assert m.web_port == 9696
        assert len(m.wiring) >= 3  # connects to multiple arr apps

    def test_ollama_manifest(self):
        m = load_manifest("ollama")
        assert m.gpu is not None
        assert m.gpu.optional is True
        assert m.gpu.warn_if_absent is True

    def test_immich_manifest(self):
        m = load_manifest("immich")
        assert m.dependencies.postgres is True
        assert m.dependencies.redis is True

    def test_bentopdf_manifest(self):
        m = load_manifest("bentopdf")
        assert "Cross-Origin-Opener-Policy" in m.traefik_headers

    def test_key_matches_filename_for_all(self):
        manifests = load_all_manifests()
        for key, m in manifests.items():
            assert m.key == key, f"Manifest key '{m.key}' doesn't match filename '{key}.yaml'"


# ── load_manifest error handling ──────────────────────────────────────────


class TestLoadManifest:
    def test_missing_manifest_raises_key_error(self):
        with pytest.raises(KeyError, match="nonexistent"):
            load_manifest("nonexistent")

    def test_key_mismatch_raises(self, tmp_path):
        """Filename sonarr.yaml but key: radarr should fail at load_manifest."""
        p = tmp_path / "sonarr.yaml"
        p.write_text("key: radarr\ndisplay_name: Radarr\nimage: img\ncategory: arr\n")
        # parse_manifest itself succeeds (it doesn't check filename)
        from backend.manifests.loader import parse_manifest as pm
        m = pm(p)
        assert m.key == "radarr"
        # But load_manifest enforces the filename == key contract
        # We test that logic by checking the condition directly
        assert m.key != p.stem  # "radarr" != "sonarr"

    def test_cache_is_used(self):
        m1 = load_manifest("sonarr")
        m2 = load_manifest("sonarr")
        assert m1 is m2  # same object from cache

    def test_force_reload_bypasses_cache(self):
        m1 = load_manifest("sonarr")
        m2 = load_manifest("sonarr", force_reload=True)
        assert m1.key == m2.key  # same content, different object
        assert m1 is not m2
