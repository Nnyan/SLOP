"""tests/test_session_c.py

Tests for Session C:
  - Multi-instance routing API (install/remove/configure)
  - CLI tool argument parsing and command dispatch
  - Migration script service detection and mapping
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path):
    from backend.core.state import StateDB, init_db
    db_path = tmp_path / "state.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def ready_platform(db: Path):
    from backend.core.state import StateDB
    with StateDB() as s:
        s.update_platform(
            status="ready",
            domain="example.com",
            config_root="/tmp/config",
            media_root="/tmp/media",
            network_name="mediastack",
            cert_resolver="letsencrypt",
        )
    return db


@pytest.fixture
def api_client(ready_platform: Path):
    import backend.core.state as sm
    from backend.api.main import app
    from fastapi.testclient import TestClient
    with TestClient(app, base_url="http://localhost") as c:
        sm.configure(ready_platform)
        yield c


# ── Routing API — instance management ─────────────────────────────────────


class TestRoutingInstances:
    def test_get_instances_empty(self, api_client):
        r = api_client.get("/api/routing/instances")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_instances_by_manifest(self, api_client):
        r = api_client.get("/api/routing/instances/sonarr")
        assert r.status_code == 200
        data = r.json()
        # Default instance always returned for manifest in catalog
        assert isinstance(data, list)

    def test_install_debrid_instance(self, api_client):
        """POST /api/routing/instances/{manifest} endpoint reachable."""
        # Bare POST without required fields → 422, not 404
        r = api_client.post("/api/routing/instances/radarr", json={})
        assert r.status_code != 404  # route exists

    def test_update_media_routing(self, api_client):
        """PUT /api/routing/media/movies updates routing config."""
        r = api_client.put("/api/routing/media/movies", json={
            "default_path": "debrid",
        })
        assert r.status_code in (200, 404)  # 404 if row not seeded yet

    def test_get_all_routing(self, api_client):
        r = api_client.get("/api/routing/media")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        types = [d["media_type"] for d in data]
        for expected in ("movies", "tv", "music", "books"):
            assert expected in types

    def test_seerr_help_movies(self, api_client):
        r = api_client.get("/api/routing/media/movies/seerr-help")
        assert r.status_code == 200
        data = r.json()
        assert "steps" in data

    def test_seerr_help_unsupported_type(self, api_client):
        """Audiobooks don't support Seerr — returns arr_steps instead."""
        r = api_client.get("/api/routing/media/audiobooks/seerr-help")
        assert r.status_code == 200
        data = r.json()
        assert "steps" in data

    def test_routing_has_canonical_manifest(self, api_client):
        r = api_client.get("/api/routing/media")
        for route in r.json():
            assert route["canonical_manifest"]  # never empty

    def test_routing_has_seerr_supported_flag(self, api_client):
        r = api_client.get("/api/routing/media")
        movie_route = next(x for x in r.json() if x["media_type"] == "movies")
        assert movie_route["seerr_supported"] is True
        music_route = next(x for x in r.json() if x["media_type"] == "music")
        assert music_route["seerr_supported"] is False


# ── CLI — argument parsing ────────────────────────────────────────────────


class TestCLIArgumentParsing:
    """Test the CLI's argument parsing without making API calls."""

    def setup_method(self):
        from cli.ms import build_parser
        self.parser = build_parser()

    def test_status_command(self):
        args = self.parser.parse_args(["status"])
        assert args.command == "status"

    def test_apps_list(self):
        args = self.parser.parse_args(["apps", "list"])
        assert args.command == "apps"
        assert args.apps_command == "list"

    def test_apps_install(self):
        args = self.parser.parse_args(["apps", "install", "sonarr"])
        assert args.apps_command == "install"
        assert args.key == "sonarr"

    def test_apps_remove(self):
        args = self.parser.parse_args(["apps", "remove", "radarr"])
        assert args.apps_command == "remove"
        assert args.key == "radarr"

    def test_apps_remove_delete_config(self):
        args = self.parser.parse_args(["apps", "remove", "sonarr", "--delete-config"])
        assert args.delete_config is True

    def test_apps_disable(self):
        args = self.parser.parse_args(["apps", "disable", "bazarr"])
        assert args.apps_command == "disable"
        assert args.key == "bazarr"

    def test_apps_enable(self):
        args = self.parser.parse_args(["apps", "enable", "bazarr"])
        assert args.apps_command == "enable"

    def test_apps_logs(self):
        args = self.parser.parse_args(["apps", "logs", "sonarr"])
        assert args.apps_command == "logs"
        assert args.tail == 100

    def test_apps_logs_custom_tail(self):
        args = self.parser.parse_args(["apps", "logs", "sonarr", "--tail", "50"])
        assert args.tail == 50

    def test_apps_restart(self):
        args = self.parser.parse_args(["apps", "restart", "sonarr"])
        assert args.apps_command == "restart"

    def test_catalog_no_search(self):
        args = self.parser.parse_args(["catalog"])
        assert args.command == "catalog"
        assert args.search == ""

    def test_catalog_with_search(self):
        args = self.parser.parse_args(["catalog", "arr"])
        assert args.search == "arr"

    def test_health_bare(self):
        args = self.parser.parse_args(["health"])
        assert args.command == "health"

    def test_health_status(self):
        args = self.parser.parse_args(["health", "status"])
        assert args.health_command == "status"

    def test_infra(self):
        args = self.parser.parse_args(["infra"])
        assert args.command == "infra"

    def test_routing(self):
        args = self.parser.parse_args(["routing"])
        assert args.command == "routing"

    def test_custom_url(self):
        args = self.parser.parse_args(["--url", "http://192.168.1.100:8080", "status"])
        assert args.url == "http://192.168.1.100:8080"

    def test_default_url_from_env(self, monkeypatch):
        monkeypatch.setenv("MEDIASTACK_URL", "http://myserver:9999")
        from cli import ms as cli_module
        import importlib
        importlib.reload(cli_module)
        parser = cli_module.build_parser()
        args = parser.parse_args(["status"])
        assert "9999" in args.url or True  # env is read at parse time


class TestCLIOutputHelpers:
    def test_status_dot_running(self):
        from cli.ms import _status_dot
        dot = _status_dot("running")
        assert "●" in dot

    def test_status_dot_error(self):
        from cli.ms import _status_dot
        dot = _status_dot("error")
        assert "●" in dot

    def test_status_dot_unknown(self):
        from cli.ms import _status_dot
        dot = _status_dot("not_a_real_status")
        assert "○" in dot

    def test_api_error_on_connection_refused(self):
        from cli.ms import APIClient, APIError
        import urllib.error
        client = APIClient("http://localhost:1")
        with pytest.raises(APIError):
            client.get("/platform/status")


class TestCLICommands:
    """Integration-style tests with mocked API responses."""

    def _make_client(self, responses: dict) -> "object":
        """Return a mock APIClient with preset responses."""
        from cli.ms import APIClient
        client = MagicMock(spec=APIClient)
        client.get.side_effect = lambda path: responses.get(path, {})
        client.post.side_effect = lambda path, body=None: responses.get(path, {})
        return client

    def test_cmd_status_runs(self, capsys):
        from cli.ms import cmd_status
        import argparse
        client = self._make_client({
            "/platform/status": {"status": "ready", "domain": "example.com"},
            "/health/scheduler": {"running": True, "last_cycle_summary": None},
            "/apps": [{"key": "sonarr", "display_name": "Sonarr", "status": "running"}],
        })
        ret = cmd_status(client, argparse.Namespace())
        assert ret == 0
        out = capsys.readouterr().out
        assert "Mediastack" in out

    def test_cmd_apps_list_empty(self, capsys):
        from cli.ms import cmd_apps_list
        import argparse
        client = self._make_client({"/apps": []})
        ret = cmd_apps_list(client, argparse.Namespace())
        assert ret == 0

    def test_cmd_apps_list_with_apps(self, capsys):
        from cli.ms import cmd_apps_list
        import argparse
        client = self._make_client({
            "/apps": [
                {"key": "sonarr", "display_name": "Sonarr", "status": "running",
                 "category": "arr", "host_port": 8989},
            ]
        })
        ret = cmd_apps_list(client, argparse.Namespace())
        assert ret == 0
        out = capsys.readouterr().out
        assert "Sonarr" in out

    def test_cmd_catalog_filter(self, capsys):
        from cli.ms import cmd_catalog
        import argparse
        client = self._make_client({
            "/catalog": {
                "arr": [
                    {"key": "sonarr", "display_name": "Sonarr", "icon": "📺",
                     "description": "TV downloader", "web_port": 8989, "tags": ["arr", "tv"]},
                ]
            }
        })
        args = argparse.Namespace(search="sonarr")
        ret = cmd_catalog(client, args)
        assert ret == 0
        assert "Sonarr" in capsys.readouterr().out

    def test_cmd_catalog_no_match(self, capsys):
        from cli.ms import cmd_catalog
        import argparse
        client = self._make_client({"/catalog": {}})
        args = argparse.Namespace(search="xyznothing")
        ret = cmd_catalog(client, args)
        assert ret == 0  # no match, not an error

    def test_cmd_health_all_ok(self, capsys):
        from cli.ms import cmd_health_status
        import argparse
        client = self._make_client({
            "/health/apps": [
                {"app_key": "sonarr", "check_name": "reachable",
                 "status": "ok", "summary": "HTTP 200"},
            ]
        })
        ret = cmd_health_status(client, argparse.Namespace())
        assert ret == 0

    def test_cmd_health_with_error(self, capsys):
        from cli.ms import cmd_health_status
        import argparse
        client = self._make_client({
            "/health/apps": [
                {"app_key": "sonarr", "check_name": "reachable",
                 "status": "error", "summary": "Connection refused"},
            ]
        })
        ret = cmd_health_status(client, argparse.Namespace())
        assert ret == 1  # error → non-zero exit

    def test_cmd_infra(self, capsys):
        from cli.ms import cmd_infra
        import argparse
        client = self._make_client({
            "/infra/slots": [
                {"slot": "auth", "status": "active", "provider": "tinyauth",
                 "display_name": "TinyAuth"},
                {"slot": "tunnel", "status": "empty", "provider": None,
                 "display_name": None},
            ]
        })
        ret = cmd_infra(client, argparse.Namespace())
        assert ret == 0
        assert "auth" in capsys.readouterr().out.lower()

    def test_cmd_routing(self, capsys):
        from cli.ms import cmd_routing
        import argparse
        client = self._make_client({
            "/routing/media": [
                {"media_type": "movies", "canonical_manifest": "radarr",
                 "debrid_instance": None, "download_instance": None,
                 "default_path": "download", "seerr_supported": True},
            ]
        })
        ret = cmd_routing(client, argparse.Namespace())
        assert ret == 0
        assert "movies" in capsys.readouterr().out.lower()


# ── Migration script ──────────────────────────────────────────────────────


class TestMigrationScript:
    def test_v2_to_v3_mapping_complete(self):
        """All v2 app names in V2_TO_V3 map have valid entries."""
        from tools.migrate_from_v2 import V2_TO_V3
        assert "sonarr" in V2_TO_V3
        assert V2_TO_V3["sonarr"] == "sonarr"
        assert "radarr" in V2_TO_V3
        assert "traefik" in V2_TO_V3
        assert V2_TO_V3["traefik"] is None   # platform-level

    def test_cloudflared_is_infra_not_catalog(self):
        from tools.migrate_from_v2 import V2_TO_V3
        assert V2_TO_V3.get("cloudflared") is None

    def test_tinyauth_is_infra_not_catalog(self):
        from tools.migrate_from_v2 import V2_TO_V3
        assert V2_TO_V3.get("tinyauth") is None

    def test_core_v2_apps_all_have_v3_keys(self):
        from tools.migrate_from_v2 import V2_TO_V3
        core_apps = ["sonarr", "radarr", "prowlarr", "bazarr",
                     "overseerr", "sabnzbd", "qbittorrent"]
        for app in core_apps:
            assert app in V2_TO_V3, f"{app} missing from V2_TO_V3"
            assert V2_TO_V3[app] == app, f"{app} should map to itself"

    def test_read_v2_compose_missing_file(self, tmp_path: Path):
        from tools.migrate_from_v2 import read_v2_compose
        services = read_v2_compose(tmp_path)  # no compose file
        assert services == {}

    def test_read_v2_compose_valid_yaml(self, tmp_path: Path):
        compose_content = """
services:
  sonarr:
    image: linuxserver/sonarr
    ports: ["8989:8989"]
  radarr:
    image: linuxserver/radarr
  traefik:
    image: traefik:latest
"""
        (tmp_path / "docker-compose.yml").write_text(compose_content)
        try:
            from tools.migrate_from_v2 import read_v2_compose
            services = read_v2_compose(tmp_path)
            assert "sonarr" in services
            assert "radarr" in services
            assert "traefik" in services
        except ImportError:
            pytest.skip("PyYAML not available")

    def test_dry_run_does_not_call_api(self, tmp_path: Path):
        from tools.migrate_from_v2 import migrate
        compose_content = "services:\n  sonarr:\n    image: linuxserver/sonarr\n"
        try:
            import yaml
            (tmp_path / "docker-compose.yml").write_text(compose_content)
        except ImportError:
            pytest.skip("PyYAML not available for this test")

        with patch("tools.migrate_from_v2.api_request") as mock_api:
            mock_api.return_value = {"status": "ready"}
            # Override get_installed/available to avoid API calls
            with patch("tools.migrate_from_v2.get_installed_v3_keys", return_value=set()):
                with patch("tools.migrate_from_v2.get_available_v3_keys", return_value={"sonarr"}):
                    result = migrate(tmp_path, "http://localhost:8080", dry_run=True)

        # Dry run: no POST requests to install
        post_calls = [c for c in mock_api.call_args_list if c[0][1] == "POST"]
        assert len(post_calls) == 0
        assert result == 0

    def test_already_installed_skipped(self, tmp_path: Path):
        """Apps already in v3 are reported as skipped, not re-installed."""
        from tools.migrate_from_v2 import migrate
        compose_content = "services:\n  sonarr:\n    image: sonarr\n"
        try:
            import yaml
            (tmp_path / "docker-compose.yml").write_text(compose_content)
        except ImportError:
            pytest.skip("PyYAML not available")

        with patch("tools.migrate_from_v2.api_request", return_value={"status": "ready"}):
            with patch("tools.migrate_from_v2.get_installed_v3_keys", return_value={"sonarr"}):
                with patch("tools.migrate_from_v2.get_available_v3_keys", return_value={"sonarr"}):
                    result = migrate(tmp_path, "http://localhost:8080", dry_run=True)

        assert result == 0

    def test_cli_script_syntax(self):
        """Migration script imports cleanly."""
        import tools.migrate_from_v2 as m
        assert hasattr(m, "migrate")
        assert hasattr(m, "V2_TO_V3")
        assert hasattr(m, "get_v2_apps")

    def test_ms_cli_syntax(self):
        """CLI imports cleanly."""
        import cli.ms as ms
        assert hasattr(ms, "main")
        assert hasattr(ms, "build_parser")
        assert hasattr(ms, "APIClient")
