"""tests/test_session_d.py

Tests for Session D deployment fixes:
  - static_dir config points to backend/static (not frontend/dist)
  - SPA fallback registered AFTER all API routers
  - _broadcast_step_to_db called in real-time via ExecutionResult.add()
  - requirements.txt contains expected packages
  - deploy.sh and Makefile exist and are executable
  - Integration test runner is importable and parses args
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch, MagicMock
from unittest.mock import MagicMock, patch

import pytest


# ── Fix 1: static_dir config ───────────────────────────────────────────────


class TestStaticDirConfig:
    def test_static_dir_default_is_backend_static(self):
        """Default static_dir must point to the Vite build output."""
        from backend.core.config import config
        assert config.static_dir.name == "static", \
            f"static_dir should be 'backend/static', got: {config.static_dir}"
        assert "backend" in str(config.static_dir), \
            f"static_dir should be under 'backend/', got: {config.static_dir}"

    def test_static_dir_contains_built_assets(self):
        """The configured static_dir should contain the built frontend."""
        from backend.core.config import config
        assert config.static_dir.exists(), \
            f"static_dir {config.static_dir} does not exist. Run: cd frontend && npm run build"
        index = config.static_dir / "index.html"
        assert index.exists(), f"index.html not found in {config.static_dir}"

    def test_static_dir_configurable_via_env(self, monkeypatch, tmp_path):
        """MS_STATIC_DIR env var overrides the default.

        Step 1.5 Phase 1b: this test was order-dependent for two
        compounding reasons:

          1. It reloaded `backend.core.config` after setting
             MS_STATIC_DIR — the reload re-ran `config = Config.from_env()`
             at module level, baking the tmp_path INTO the global
             singleton that subsequent tests read. (Reload removed.)
          2. Even without reload, if this is the FIRST test in the
             file's run, `from backend.core.config import Config`
             triggers the module's first load while MS_STATIC_DIR is
             set — so the global `config = Config.from_env()` line at
             module level captures the polluted env. Subsequent
             `from backend.core.config import config` calls return
             that polluted singleton.

        Fix: pre-import `config` BEFORE setting MS_STATIC_DIR, so the
        global singleton captures the un-patched env. Then call
        `Config.from_env()` locally to test the override path.
        """
        # IMPORTANT: import BEFORE monkeypatch.setenv so the module-level
        # `config = Config.from_env()` baked into the global runs against
        # the un-modified env. (No-op on second-and-later runs because
        # Python caches the module.)
        from backend.core.config import config as _force_initial_load  # noqa: F401

        monkeypatch.setenv("MS_STATIC_DIR", str(tmp_path))
        from backend.core.config import Config
        cfg = Config.from_env()
        assert cfg.static_dir == tmp_path

    def test_not_frontend_dist(self):
        """Must NOT default to frontend/dist — that directory doesn't exist after build."""
        from backend.core.config import config
        assert "frontend/dist" not in str(config.static_dir), \
            "static_dir must not be frontend/dist — Vite builds to backend/static"


# ── Fix 2: SPA route order ─────────────────────────────────────────────────


class TestSPARouteOrder:
    """Verify API routes are registered before the SPA catch-all.

    Tests check the route registry directly — no need to start a server.
    The critical invariant: /{full_path:path} must appear AFTER all /api/* routes.
    """

    def _get_app_routes(self):
        from backend.api.main import app
        from fastapi.routing import APIRoute
        return [r for r in app.routes if isinstance(r, APIRoute)]

    def test_api_apps_route_exists(self):
        routes = self._get_app_routes()
        paths = [r.path for r in routes]
        assert any(p.startswith("/api/apps") for p in paths), \
            f"No /api/apps routes found. Paths: {[p for p in paths if 'api' in p]}"

    def test_api_infra_route_exists(self):
        routes = self._get_app_routes()
        paths = [r.path for r in routes]
        assert any(p.startswith("/api/infra") for p in paths), \
            f"No /api/infra routes found."

    def test_install_progress_route_exists(self):
        routes = self._get_app_routes()
        paths = [r.path for r in routes]
        assert any("install/progress" in p for p in paths), \
            f"install/progress route not found. Paths: {paths}"

    def test_spa_catchall_after_api_routes(self):
        """/{full_path:path} must come after all /api/* routes in the route list."""
        routes = self._get_app_routes()
        catchall_idx = None
        for i, r in enumerate(routes):
            if r.path == "/{full_path:path}":
                catchall_idx = i
                break
        if catchall_idx is None:
            return  # SPA not mounted (static dir missing) — OK in CI
        api_indices = [i for i, r in enumerate(routes) if r.path.startswith("/api/")]
        if not api_indices:
            return
        last_api = max(api_indices)
        assert catchall_idx > last_api, (
            f"SPA catch-all at index {catchall_idx} is BEFORE "
            f"API route at index {last_api} ({routes[last_api].path}). "
            f"GET requests to that API route would be served index.html instead of JSON."
        )

    def test_api_ping_route_registered(self):
        routes = self._get_app_routes()
        paths = [r.path for r in routes]
        assert "/api/ping" in paths, f"/api/ping not registered. Paths: {paths}"


# ── Fix 3: real-time install progress ─────────────────────────────────────


class TestRealTimeInstallProgress:
    def test_execution_result_add_broadcasts_immediately(self, tmp_path):
        """ExecutionResult.add() writes step to DB synchronously."""
        from backend.core.state import StateDB, init_db
        db_path = tmp_path / "test.db"
        init_db(db_path)
        import backend.core.state as sm
        sm.configure(db_path)

        from backend.manifests.executor import ExecutionResult, StepLog

        result = ExecutionResult(ok=True, app_key="sonarr", operation="install")
        result.add("validate", "ok", "Platform ready.")

        # Step should already be in DB — not just in memory
        with StateDB() as db:
            steps = db.get_op_steps("sonarr")

        assert len(steps) == 1, f"Expected 1 step in DB, got {len(steps)}"
        assert steps[0]["step"] == "validate"
        assert steps[0]["status"] == "ok"
        assert steps[0]["message"] == "Platform ready."

    def test_multiple_steps_all_broadcast(self, tmp_path):
        """Multiple add() calls all persist to DB."""
        from backend.core.state import StateDB, init_db
        db_path = tmp_path / "test.db"
        init_db(db_path)
        import backend.core.state as sm
        sm.configure(db_path)

        from backend.manifests.executor import ExecutionResult

        result = ExecutionResult(ok=True, app_key="radarr", operation="install")
        for step_name in ["validate", "deps", "config_dir", "fragment", "deploy"]:
            result.add(step_name, "ok", f"{step_name} done.")

        with StateDB() as db:
            steps = db.get_op_steps("radarr")

        assert len(steps) == 5, f"Expected 5 steps in DB, got {len(steps)}"
        step_names = [s["step"] for s in steps]
        assert step_names == ["validate", "deps", "config_dir", "fragment", "deploy"]

    def test_error_step_broadcast_with_detail(self, tmp_path):
        """Error steps with detail are persisted correctly."""
        from backend.core.state import StateDB, init_db
        db_path = tmp_path / "test.db"
        init_db(db_path)
        import backend.core.state as sm
        sm.configure(db_path)

        from backend.manifests.executor import ExecutionResult

        result = ExecutionResult(ok=True, app_key="prowlarr", operation="install")
        result.fail("deploy", "Container failed to start.", "Exit code 1: port in use.")

        with StateDB() as db:
            steps = db.get_op_steps("prowlarr")

        assert len(steps) == 1
        assert steps[0]["status"] == "error"
        assert steps[0]["detail"] == "Exit code 1: port in use."

    def test_progress_api_reflects_realtime_steps(self):
        """GET /api/apps/{key}/install/progress returns steps written by add().

        Steps are written inside the TestClient context so the lifespan DB
        init doesn't override our test writes.
        """
        from backend.core.state import StateDB
        from backend.api.main import app
        from fastapi.testclient import TestClient

        with TestClient(app, base_url="http://localhost") as client:
            # Write steps after lifespan DB init so they land in the live DB
            with StateDB() as db:
                db.clear_op_steps("bazarr")
                db.write_op_step("bazarr", "validate", "ok", "Platform ready.")
                db.write_op_step("bazarr", "deps", "ok", "Dependencies satisfied.")

            r = client.get("/api/apps/bazarr/install/progress")

        assert r.status_code == 200
        data = r.json()
        assert data["done"] is False
        assert len(data["steps"]) == 2, \
            f"Expected 2 steps, got {len(data['steps'])}: {data['steps']}"
        assert data["steps"][0]["step"] == "validate"
        assert data["steps"][1]["step"] == "deps"


# ── Fix 4: requirements.txt ────────────────────────────────────────────────


class TestRequirements:
    REQ_PATH = Path("requirements.txt")
    DEV_REQ_PATH = Path("requirements-dev.txt")

    def test_requirements_txt_exists(self):
        assert self.REQ_PATH.exists(), "requirements.txt missing"

    def test_requirements_dev_txt_exists(self):
        assert self.DEV_REQ_PATH.exists(), "requirements-dev.txt missing"

    def test_requirements_has_core_packages(self):
        content = self.REQ_PATH.read_text()
        for pkg in ["fastapi", "uvicorn", "httpx", "docker", "pyyaml", "pydantic"]:
            assert pkg in content.lower(), f"'{pkg}' not in requirements.txt"

    def test_requirements_dev_includes_base(self):
        content = self.DEV_REQ_PATH.read_text()
        assert "-r requirements.txt" in content

    def test_requirements_dev_has_test_packages(self):
        content = self.DEV_REQ_PATH.read_text()
        assert "pytest" in content


# ── Fix 5: deploy tooling ─────────────────────────────────────────────────


class TestDeployTooling:
    def test_deploy_sh_exists(self):
        assert Path("deploy.sh").exists(), "deploy.sh missing"

    def test_deploy_sh_is_executable(self):
        mode = Path("deploy.sh").stat().st_mode
        assert mode & stat.S_IXUSR, "deploy.sh is not executable (run: chmod +x deploy.sh)"

    def test_makefile_exists(self):
        assert Path("Makefile").exists(), "Makefile missing"

    def test_makefile_has_key_targets(self):
        content = Path("Makefile").read_text()
        for target in ["dev", "build", "test", "deploy", "install"]:
            assert target in content, f"Makefile missing '{target}' target"

    def test_ms_executable_exists(self):
        assert Path("ms").exists(), "ms CLI wrapper missing"

    def test_ms_is_executable(self):
        mode = Path("ms").stat().st_mode
        assert mode & stat.S_IXUSR, "ms is not executable"

    def test_migration_script_exists(self):
        assert Path("tools/migrate_from_v2.py").exists()

    def test_integration_runner_exists(self):
        assert Path("tests/integration/run.py").exists()

    def test_integration_runner_importable(self):
        import tests.integration.run as runner
        assert hasattr(runner, "main")
        assert hasattr(runner, "suite_smoke")
        assert hasattr(runner, "SUITES")
        assert len(runner.SUITES) >= 5


# ── Startup validation ─────────────────────────────────────────────────────


class TestStartupValidation:
    def test_all_api_modules_import_cleanly(self):
        """All API modules must be importable without side effects."""
        modules = [
            "backend.api.apps",
            "backend.api.catalog",
            "backend.api.health",
            "backend.api.infra",
            "backend.api.models",
            "backend.api.platform",
            "backend.api.registry",
            "backend.api.routing",
            "backend.api.settings",
            "backend.api.storage",
        ]
        import importlib
        imported = []
        for mod in modules:
            try:
                m = importlib.import_module(mod)
                assert m is not None, f"{mod} imported as None"
                imported.append(mod)
            except ImportError as e:
                pytest.fail(f"Cannot import {mod}: {e}")
        assert len(imported) == len(modules), f"Only {len(imported)}/{len(modules)} modules imported"

    def test_schema_sql_idempotent(self, tmp_path):
        """init_db() can be called twice without error (idempotent schema)."""
        from backend.core.state import init_db
        import sqlite3
        db_path = tmp_path / "test.db"
        init_db(db_path)
        init_db(db_path)  # second call must not raise
        # Assert: database file exists and has the platform table
        assert db_path.exists(), "DB file must exist after init_db"
        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "platform" in tables, "platform table must exist after init_db"
        assert "apps" in tables, "apps table must exist after init_db"
        assert "health_checks" in tables, "health_checks table must exist after init_db"

    def test_config_data_dir_env_override(self, monkeypatch, tmp_path):
        """MS_DATA_DIR env var sets the data directory."""
        monkeypatch.setenv("MS_DATA_DIR", str(tmp_path))
        from backend.core.config import Config
        cfg = Config.from_env()
        assert cfg.data_dir == tmp_path

    def test_operation_steps_table_created(self, tmp_path):
        """operation_steps table exists after init_db."""
        from backend.core.state import StateDB, init_db
        db_path = tmp_path / "test.db"
        init_db(db_path)
        import backend.core.state as sm
        sm.configure(db_path)
        with StateDB() as db:
            tables = db._c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        table_names = [t["name"] for t in tables]
        assert "operation_steps" in table_names, \
            f"operation_steps table missing. Tables: {table_names}"
        assert "manifest_registry" in table_names, \
            f"manifest_registry table missing. Tables: {table_names}"
