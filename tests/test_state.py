"""tests/test_state.py

Unit tests for the state database module.
Uses a temporary in-memory-adjacent file database — no mocking needed.
"""
import tempfile
import time
from pathlib import Path

import pytest

from backend.core import state
from backend.core.state import StateDB, init_db, StateError


@pytest.fixture
def db(tmp_path: Path):
    """Fresh database for each test."""
    db_path = tmp_path / "test_state.db"
    init_db(db_path)
    yield db_path


# ── Platform ──────────────────────────────────────────────────────────────

class TestPlatform:
    def test_get_platform_creates_singleton(self, db):
        with StateDB() as s:
            p = s.get_platform()
        assert p.status == "pending"
        assert p.network_name == "mediastack"
        assert p.puid == 1000

    def test_update_platform_domain(self, db):
        with StateDB() as s:
            s.update_platform(domain="nyrdalyrt.com", status="ready")
            p = s.get_platform()
        assert p.domain == "nyrdalyrt.com"
        assert p.status == "ready"

    def test_update_platform_ignores_unknown_fields(self, db):
        with StateDB() as s:
            s.update_platform(bogus_field="should_be_ignored")
            p = s.get_platform()
        assert p.domain is None  # unchanged


# ── Infrastructure slots ──────────────────────────────────────────────────

class TestInfraSlots:
    def test_all_five_slots_exist(self, db):
        with StateDB() as s:
            slots = s.get_all_slots()
        keys = {sl.slot for sl in slots}
        assert keys == {"auth", "tunnel", "vpn", "management", "dashboard"}

    def test_all_slots_start_empty(self, db):
        with StateDB() as s:
            slots = s.get_all_slots()
        for sl in slots:
            assert sl.status == "empty"
            assert sl.provider is None

    def test_update_slot_provider(self, db):
        with StateDB() as s:
            s.update_slot("auth", provider="tinyauth", status="active",
                          config={"app_url": "https://auth.example.com"})
            sl = s.get_slot("auth")
        assert sl.provider == "tinyauth"
        assert sl.status == "active"
        assert sl.config["app_url"] == "https://auth.example.com"

    def test_get_unknown_slot_raises(self, db):
        with StateDB() as s:
            with pytest.raises(StateError, match="Unknown infrastructure slot"):
                s.get_slot("nonexistent")


# ── Apps ─────────────────────────────────────────────────────────────────

class TestApps:
    def test_get_nonexistent_app_returns_none(self, db):
        with StateDB() as s:
            assert s.get_app("sonarr") is None

    def test_upsert_creates_app(self, db):
        with StateDB() as s:
            app_id = s.upsert_app(
                "sonarr",
                display_name="Sonarr",
                category="arr",
                image="lscr.io/linuxserver/sonarr",
                image_tag="latest",
                container_name="sonarr",
                web_port=8989,
                host_port=8989,
            )
            app = s.get_app("sonarr")
        assert app_id > 0
        assert app.key == "sonarr"
        assert app.web_port == 8989
        assert app.status == "installing"

    def test_upsert_updates_existing_app(self, db):
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr")
            s.upsert_app("sonarr", status="running")
            app = s.get_app("sonarr")
        assert app.status == "running"

    def test_get_all_apps_empty(self, db):
        with StateDB() as s:
            apps = s.get_all_apps()
        assert apps == []

    def test_get_all_apps_filtered_by_status(self, db):
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr", status="running")
            s.upsert_app("radarr", display_name="Radarr", category="arr",
                         image="img", container_name="radarr", status="stopped")
            running = s.get_all_apps(status="running")
        assert len(running) == 1
        assert running[0].key == "sonarr"

    def test_remove_app(self, db):
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr")
            s.remove_app("sonarr")
            app = s.get_app("sonarr")
        assert app is None


# ── Operations log ────────────────────────────────────────────────────────

class TestOperations:
    def test_log_and_complete_operation(self, db):
        with StateDB() as s:
            op_id = s.log_operation(
                "install", "app", "sonarr",
                detail={"image": "lscr.io/linuxserver/sonarr"}
            )
            s.complete_operation(op_id)
            ops = s.get_recent_operations()
        assert len(ops) == 1
        assert ops[0].status == "completed"
        assert ops[0].detail["image"] == "lscr.io/linuxserver/sonarr"

    def test_failed_operation_records_error(self, db):
        with StateDB() as s:
            op_id = s.log_operation("install", "app", "sonarr")
            s.complete_operation(op_id, status="failed",
                                 error="Port 8989 is already in use by another container.")
            ops = s.get_recent_operations()
        assert ops[0].status == "failed"
        assert "Port 8989" in ops[0].error


# ── Health checks ─────────────────────────────────────────────────────────

class TestHealthChecks:
    def test_upsert_and_retrieve(self, db):
        with StateDB() as s:
            s.upsert_health_check(
                "app", "sonarr", "api_reachable",
                status="ok", summary="API responded in 12ms"
            )
            checks = s.get_health_checks("app", "sonarr")
        assert len(checks) == 1
        assert checks[0].status == "ok"

    def test_upsert_overwrites_previous_result(self, db):
        with StateDB() as s:
            s.upsert_health_check("app", "sonarr", "api_reachable",
                                  status="ok", summary="OK")
            s.upsert_health_check("app", "sonarr", "api_reachable",
                                  status="error", summary="Connection refused")
            checks = s.get_health_checks("app", "sonarr")
        assert len(checks) == 1
        assert checks[0].status == "error"


# ── Settings ──────────────────────────────────────────────────────────────

class TestSettings:
    def test_defaults_present(self, db):
        with StateDB() as s:
            val = s.get_setting("disk_warn_percent")
        assert val == "80"

    def test_set_and_get_setting(self, db):
        with StateDB() as s:
            s.set_setting("cf_auto_register_hostnames", "true")
            val = s.get_setting("cf_auto_register_hostnames")
        assert val == "true"

    def test_get_missing_setting_returns_default(self, db):
        with StateDB() as s:
            val = s.get_setting("nonexistent_key", default="fallback")
        assert val == "fallback"


# ── External resources ────────────────────────────────────────────────────

class TestExternalResources:
    def test_record_and_retrieve_resource(self, db):
        with StateDB() as s:
            s.upsert_app("sonarr", display_name="Sonarr", category="arr",
                         image="img", container_name="sonarr")
            app = s.get_app("sonarr")
            s.record_external_resource(
                "cf_tunnel_hostname",
                hostname="sonarr.nyrdalyrt.com",
                target="HTTPS:192.168.1.100:443",
                app_id=app.id,
                resource_id="abc123",
            )
            resources = s.get_active_resources(app_id=app.id)
        assert len(resources) == 1
        assert resources[0]["hostname"] == "sonarr.nyrdalyrt.com"

    def test_mark_resource_removed(self, db):
        with StateDB() as s:
            s.record_external_resource(
                "cf_tunnel_hostname",
                hostname="sonarr.nyrdalyrt.com",
                target="HTTPS:192.168.1.100:443",
                resource_id="abc123",
            )
            s.mark_resource_removed("abc123")
            resources = s.get_active_resources()
        assert len(resources) == 0


# ── StateDB context manager ───────────────────────────────────────────────

class TestStateDBContextManager:
    def test_raises_outside_context(self, db):
        s = StateDB()
        with pytest.raises(StateError, match="outside of context manager"):
            s.get_platform()

    # test_test_rollback_on_exception removed — duplicate of test in test_comprehensive_contracts.py

    def test_autocommit_on_clean_exit(self, db):
        """Core Rule 4.4 — StateDB auto-commits on clean __exit__.

        Behavioral companion to the Semgrep rule `bare-db-commit`
        (Core Rule 3.5: every static rule has a runtime test). Proves that
        callers do NOT need to call db._c.commit() manually inside a
        `with StateDB()` block — the context manager handles it.
        """
        # Write inside a context, no manual commit
        with StateDB() as s:
            s.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("autocommit_test_marker", "persisted"),
            )
            # NOTE: deliberately NO db._c.commit() here — this is the point

        # Reopen — value should be present, proving the first block committed
        with StateDB() as s:
            row = s.execute(
                "SELECT value FROM settings WHERE key = ?",
                ("autocommit_test_marker",),
            ).fetchone()
        assert row is not None, "auto-commit on clean exit failed — data lost"
        assert row["value"] == "persisted"

    def test_rollback_on_exception(self, db):
        """Core Rule 4.4 — StateDB rolls back on __exit__ when an exception propagates.

        The complement to test_autocommit_on_clean_exit: data written inside a
        with-block that raises must NOT persist.
        """
        with pytest.raises(RuntimeError, match="boom"):
            with StateDB() as s:
                s.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    ("rollback_test_marker", "should_not_persist"),
                )
                raise RuntimeError("boom")

        with StateDB() as s:
            row = s.execute(
                "SELECT value FROM settings WHERE key = ?",
                ("rollback_test_marker",),
            ).fetchone()
        assert row is None, "rollback on exception failed — uncommitted data persisted"
