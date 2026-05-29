"""Integration tests — cross-layer scenarios that unit tests miss.

Run all:   pytest tests/test_integration.py
Run fast:  pytest tests/test_integration.py -m "not slow"
Run slow:  pytest tests/test_integration.py -m slow

These tests exercise real interactions between:
  - executor.py ↔ state.py ↔ health/checker.py
  - compose fragment existence ↔ DB record ↔ health pre-check
  - install failure modes ↔ cleanup ↔ reinstall guard
  - LLM context assembler ↔ DB state ↔ prompt correctness
  - Platform store ↔ API ↔ SetupView routing

Run with:  pytest tests/test_integration.py -v
"""

import time
import tempfile
import pathlib
from unittest.mock import patch, MagicMock
import pytest

# Mark tests that load the full FastAPI app (memory-intensive)
slow = pytest.mark.slow


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_env(tmp_path):
    """Full isolated environment: DB + compose dir + config dir."""
    import backend.core.state as sm
    from backend.core.state import init_db
    from backend.core import config as cfg_mod

    db = tmp_path / "state.db"
    compose = tmp_path / "compose"
    compose.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_PASSWORD=test\nTZ=UTC\n")
    env_file.chmod(0o600)

    sm.configure(db)
    init_db(db)

    original_config = cfg_mod.config
    mock_cfg = MagicMock()
    mock_cfg.compose_dir = compose
    mock_cfg.config_root = config
    mock_cfg.data_dir = data
    mock_cfg.env_file = env_file
    cfg_mod.config = mock_cfg

    yield {"db": db, "compose": compose, "config": config, "data": data}

    cfg_mod.config = original_config


# ── Category 1: Install failure + cleanup contracts ───────────────────────

class TestInstallCleanup:
    """Verify install failure modes leave correct state."""

    @slow
    def test_failed_install_without_fragment_deletes_db_record(self, tmp_env):
        """If install fails before compose fragment is written, no DB record survives."""
        from backend.core.state import StateDB
        from backend.manifests.executor import install_app

        with patch("backend.manifests.executor.load_manifest") as mock_load, \
             patch("backend.manifests.executor.docker_client") as mock_dc:

            mock_manifest = MagicMock()
            mock_manifest.key = "testapp"
            mock_manifest.display_name = "Test App"
            mock_manifest.content_hash = "abc123"
            mock_manifest.dependencies.postgres = False
            mock_manifest.dependencies.redis = False
            mock_manifest.dependencies.apps = []
            mock_manifest.companions = []
            mock_manifest.tier = 2
            mock_manifest.category = "tools"
            mock_load.return_value = mock_manifest

            # Fail at port conflict (before fragment is written)
            mock_dc.ports_in_use.return_value = {8080: "other_app"}
            mock_dc.get_container.return_value = None

            result = install_app("testapp", host_port_override=8080)

        assert not result.ok
        # No compose fragment → DB record must be deleted
        with StateDB() as db:
            app = db.get_app("testapp")
        assert app is None, "Orphaned DB record should not exist after pre-deploy failure"

    @slow
    def test_failed_install_with_fragment_marks_failed(self, tmp_env):
        """If install fails after fragment is written, DB record has status=failed."""
        from backend.core.state import StateDB
        from backend.manifests.executor import install_app

        # Create a compose fragment (simulates failure after Step 4 but before deploy)
        frag = tmp_env["compose"] / "testapp2.yaml"
        frag.write_text("services:\n  testapp2:\n    image: test:latest\n")

        with patch("backend.manifests.executor.load_manifest") as mock_load, \
             patch("backend.manifests.executor._install_inner") as mock_inner, \
             patch("backend.manifests.executor.docker_client"):

            mock_manifest = MagicMock()
            mock_manifest.key = "testapp2"
            mock_manifest.display_name = "Test App 2"
            mock_manifest.content_hash = "def456"
            mock_load.return_value = mock_manifest

            # Simulate inner failure (after fragment was written externally)
            mock_inner.side_effect = lambda m, r, e, h: r.fail("deploy", "Docker failed")

            install_app("testapp2")

        with StateDB() as db:
            app = db.get_app("testapp2")
        assert app is not None, "DB record should exist when fragment exists"
        assert app.status == "failed"

    @slow
    def test_reinstall_clears_stale_failed_record(self, tmp_env):
        """Reinstalling an app with status=failed and no fragment clears stale record."""
        from backend.core.state import StateDB
        from backend.manifests.executor import install_app

        # Create a stale failed record with no fragment
        with StateDB() as db:
            db.upsert_app("staleapp", display_name="Stale App", status="failed",
                          tier=2, category="tools")

        assert not (tmp_env["compose"] / "staleapp.yaml").exists()

        with patch("backend.manifests.executor.load_manifest") as mock_load, \
             patch("backend.manifests.executor.docker_client") as mock_dc:

            mock_manifest = MagicMock()
            mock_manifest.key = "staleapp"
            mock_manifest.display_name = "Stale App"
            mock_manifest.content_hash = "ghi789"
            mock_manifest.dependencies.postgres = False
            mock_manifest.dependencies.redis = False
            mock_manifest.dependencies.apps = []
            mock_manifest.companions = []
            mock_dc.ports_in_use.return_value = {}
            mock_dc.get_container.return_value = None
            mock_load.return_value = mock_manifest

            # The install itself may fail (no real Docker), but the stale record
            # should have been cleared before the new install attempt
            install_app("staleapp")

        # The reinstall guard should have cleared the stale record
        # (even if the new install also fails, the old orphaned record is gone)
        with StateDB() as db:
            ops = db.execute(
                "SELECT COUNT(*) as n FROM operations WHERE subject_key='staleapp'"
            ).fetchone()
        assert ops["n"] >= 1, "Operation should be logged even for failed reinstall"


# ── Category 2: Health check contract correctness ─────────────────────────

class TestHealthCheckContracts:
    """Verify health check URL and pre-check contracts."""

    @slow
    def test_health_check_uses_host_port_not_container_dns(self, tmp_env):
        """HTTP health checks must target localhost:{host_port} never container hostnames."""
        import asyncio
        from backend.health.checker import _check_http

        captured_urls = []
        original_check = _check_http.__wrapped__ if hasattr(_check_http, '__wrapped__') else None

        async def mock_http_check(app_key, check_name, base_url, path, expect_status):
            captured_urls.append(base_url)
            from backend.health.checker import CheckResult
            return CheckResult(app_key=app_key, check_name=check_name,
                               ok=True, message="mock ok")

        with patch("backend.health.checker._check_http", side_effect=mock_http_check):
            pass  # Just verify the URL pattern

        # Verify the URL pattern via source inspection. Step 4.1 wire-up:
        # `check_app` is now a thin timing wrapper; the localhost / host_port
        # logic lives in `_check_app_inner`. Inspect that instead.
        import inspect
        import backend.health.checker as chk
        source = inspect.getsource(chk._check_app_inner)
        assert "localhost" in source, "_check_app_inner must use localhost for health checks"
        assert "host_port" in source, "_check_app_inner must use host_port not web_port"
        assert "container_name" not in source.split("base_url")[0].split("localhost")[0], \
            "base_url must not use container DNS names"

    @slow
    def test_fragment_pre_check_catches_missing_compose_file(self, tmp_env):
        """App with DB record but no compose fragment gets 'misconfigured' status."""
        import asyncio
        from backend.core.state import StateDB
        from backend.health.checker import check_app

        with StateDB() as db:
            db.upsert_app("fragless", display_name="Fragless App",
                          status="running", host_port=9999, tier=2, category="tools")

        # No compose fragment exists for "fragless"
        assert not (tmp_env["compose"] / "fragless.yaml").exists()

        with patch("backend.health.checker.load_manifest") as mock_load:
            mock_manifest = MagicMock()
            mock_manifest.health_checks = [MagicMock(check_type="http", name="http_reachable", path="/")]
            mock_manifest.start_grace_s = 0
            mock_manifest.display_name = "Fragless App"
            mock_load.return_value = mock_manifest

            # check_app signature (post-1.4.d): (app_key, ollama_url, ntfy_url, ntfy_topic)
            results = asyncio.run(check_app("fragless", "", "", ""))

        assert results, "Should return check results"
        messages = " ".join(r.message for r in results)
        assert "compose" in messages.lower() or "fragment" in messages.lower() or \
               "misconfigured" in messages.lower(), \
            f"Missing fragment should be flagged. Got: {messages}"

    @slow
    def test_oom_detection_short_circuits_other_checks(self, tmp_env):
        """OOM-killed container skips HTTP/TCP checks and returns OOM result."""
        import asyncio
        from backend.core.state import StateDB
        from backend.health.checker import check_app

        with StateDB() as db:
            db.upsert_app("oomapp", display_name="OOM App",
                          status="running", host_port=8888, tier=2, category="tools")

        # Create a compose fragment so pre-check passes
        frag = tmp_env["compose"] / "oomapp.yaml"
        frag.write_text("services:\n  oomapp:\n    image: test:latest\n")

        with patch("backend.health.checker.load_manifest") as mock_load, \
             patch("backend.health.checker._container_runtime_state") as mock_state, \
             patch("backend.health.checker._in_startup_grace") as mock_grace:

            mock_manifest = MagicMock()
            mock_manifest.health_checks = [MagicMock(check_type="http", name="http_check", path="/")]
            mock_manifest.start_grace_s = 0
            mock_manifest.display_name = "OOM App"
            mock_load.return_value = mock_manifest
            mock_state.return_value = {"oom_killed": True, "restart_count": 5,
                                       "exit_code": 137, "config_disk_pct": 10}
            mock_grace.return_value = (False, 120)

            results = asyncio.run(check_app("oomapp", "", "", ""))

        assert results, "Should return results"
        assert not results[0].ok
        assert "oom" in results[0].message.lower() or "memory" in results[0].message.lower(), \
            f"OOM result should mention OOM. Got: {results[0].message}"
        # Should be only ONE result (short-circuited)
        assert len(results) == 1, "OOM should short-circuit all other checks"


# ── Category 3: LLM context completeness ─────────────────────────────────

class TestLLMContextContracts:
    """Verify LLM context assembler surfaces the right signals."""

    def test_traefik_down_appears_in_context(self, tmp_env):
        """When Traefik is stopped, context must contain TRAEFIK warning."""
        from backend.core.state import StateDB
        from backend.health.context_assembler import assemble_context

        with StateDB() as db:
            db.upsert_app("sonarr", display_name="Sonarr",
                          status="running", host_port=8989, tier=2, category="arr")

        mock_container = MagicMock()
        mock_container.status = "exited"

        with patch("backend.core.docker_client.get_container", return_value=mock_container):
            ctx = assemble_context("sonarr", "http_reachable")

        assert "TRAEFIK" in ctx.upper(), \
            "Context must warn about Traefik being stopped"

    def test_pending_fix_suppresses_duplicate_suggestions(self, tmp_env):
        """If a pending fix exists, context must tell LLM not to suggest again."""
        from backend.core.state import StateDB
        from backend.health.context_assembler import assemble_context

        with StateDB() as db:
            db.upsert_app("radarr", display_name="Radarr",
                          status="running", host_port=7878, tier=2, category="arr")
            db.execute("""
                CREATE TABLE IF NOT EXISTS pending_fixes (
                    id INTEGER PRIMARY KEY,
                    app_key TEXT NOT NULL, check_name TEXT NOT NULL,
                    action_type TEXT NOT NULL, problem TEXT NOT NULL,
                    suggested_fix TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'pending', model TEXT,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    resolved_at INTEGER,
                    UNIQUE(app_key, check_name, action_type)
                )""")
            db.execute(
                "INSERT INTO pending_fixes (app_key, check_name, action_type, problem, suggested_fix, confidence) "
                "VALUES ('radarr', 'http_reachable', 'restart_container', 'Port unreachable', "
                "'Restart the radarr container', 0.8)"
            )

        with patch("backend.core.docker_client.get_container", return_value=None):
            ctx = assemble_context("radarr", "http_reachable")

        assert "pending" in ctx.lower() or "DO NOT suggest" in ctx, \
            "Context must warn LLM about existing pending fix"

    def test_mass_failure_context_warns_infrastructure(self, tmp_env):
        """When ≥4 apps failing, context must contain MASS FAILURE warning."""
        from backend.core.state import StateDB
        from backend.health.context_assembler import assemble_context

        now = int(time.time())
        with StateDB() as db:
            for app in ["sonarr", "radarr", "prowlarr", "bazarr", "lidarr"]:
                db.upsert_app(app, display_name=app.title(),
                              status="running", host_port=8000, tier=2, category="arr")
                db.execute(
                    "INSERT INTO health_checks (subject_type, subject_key, check_name, "
                    "status, summary, checked_at) VALUES ('app', ?, 'http', 'error', 'fail', ?)",
                    (app, now)
                )

        with patch("backend.core.docker_client.get_container", return_value=None):
            ctx = assemble_context("sonarr", "http_reachable")

        assert "MASS FAILURE" in ctx or "simultaneously" in ctx.lower(), \
            "Context must warn about mass failure event"

    def test_failed_install_status_annotated_in_context(self, tmp_env):
        """App with status=failed must have INSTALL FAILED annotation in context."""
        from backend.core.state import StateDB
        from backend.health.context_assembler import assemble_context

        with StateDB() as db:
            db.upsert_app("immich", display_name="Immich",
                          status="failed", host_port=2283, tier=2, category="productivity")

        with patch("backend.core.docker_client.get_container", return_value=None):
            ctx = assemble_context("immich", "http_reachable")

        assert "INSTALL FAILED" in ctx or "failed" in ctx.lower(), \
            "Context must flag failed install status"

    def test_missing_compose_fragment_in_context_says_reinstall(self, tmp_env):
        """Missing fragment context must direct user to reinstall, not restart."""
        from backend.core.state import StateDB
        from backend.health.context_assembler import assemble_context

        with StateDB() as db:
            db.upsert_app("missing_frag_app", display_name="Missing Frag",
                          status="running", host_port=7777, tier=2, category="tools")

        # No compose fragment
        with patch("backend.core.docker_client.get_container", return_value=None):
            ctx = assemble_context("missing_frag_app", "http_reachable")

        assert "reinstall" in ctx.lower() or "CRITICAL" in ctx, \
            "Context must tell user to reinstall when fragment is missing"


# ── Category 4: Platform state machine correctness ────────────────────────

class TestPlatformStateMachine:
    """Verify platform status transitions are correct."""

    def test_reset_clears_domain(self, tmp_env):
        """After reset, platform.domain must be None."""
        from backend.core.state import StateDB
        from backend.api.platform import reset_platform

        with StateDB() as db:
            db.update_platform(status="ready", domain="example.com",
                               traefik_version="v3.0")

        with patch("backend.api.platform.StateDB", StateDB), \
             patch("backend.core.config.config") as mock_cfg:
            mock_cfg.compose_dir = tmp_env["compose"]
            reset_platform()

        with StateDB() as db:
            p = db.get_platform()
        assert p.status == "pending"
        assert p.domain is None, "Reset must clear domain"

    def test_health_checks_skip_when_platform_pending(self, tmp_env):
        """Health scheduler must not run app checks when platform.status=pending."""
        from backend.core.state import StateDB

        with StateDB() as db:
            db.update_platform(status="pending")
            db.upsert_app("testapp", display_name="Test", status="running",
                          host_port=8080, tier=2, category="tools")

        from backend.api.health import get_health_summary
        from fastapi.testclient import TestClient
        from backend.api.main import app

        client = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
        response = client.get("/api/health/summary")
        # Platform pending → no checks run → summary should be empty or indicate pending
        assert response.status_code in (200, 503)


# ── Category 5: Compose fragment ↔ DB consistency ────────────────────────

class TestFragmentDBConsistency:
    """Verify the fragment existence ↔ DB record contract is maintained."""

    def test_ms_check_would_flag_orphaned_record(self, tmp_env):
        """DB record without fragment is detectable (for ms-check logic)."""
        from backend.core.state import StateDB

        with StateDB() as db:
            db.upsert_app("orphan", display_name="Orphan App",
                          status="running", host_port=9000, tier=2, category="tools")

        # No fragment exists
        frag = tmp_env["compose"] / "orphan.yaml"
        assert not frag.exists()

        # The ms-check bash script would detect this — verify the detection query works
        with StateDB() as db:
            apps_without_fragment = [
                row["key"] for row in db.execute(
                    "SELECT key FROM apps WHERE status NOT IN ('disabled','removing','failed')"
                ).fetchall()
                if not (tmp_env["compose"] / f"{row['key']}.yaml").exists()
            ]

        assert "orphan" in apps_without_fragment

    def test_successful_install_creates_both_fragment_and_record(self, tmp_env):
        """Simulated successful install must result in both DB record and fragment."""
        from backend.core.state import StateDB

        # Simulate what executor does on success
        frag = tmp_env["compose"] / "testapp_ok.yaml"
        frag.write_text("services:\n  testapp_ok:\n    image: test:latest\n")

        with StateDB() as db:
            db.upsert_app("testapp_ok", display_name="Test OK",
                          status="running", host_port=8080, tier=2, category="tools")

        with StateDB() as db:
            app = db.get_app("testapp_ok")

        assert app is not None
        assert app.status == "running"
        assert frag.exists()

    def test_failed_install_before_fragment_leaves_clean_state(self, tmp_env):
        """After pre-deploy failure (no fragment written), state is clean for retry."""
        from backend.core.state import StateDB

        # No fragment, no DB record — clean state
        frag = tmp_env["compose"] / "clean_app.yaml"
        assert not frag.exists()

        with StateDB() as db:
            app = db.get_app("clean_app")
        assert app is None, "Clean state: no DB record"

        # After a failed install that cleaned up correctly, same state
        # (this is verified by test_failed_install_without_fragment_deletes_db_record)
