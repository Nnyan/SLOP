"""tests/test_routing.py

Tests for multi-instance app management, request routing config,
new arr manifests, and Seerr setup guidance.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.core import state as state_mod
from backend.core.state import StateDB, init_db
from backend.manifests.executor import (
    get_instances_for_manifest,
    install_instance,
    list_instances,
)
from backend.manifests.loader import clear_cache, load_all_manifests, load_manifest
from backend.api.routing import (
    MEDIA_TYPE_MANIFEST,
    SEERR_SUPPORTED,
    VALID_MEDIA_TYPES,
    _all_routing,
    _load_routing,
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
def api_client(db: Path):
    from backend.api.main import app
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=True) as c:
        state_mod.configure(db)
        yield c


# ── New arr manifests ──────────────────────────────────────────────────────


class TestNewArrManifests:
    def test_lidarr_loads(self):
        m = load_manifest("lidarr")
        assert m.web_port == 8686
        assert m.linuxserver is True
        assert any(w.wire_type == "indexer" for w in m.wiring)

    def test_readarr_loads(self):
        m = load_manifest("readarr")
        assert m.web_port == 8787
        assert m.linuxserver is True

    def test_bazarr_loads(self):
        m = load_manifest("bazarr")
        assert m.web_port == 6767
        assert any(w.peer == "sonarr" for w in m.wiring)
        assert any(w.peer == "radarr" for w in m.wiring)

    def test_mylar3_loads(self):
        m = load_manifest("mylar3")
        assert m.web_port == 8091
        assert m.category == "arr"

    def test_audiobookshelf_loads(self):
        m = load_manifest("audiobookshelf")
        assert m.web_port == 13378
        assert m.category == "media"
        assert m.linuxserver is False

    def test_whisparr_loads(self):
        m = load_manifest("whisparr")
        assert m.web_port == 6969
        assert m.category == "arr"

    def test_catalog_has_45_manifests(self):
        manifests = load_all_manifests()
        assert len(manifests) >= 45

    def test_all_arr_have_prowlarr_wiring(self):
        """All arr apps that use indexers should accept wiring from Prowlarr."""
        arr_with_indexers = ["sonarr", "radarr", "lidarr", "readarr", "whisparr"]
        for key in arr_with_indexers:
            m = load_manifest(key)
            has_prowlarr = any(
                w.wire_type == "indexer" and w.peer == "prowlarr"
                for w in m.wiring
            )
            assert has_prowlarr, f"{key} should accept indexer wiring from prowlarr"

    def test_audiobookshelf_has_media_volumes(self):
        m = load_manifest("audiobookshelf")
        container_paths = [v.container_path for v in m.custom_volumes]
        assert any("audiobooks" in p for p in container_paths)
        assert any("podcasts" in p for p in container_paths)

    def test_no_port_conflicts_in_full_catalog(self):
        manifests = load_all_manifests()
        port_map: dict[int, list[str]] = {}
        for key, m in manifests.items():
            if m.web_port:
                port_map.setdefault(m.web_port, []).append(key)
        # No conflicts outside of commonly shared ports
        conflicts = {
            p: keys for p, keys in port_map.items()
            if len(keys) > 1 and p not in (80, 3000, 8080)
        }
        assert conflicts == {}, f"Port conflicts: {conflicts}"


# ── Routing config ─────────────────────────────────────────────────────────


class TestRoutingConfig:
    def test_all_media_types_seeded(self, db):
        rows = _all_routing()
        types = {r["media_type"] for r in rows}
        assert types == set(VALID_MEDIA_TYPES)

    def test_all_default_to_download(self, db):
        for row in _all_routing():
            assert row["default_path"] == "download"

    def test_seerr_supported_only_movies_tv(self):
        assert SEERR_SUPPORTED == {"movies", "tv"}

    def test_media_type_manifest_mapping(self):
        assert MEDIA_TYPE_MANIFEST["movies"] == "radarr"
        assert MEDIA_TYPE_MANIFEST["tv"] == "sonarr"
        assert MEDIA_TYPE_MANIFEST["music"] == "lidarr"
        assert MEDIA_TYPE_MANIFEST["books"] == "readarr"
        assert MEDIA_TYPE_MANIFEST["comics"] == "mylar3"
        assert MEDIA_TYPE_MANIFEST["adult"] == "whisparr"

    def test_load_routing_movies(self, db):
        r = _load_routing("movies")
        assert r["media_type"] == "movies"
        assert r["default_path"] == "download"

    def test_load_routing_missing_raises(self, db):
        with pytest.raises(KeyError):
            _load_routing("doesnotexist")


# ── API: routing endpoints ─────────────────────────────────────────────────


class TestRoutingAPI:
    def test_get_all_routing(self, api_client: TestClient):
        r = api_client.get("/api/routing/media")
        assert r.status_code == 200
        data = r.json()
        types = {item["media_type"] for item in data}
        assert "movies" in types
        assert "tv" in types
        assert "music" in types
        assert "adult" in types

    def test_get_routing_for_movies(self, api_client: TestClient):
        r = api_client.get("/api/routing/media/movies")
        assert r.status_code == 200
        data = r.json()
        assert data["media_type"] == "movies"
        assert data["canonical_manifest"] == "radarr"
        assert data["seerr_supported"] is True

    def test_get_routing_for_music(self, api_client: TestClient):
        r = api_client.get("/api/routing/media/music")
        assert r.status_code == 200
        data = r.json()
        assert data["seerr_supported"] is False
        assert data["canonical_manifest"] == "lidarr"

    def test_get_routing_invalid_type(self, api_client: TestClient):
        r = api_client.get("/api/routing/media/games")
        assert r.status_code == 404

    def test_update_routing_without_instances(self, api_client: TestClient):
        # Can set default_path without instances installed
        r = api_client.put("/api/routing/media/movies", json={
            "default_path": "debrid",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["default_path"] == "debrid"

    def test_update_routing_invalid_path(self, api_client: TestClient):
        r = api_client.put("/api/routing/media/movies", json={
            "default_path": "maybe",
        })
        assert r.status_code == 422

    def test_update_routing_with_nonexistent_instance(self, api_client: TestClient):
        r = api_client.put("/api/routing/media/movies", json={
            "debrid_instance": "radarr_debrid_which_does_not_exist",
            "default_path": "debrid",
        })
        assert r.status_code == 404

    def test_seerr_help_movies(self, api_client: TestClient):
        r = api_client.get("/api/routing/media/movies/seerr-help")
        assert r.status_code == 200
        data = r.json()
        assert data["seerr_supported"] is True
        assert len(data["steps"]) >= 5
        assert any("Seerr" in s or "Radarr" in s for s in data["steps"])

    def test_seerr_help_music_not_supported(self, api_client: TestClient):
        r = api_client.get("/api/routing/media/music/seerr-help")
        assert r.status_code == 200
        data = r.json()
        assert data["seerr_supported"] is False
        assert any("Decypharr" in s or "download client" in s.lower() for s in data["steps"])

    def test_seerr_help_books(self, api_client: TestClient):
        r = api_client.get("/api/routing/media/books/seerr-help")
        assert r.status_code == 200
        data = r.json()
        assert data["seerr_supported"] is False
        assert any("Readarr" in s for s in data["steps"])

    def test_get_all_instances_empty(self, api_client: TestClient):
        r = api_client.get("/api/routing/instances")
        assert r.status_code == 200
        assert r.json() == []


# ── Multi-instance executor (unit) ────────────────────────────────────────


class TestMultiInstance:
    def test_install_instance_invalid_role(self, db):
        result = install_instance(
            manifest_key="radarr",
            instance_key="radarr_test",
            instance_label="Test",
            role="invalid_role",
        )
        assert result.ok is False
        assert "role" in result.error.lower()

    def test_install_instance_bad_manifest(self, db):
        result = install_instance(
            manifest_key="doesnotexist",
            instance_key="doesnotexist_debrid",
            instance_label="Test",
            role="debrid",
        )
        assert result.ok is False
        assert "manifest" in result.error.lower() or "not found" in result.error.lower()

    def test_list_instances_empty(self, db):
        instances = list_instances()
        assert instances == []

    def test_get_instances_for_manifest_empty(self, db):
        instances = get_instances_for_manifest("radarr")
        assert instances == []

    def test_instance_key_uniqueness(self, db):
        """Installing the same instance_key twice should fail gracefully."""
        # Simulate an already-installed app
        with StateDB() as s:
            s.upsert_app(
                "radarr_debrid",
                display_name="Radarr Debrid",
                category="arr",
                image="img",
                image_tag="latest",
                container_name="radarr_debrid",
                web_port=7878,
                host_port=7879,
                config_path="/config/radarr_debrid",
                manifest_source="catalog",
                manifest_hash="abc",
                status="running",
            )
        result = install_instance(
            manifest_key="radarr",
            instance_key="radarr_debrid",
            instance_label="Radarr (Debrid)",
            role="debrid",
        )
        assert result.ok is False
        assert "already installed" in result.error.lower()

    def test_routing_config_persists(self, db):
        """Updating routing config should persist across calls."""
        with StateDB() as s:
            s._c.execute(
                """UPDATE request_routing SET default_path='debrid'
                   WHERE media_type='movies'"""
            )
            s._c.commit()
        r = _load_routing("movies")
        assert r["default_path"] == "debrid"

    def test_all_media_types_in_routing(self, db):
        """Every valid media type should have a row in request_routing."""
        rows = _all_routing()
        types = {r["media_type"] for r in rows}
        for mt in VALID_MEDIA_TYPES:
            assert mt in types, f"Missing routing for media type: {mt}"

    def test_instance_result_fields(self):
        """InstanceResult has all required fields."""
        from backend.manifests.executor import InstanceResult
        r = InstanceResult(
            instance_key="sonarr_debrid",
            manifest_key="sonarr",
            ok=True,
            role="debrid",
        )
        assert r.instance_key == "sonarr_debrid"
        assert r.manifest_key == "sonarr"
        assert r.role == "debrid"
        assert r.error is None
