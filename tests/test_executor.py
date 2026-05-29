"""tests/test_executor.py

Tests for the app install/remove/replace executor and the apps API routes.

Docker calls are mocked — these tests verify the orchestration logic,
state DB transitions, and API contract, not actual container behaviour.
"""
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.core import state as state_mod
from backend.core.state import StateDB, init_db
from backend.manifests.executor import (
    ExecutionResult,
    StepLog,
    _clean_compose_output,
    _expand_path,
    install_app,
    remove_app,
    replace_app,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "state.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def ready_platform(db: Path):
    """Mark platform as ready with test paths."""
    with StateDB() as s:
        s.update_platform(
            status="ready",
            domain="example.com",
            config_root="/tmp/test_config",
            media_root="/tmp/test_media",
            puid=1000,
            pgid=1000,
            timezone="UTC",
            network_name="mediastack",
            cert_resolver="letsencrypt",
        )
    return db


@pytest.fixture
def api_client(ready_platform: Path):
    state_mod.configure(ready_platform)
    from backend.api.main import app
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def real_install_env(db: Path, tmp_path: Path):
    """Behavioural-mock-free install fixture (Core Rule 4.12 / ADR 0002).

    Yields a dict of real `tmp_path`-rooted paths and patches the
    `backend.core.config.config.data_dir` singleton so `compose_dir`
    (= data_dir/compose) resolves under the test's tmp dir. Tests using
    this fixture can drop `@patch("backend.manifests.executor.write_fragment")`
    et al. and assert on the actual filesystem effect of `install_app()`.
    """
    from backend.core.config import config as _cfg
    config_root = tmp_path / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    compose_dir = data_dir / "compose"
    compose_dir.mkdir(parents=True, exist_ok=True)

    with StateDB() as s:
        s.update_platform(
            status="ready",
            domain="example.com",
            config_root=str(config_root),
            media_root=str(media_root),
            puid=1000,
            pgid=1000,
            timezone="UTC",
            network_name="mediastack",
            cert_resolver="letsencrypt",
        )

    # Config is a frozen dataclass — bypass the frozen guard via
    # object.__setattr__. This is the standard pattern for swapping out
    # singleton state in tests.
    original_data_dir = _cfg.data_dir
    object.__setattr__(_cfg, "data_dir", data_dir)
    try:
        yield {
            "tmp": tmp_path,
            "db": db,
            "config_root": config_root,
            "media_root": media_root,
            "data_dir": data_dir,
            "compose_dir": compose_dir,
        }
    finally:
        object.__setattr__(_cfg, "data_dir", original_data_dir)


def _mock_compose_success(*args, **kwargs):
    m = MagicMock()
    m.returncode = 0
    m.stdout = "Container started"
    m.stderr = ""
    return m


def _mock_container_running(name):
    c = MagicMock()
    c.status = "running"
    c.health = "healthy"
    c.name = name
    return c


# ── ExecutionResult ───────────────────────────────────────────────────────


class TestExecutionResult:
    def test_starts_ok(self):
        r = ExecutionResult(ok=True, app_key="sonarr", operation="install")
        assert r.ok
        assert r.steps == []

    def test_add_ok_step(self):
        r = ExecutionResult(ok=True, app_key="sonarr", operation="install")
        r.add("validate", "ok", "All good")
        assert len(r.steps) == 1
        assert r.ok  # ok steps don't change result

    def test_fail_sets_error(self):
        r = ExecutionResult(ok=True, app_key="sonarr", operation="install")
        r.fail("validate", "Platform not ready.")
        assert not r.ok
        assert r.error == "Platform not ready."

    def test_fail_only_sets_first_error(self):
        r = ExecutionResult(ok=True, app_key="sonarr", operation="install")
        r.fail("step1", "First error")
        r.fail("step2", "Second error")
        assert r.error == "First error"


# ── install_app ───────────────────────────────────────────────────────────


class TestInstallApp:
    def test_fails_if_platform_not_ready(self, db: Path):
        # Platform is 'pending' by default
        result = install_app("sonarr")
        assert not result.ok
        assert "Platform" in result.error

    def test_fails_if_manifest_not_found(self, ready_platform: Path):
        result = install_app("nonexistent_app_xyz")
        assert not result.ok
        assert "nonexistent" in result.error

    @patch("backend.manifests.executor.docker_client.get_container",
           return_value=MagicMock(status="running", health="healthy"))
    def test_fails_if_already_running_and_healthy(self, mock_container, ready_platform: Path):
        """Retry is blocked only when container is actually healthy (not just DB status)."""
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr", status="running")
        result = install_app("sonarr")
        assert result.ok, "Should succeed (return healthy status) not fail"
        assert "already running" in (result.steps[0].message if result.steps else "")

    def test_successful_install(self, real_install_env) -> None:
        """A successful install must produce all the on-disk and DB effects
        a successful install is supposed to produce — not just return ok=True
        with mocked internals.

        Step 2.2.d rewrite per ADR 0002: drops @patch on `write_fragment`,
        `write_compose_file`, `httpx.get`, and `pathlib.Path.mkdir` —
        the real functions run against a tmp_path compose dir. Boundary
        mocks (subprocess.run, docker_client.*) stay because docker isn't
        running in CI.
        """
        env = real_install_env
        with patch("backend.manifests.executor.subprocess.run",
                   side_effect=_mock_compose_success), \
             patch("backend.manifests.executor.docker_client.ports_in_use",
                   return_value={}), \
             patch("backend.manifests.executor.docker_client.get_container",
                   side_effect=_mock_container_running), \
             patch("backend.manifests.executor.httpx.get") as mock_http:
            mock_http.return_value = MagicMock(status_code=200)
            result = install_app("sonarr")

        assert result.ok, f"install failed: {result.error}\nSteps: {result.steps}"

        # Behavioural assertions — what install ACTUALLY does, not what mocks were called with
        frag = env["compose_dir"] / "sonarr.yaml"
        assert frag.exists(), "install must write the compose fragment to disk"
        frag_text = frag.read_text()
        assert "image:" in frag_text, "fragment should be valid compose YAML"
        assert "sonarr" in frag_text.lower(), "fragment should reference the app"

        with StateDB() as s:
            app = s.get_app("sonarr")
        assert app is not None, "install must register the app in DB"
        assert app.status == "running", \
            f"installed app should be 'running', got '{app.status}'"
        assert app.config_path == str(env["config_root"] / "sonarr"), \
            "DB config_path should match the platform-derived config dir"

        # The per-app config dir must actually exist
        assert (env["config_root"] / "sonarr").is_dir(), \
            "install must create the per-app config directory"

    def test_fails_on_port_conflict(self, real_install_env) -> None:
        """Behavioural rewrite of the port-conflict guard test.

        Step 2.2.d per ADR 0002: drops mocks on `write_fragment` /
        `write_compose_file` / `pathlib.Path.mkdir`. Asserts that the
        DB does NOT carry a stale 'running' record AND that no compose
        fragment was written when the port-conflict guard triggers — the
        original test only checked `result.ok` was False, which a
        no-op'd write_fragment would still satisfy.
        """
        env = real_install_env
        with patch("backend.manifests.executor.subprocess.run",
                   side_effect=_mock_compose_success), \
             patch("backend.manifests.executor.docker_client.ports_in_use",
                   return_value={8989: "other_container"}):
            result = install_app("sonarr")

        assert not result.ok
        assert "8989" in result.error or "port" in result.error.lower()

        # Behavioural assertions — port-conflict must abort BEFORE any side effects
        frag = env["compose_dir"] / "sonarr.yaml"
        assert not frag.exists(), \
            "port-conflict abort must NOT have written a compose fragment"
        with StateDB() as s:
            app = s.get_app("sonarr")
        assert app is None or app.status != "running", \
            "port-conflict abort must NOT have left a 'running' DB record"


# ── remove_app ────────────────────────────────────────────────────────────


class TestRemoveApp:
    def test_fails_if_not_installed(self, ready_platform: Path):
        result = remove_app("sonarr")
        assert not result.ok
        assert "not installed" in result.error

    @patch("backend.manifests.executor.subprocess.run", side_effect=_mock_compose_success)
    def test_successful_remove_retains_config(
        self, mock_run, ready_platform: Path, tmp_path: Path
    ):
        cfg_path = tmp_path / "sonarr"
        cfg_path.mkdir()

        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr", status="running",
                         config_path=str(cfg_path))

        with patch("backend.manifests.executor.remove_fragment"):
            with patch("backend.core.compose.config") as mock_cfg:
                mock_cfg.compose_dir = tmp_path
                result = remove_app("sonarr", delete_config=False)

        assert result.ok
        assert cfg_path.exists()  # retained
        config_step = next((s for s in result.steps if s.name == "config"), None)
        assert config_step is not None
        assert config_step.status in ("skipped", "ok")

    @patch("backend.manifests.executor.subprocess.run", side_effect=_mock_compose_success)
    def test_successful_remove_deletes_config(
        self, mock_run, ready_platform: Path, tmp_path: Path
    ):
        cfg_path = tmp_path / "sonarr_del"
        cfg_path.mkdir()

        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr", status="running",
                         config_path=str(cfg_path))

        with patch("backend.manifests.executor.remove_fragment"):
            with patch("backend.core.compose.config") as mock_cfg:
                mock_cfg.compose_dir = tmp_path
                result = remove_app("sonarr", delete_config=True)

        assert result.ok
        assert not cfg_path.exists()  # deleted

    @patch("backend.manifests.executor.subprocess.run", side_effect=_mock_compose_success)
    def test_remove_cleans_state_db(
        self, mock_run, ready_platform: Path, tmp_path: Path
    ):
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr", status="running")

        with patch("backend.manifests.executor.remove_fragment"):
            with patch("backend.core.compose.config") as mock_cfg:
                mock_cfg.compose_dir = tmp_path
                remove_app("sonarr")

        with StateDB() as s:
            assert s.get_app("sonarr") is None


# ── Operations audit log ──────────────────────────────────────────────────


class TestOperationsLog:
    @patch("backend.manifests.executor.subprocess.run", side_effect=_mock_compose_success)
    @patch("backend.manifests.executor.docker_client.ports_in_use",
           return_value={8989: "conflict"})
    def test_failed_install_logged(self, mock_ports, mock_run, ready_platform: Path):
        # Use a real manifest key but force a port conflict so install fails after logging
        with patch("pathlib.Path.mkdir"):
            install_app("sonarr")
        with StateDB() as s:
            ops = s.get_recent_operations(limit=10)
        install_ops = [o for o in ops if o.operation == "install"
                       and o.subject_key == "sonarr"]
        assert len(install_ops) == 1
        assert install_ops[0].status == "failed"


# ── Apps API routes ───────────────────────────────────────────────────────


class TestAppsAPI:
    @pytest.fixture(autouse=True)
    def mock_docker(self):
        """Mock Docker client for all API tests — no Docker socket needed."""
        with patch("backend.api.apps.docker_client.get_container", return_value=None):
            with patch("backend.core.docker_client._connect", return_value=MagicMock()):
                yield

    def test_list_apps_empty(self, api_client: TestClient, ready_platform: Path):
        r = api_client.get("/api/apps")
        assert r.status_code == 200
        # May have apps from other tests sharing the DB — just verify it returns a list
        assert isinstance(r.json(), list)

    def test_get_app_not_found(self, api_client: TestClient, ready_platform: Path):
        r = api_client.get("/api/apps/definitely_not_installed_xyz_12345")
        assert r.status_code == 404

    def test_get_app_installed(self, api_client: TestClient, ready_platform: Path):
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr", status="running")
        with patch("backend.api.apps.docker_client.get_container", return_value=None):
            r = api_client.get("/api/apps/sonarr")
        assert r.status_code == 200
        data = r.json()
        assert data["key"] == "sonarr"
        assert data["status"] == "running"

    def test_list_apps_shows_installed(self, api_client: TestClient, ready_platform: Path):
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr")
            s.upsert_app("radarr", display_name="Radarr", category="arr",
                         image="img", container_name="radarr")
        with patch("backend.api.apps.docker_client.get_container", return_value=None):
            r = api_client.get("/api/apps")
        assert r.status_code == 200
        keys = [a["key"] for a in r.json()]
        assert "sonarr" in keys
        assert "radarr" in keys

    def test_install_endpoint_returns_steps(self, api_client: TestClient, ready_platform: Path):
        with patch("backend.manifests.executor.install_app") as mock_install:
            mock_result = MagicMock()
            mock_result.ok = False
            mock_result.app_key = "sonarr"
            mock_result.operation = "install"
            mock_result.steps = [
                StepLog("validate", "error", "Platform not ready.", "")
            ]
            mock_result.error = "Platform not ready."
            mock_install.return_value = mock_result
            r = api_client.post("/api/apps/sonarr/install", json={})
        assert r.status_code == 200
        data = r.json()
        # New async response: returns installing=True immediately
        assert data["installing"] is True
        assert data["key"] == "sonarr"

    def test_remove_endpoint(self, api_client: TestClient, ready_platform: Path):
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr")
        with patch("backend.api.apps.remove_app") as mock_remove:
            mock_result = ExecutionResult(ok=True, app_key="sonarr", operation="remove")
            mock_result.add("state", "ok", "Removed.")
            mock_remove.return_value = mock_result
            r = api_client.delete("/api/apps/sonarr")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_restart_not_found(self, api_client: TestClient):
        # App not in DB → 404
        with patch("backend.api.apps.StateDB") as mock_db_cls:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.get_app.return_value = None
            mock_db_cls.return_value = mock_db
            r = api_client.post("/api/apps/sonarr/restart")
        assert r.status_code == 404

    def test_logs_not_found(self, api_client: TestClient):
        # App not in DB → 404
        with patch("backend.api.apps.StateDB") as mock_db_cls:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.get_app.return_value = None
            mock_db_cls.return_value = mock_db
            r = api_client.get("/api/apps/sonarr/logs")
        assert r.status_code == 404


# ── Helper functions ──────────────────────────────────────────────────────


class TestHelpers:
    def test_clean_compose_output_strips_pull_noise(self):
        raw = "Pulling sonarr...\nPull complete\nError response from daemon: conflict"
        cleaned = _clean_compose_output(raw)
        assert "Error response" in cleaned
        assert "Pulling" not in cleaned
        assert "Pull complete" not in cleaned

    def test_clean_compose_output_fallback(self):
        raw = "some normal output"
        assert _clean_compose_output(raw) == "some normal output"

    def test_expand_path_replaces_config_root(self):
        platform = MagicMock()
        platform.config_root = "/srv/mediastack/config"
        platform.media_root = "/mnt/media"
        result = _expand_path("{config_root}/sonarr", platform)
        assert result == "/srv/mediastack/config/sonarr"

    def test_expand_path_replaces_media_root(self):
        platform = MagicMock()
        platform.config_root = "/config"
        platform.media_root = "/mnt/media"
        result = _expand_path("{media_root}/movies", platform)
        assert result == "/mnt/media/movies"
