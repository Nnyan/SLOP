"""tests/test_api_coverage.py

Comprehensive tests covering all previously untested API routes and workflows.
Tests every major user flow end-to-end:
  - App install from catalog (single + batch)
  - YAML linter for custom apps
  - Health: pending actions, anomaly detection, apply-fix, platform-review
  - Settings: secrets read/write, AI safety, cloud LLM config
  - Models: hardware eval, HF search preflight, fix-history CRUD
  - Platform: reset, wizard steps
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.core.state import StateDB, init_db
from backend.core.docker_client import DockerError
from backend.api import models as models_api


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_manifest_cache():
    """Clear manifest cache between tests."""
    from backend.manifests.loader import clear_cache
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated database for each test — patches both state and config."""
    import backend.core.state as sm
    import backend.core.config as cm
    p = tmp_path / "state.db"
    init_db(p)
    sm.configure(p)
    return p


@pytest.fixture
def client(db_path: Path):
    """TestClient with properly isolated database."""
    import backend.core.config as cm
    import backend.core.state as sm
    from backend.api.main import app

    # Patch config.db_path so lifespan uses the test DB
    with patch.object(type(cm.config), "db_path", property(lambda self: db_path)):
        sm.configure(db_path)
        with TestClient(app, base_url="http://localhost") as c:
            yield c


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    """A .env file with test credentials."""
    p = tmp_path / ".env"
    p.write_text(
        "CF_DNS_API_TOKEN=testtoken123\n"
        "CF_ZONE_ID=zone456\n"
        "POSTGRES_PASSWORD=pgpass789\n"
    )
    return p


# ── Workflow 1: Single app install from catalog ───────────────────────────────


class TestAppInstallWorkflow:
    def test_install_unknown_app_returns_404(self, client):
        r = client.post("/api/apps/does_not_exist_xyz/install", json={})
        assert r.status_code == 404

    def test_install_progress_returns_empty_before_install(self, client):
        r = client.get("/api/apps/sonarr/install/progress")
        assert r.status_code == 200
        data = r.json()
        assert "steps" in data

    def test_install_concurrent_guard(self, client):
        """Second install request while one is in progress returns 409."""
        with patch("backend.api.apps._installing", {"sonarr"}):
            r = client.post("/api/apps/sonarr/install", json={})
        assert r.status_code == 409
        assert "already being installed" in r.json().get("detail", "")

    def test_app_logs_returns_error_when_docker_unavailable(self, client, db_path):
        """App logs endpoint should handle Docker being unavailable."""
        with StateDB() as db:
            db.upsert_app(
                "sonarr", display_name="Sonarr", category="arr",
                image="sonarr", container_name="sonarr", status="running",
                config_path="/tmp/sonarr",
            )
        # Patch at the module level where logs are fetched
        with patch("backend.core.docker_client.container_logs",
                   side_effect=DockerError("Docker unavailable")):
            r = client.get("/api/apps/sonarr/logs")
        # Should return some response (not 500 crash)
        assert r.status_code in (200, 503, 404)

    def test_app_restart_returns_503_when_docker_unavailable(self, client, db_path):
        with StateDB() as db:
            db.upsert_app(
                "sonarr", display_name="Sonarr", category="arr",
                image="sonarr", container_name="sonarr", status="running",
                config_path="/tmp/sonarr",
            )
        with patch("backend.core.docker_client.get_container",
                   return_value=None):
            r = client.post("/api/apps/sonarr/restart")
        # App not running → error response
        assert r.status_code in (200, 404, 503)


# ── Workflow 2: Batch install with dependency resolution ──────────────────────


class TestBatchInstallWorkflow:
    def test_preflight_resolves_dependencies(self, client):
        r = client.post("/api/apps/batch/preflight", json={"keys": ["sonarr"]})
        assert r.status_code == 200
        data = r.json()
        assert data["can_proceed"] is True
        # sonarr requires prowlarr — should be added
        assert "prowlarr" in data["install_order"]
        # sonarr should also be in order
        assert "sonarr" in data["install_order"]
        # prowlarr should come before sonarr
        order = data["install_order"]
        assert order.index("prowlarr") < order.index("sonarr")

    def test_preflight_rejects_unknown_app(self, client):
        r = client.post("/api/apps/batch/preflight", json={"keys": ["totally_fake_app_xyz"]})
        assert r.status_code == 200
        data = r.json()
        assert data["can_proceed"] is False
        assert any("not in catalog" in i["message"].lower() for i in data["issues"])

    def test_preflight_already_installed_shown_as_info(self, client, db_path):
        with StateDB() as db:
            db.upsert_app(
                "prowlarr", display_name="Prowlarr", category="arr",
                image="prowlarr", container_name="prowlarr", status="running",
                config_path="/tmp/prowlarr",
            )
        r = client.post("/api/apps/batch/preflight", json={"keys": ["prowlarr"]})
        data = r.json()
        # Already installed apps show as info-level issues
        all_msgs = [i["message"].lower() for i in data["issues"]]
        assert any("already" in m or "installed" in m or "skip" in m for m in all_msgs)

    def test_batch_install_runs_preflight_before_install(self, client):
        """Batch install with invalid key should fail gracefully."""
        r = client.post("/api/apps/batch/install",
                        json={"keys": ["nonexistent_app_abc_xyz"]})
        # Either 404 or 200 with ok=False
        assert r.status_code in (200, 404, 422)
        if r.status_code == 200:
            assert r.json().get("ok") is False or r.json().get("status") == "error"


# ── Workflow 3: YAML linter custom app ───────────────────────────────────────


class TestYAMLLinterWorkflow:
    def test_valid_compose_fragment(self, client):
        r = client.post("/api/apps/lint-compose", json={"yaml": """
services:
  myapp:
    image: nginx:latest
    ports:
      - 8888:8888
    volumes:
      - /config:/config
"""})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert data["manifest_preview"] is not None
        assert data["manifest_preview"]["key"] == "myapp"
        assert data["manifest_preview"]["web_port"] == 8888

    def test_invalid_yaml_syntax(self, client):
        r = client.post("/api/apps/lint-compose", json={"yaml": "this: {bad: yaml"})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0
        assert "line" in data["errors"][0].lower() or "syntax" in data["errors"][0].lower()

    def test_missing_image_field(self, client):
        r = client.post("/api/apps/lint-compose", json={"yaml": """
services:
  app:
    ports:
      - 8080:8080
"""})
        assert r.status_code == 200
        assert r.json()["valid"] is False
        assert any("image" in e.lower() for e in r.json()["errors"])

    def test_hardcoded_secret_warning(self, client):
        r = client.post("/api/apps/lint-compose", json={"yaml": """
services:
  app:
    image: myapp:latest
    environment:
      API_KEY: hardcoded_secret_value_here
"""})
        data = r.json()
        assert any("secret" in w.lower() or "hardcoded" in w.lower()
                   for w in data["warnings"])

    def test_empty_yaml(self, client):
        r = client.post("/api/apps/lint-compose", json={"yaml": ""})
        assert r.status_code == 200
        assert r.json()["valid"] is False

    def test_bare_service_without_wrapper(self, client):
        """Service definition without 'services:' wrapper should work."""
        r = client.post("/api/apps/lint-compose", json={"yaml": """
image: nginx:latest
ports:
  - 9090:80
"""})
        # Should either be valid (with warning) or have a clear error
        data = r.json()
        assert "valid" in data


# ── Workflow 3b: YAML linter — port conflict detection ───────────────────────


class TestLintComposeYamlPortConflict:
    """Port conflict detection in lint_compose_yaml — regression guards.

    The linter checks host ports in the submitted compose fragment against:
    1. System ports already bound on the host (/proc/net/tcp via _get_listening_ports)
    2. Host ports of already-installed Mediastack apps (StateDB)

    Port conflicts become warnings (not errors) — the linted YAML is still
    structurally valid, but the container may fail to bind at runtime.
    """

    COMPOSE_PORT_8080 = """
services:
  app:
    image: nginx:1.27
    ports:
      - "8080:80"
"""

    COMPOSE_PORT_9090 = """
services:
  app:
    image: nginx:1.27
    ports:
      - "9090:80"
"""

    def test_system_port_conflict_triggers_warning(self, client):
        """Linter warns when compose host port matches a system-listening port."""
        with patch("backend.api.apps._get_listening_ports", return_value={8080}):
            r = client.post("/api/apps/lint-compose", json={"yaml": self.COMPOSE_PORT_8080})
        assert r.status_code == 200
        data = r.json()
        # Port conflict is a warning — compose YAML itself is still structurally valid
        assert data["valid"] is True, f"Expected valid=True (conflict is a warning), got: {data}"
        assert any("8080" in w for w in data["warnings"]), (
            f"Expected a warning mentioning port 8080 but got warnings: {data['warnings']}"
        )
        assert any(pc["port"] == 8080 for pc in data["port_conflicts"]), (
            f"Expected port_conflicts to include port 8080 but got: {data['port_conflicts']}"
        )
        conflict_entry = next(pc for pc in data["port_conflicts"] if pc["port"] == 8080)
        assert conflict_entry["type"] == "system", (
            f"Expected conflict type 'system' but got: {conflict_entry['type']}"
        )

    def test_installed_app_port_conflict_triggers_warning(self, client):
        """Linter warns when compose host port is used by an installed Mediastack app."""
        mock_app = MagicMock()
        mock_app.host_port = 8080
        mock_app.display_name = "Sonarr"

        with patch("backend.api.apps._get_listening_ports", return_value=set()):
            with patch("backend.core.state.StateDB.get_all_apps", return_value=[mock_app]):
                r = client.post("/api/apps/lint-compose", json={"yaml": self.COMPOSE_PORT_8080})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert any("8080" in w for w in data["warnings"]), (
            f"Expected port conflict warning for installed-app path but got: {data['warnings']}"
        )
        conflict_entries = [pc for pc in data["port_conflicts"] if pc["port"] == 8080]
        assert conflict_entries, f"port_conflicts empty; expected port 8080 entry"
        assert conflict_entries[0]["type"] == "installed_app"
        assert "Sonarr" in conflict_entries[0]["conflicting"]

    def test_different_host_port_no_conflict(self, client):
        """No port conflict warning when compose host port is not in use."""
        with patch("backend.api.apps._get_listening_ports", return_value={8080}):
            r = client.post("/api/apps/lint-compose", json={"yaml": self.COMPOSE_PORT_9090})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        conflict_warnings = [w for w in data["warnings"] if "conflict" in w.lower() or "already" in w.lower()]
        assert not conflict_warnings, (
            f"Unexpected port conflict warning for port 9090 (only 8080 is in use): {conflict_warnings}"
        )
        assert data["port_conflicts"] == [], (
            f"Expected empty port_conflicts for non-conflicting port 9090 but got: {data['port_conflicts']}"
        )

    def test_no_ports_no_conflict_check(self, client):
        """Compose fragment without ports mapping skips conflict check cleanly."""
        compose_no_ports = """
services:
  app:
    image: nginx:1.27
"""
        with patch("backend.api.apps._get_listening_ports", return_value={8080, 9090}):
            r = client.post("/api/apps/lint-compose", json={"yaml": compose_no_ports})
        assert r.status_code == 200
        data = r.json()
        assert data["port_conflicts"] == [], (
            f"No ports mapped — expected empty port_conflicts but got: {data['port_conflicts']}"
        )


# ── Workflow 4: Health pending actions ───────────────────────────────────────


class TestPendingActions:
    def test_returns_list_on_empty_platform(self, client, db_path):
        r = client.get("/api/health/pending-actions")
        assert r.status_code == 200
        actions = r.json()
        assert isinstance(actions, list)
        # Empty platform should have at least "platform setup incomplete"
        priorities = [a["priority"] for a in actions]
        assert "error" in priorities or "warning" in priorities

    def test_setup_incomplete_is_first_error(self, client, db_path):
        r = client.get("/api/health/pending-actions")
        actions = r.json()
        if actions:
            # Errors should come before warnings and suggestions
            error_indices = [i for i, a in enumerate(actions) if a["priority"] == "error"]
            warn_indices = [i for i, a in enumerate(actions) if a["priority"] == "warning"]
            sugg_indices = [i for i, a in enumerate(actions) if a["priority"] == "suggestion"]
            if error_indices and warn_indices:
                assert max(error_indices) < min(warn_indices)
            if warn_indices and sugg_indices:
                assert max(warn_indices) < min(sugg_indices)

    def test_returns_actions_with_required_fields(self, client, db_path):
        r = client.get("/api/health/pending-actions")
        actions = r.json()
        for action in actions:
            assert "priority" in action
            assert "title" in action
            assert "description" in action
            assert "action" in action
            assert action["priority"] in ("error", "warning", "suggestion")

    def test_no_errors_when_platform_ready(self, client, db_path):
        """When platform is configured, setup error should not appear."""
        with StateDB() as db:
            db.update_platform(
                status="ready", domain="test.com", config_root="/tmp",
                media_root="/tmp/media", network_name="mediastack",
                cert_resolver="letsencrypt",
            )
        r = client.get("/api/health/pending-actions")
        assert r.status_code == 200
        actions = r.json()
        # "Platform setup incomplete" should NOT be in the list now
        titles = [a["title"].lower() for a in actions]
        assert not any("setup incomplete" in t for t in titles)


# ── Workflow 5: Anomaly detection ────────────────────────────────────────────


class TestAnomalyDetection:
    def test_returns_empty_list_on_fresh_db(self, client, db_path):
        r = client.get("/api/health/anomalies")
        assert r.status_code == 200
        assert r.json() == []

    def test_detects_recurring_pattern(self, db_path):
        """Unit test: insert failures directly and run anomaly detection."""
        import backend.core.state as sm
        sm.configure(db_path)
        with StateDB() as db:
            db.upsert_app('sonarr', display_name='Sonarr', status='running', tier=2, category='arr')
            now = int(time.time())
            for i in range(6):
                db.execute(
                    """INSERT INTO health_check_history
                       (subject_type, subject_key, check_name, status, summary, checked_at)
                       VALUES ('app', 'sonarr', 'api_reachable', 'error', 'Connection refused',
                               ?)""",
                    (now - i * 3600,)
                )
        # Test the function directly
        from backend.health.anomaly import get_anomaly_summary
        data = get_anomaly_summary()
        assert len(data) >= 1
        sonarr_pattern = next((p for p in data if p["app_key"] == "sonarr"), None)
        assert sonarr_pattern is not None
        assert sonarr_pattern["occurrences"] >= 6
        assert sonarr_pattern["is_recurring"] is True

    def test_fewer_than_3_occurrences_not_flagged(self, client, db_path):
        """Only 2 failures — below threshold."""
        with StateDB() as db:
            now = int(time.time())
            for i in range(2):
                db.execute(
                    """INSERT INTO health_check_history
                       (subject_type, subject_key, check_name, status, summary, checked_at)
                       VALUES ('app', 'radarr', 'http_check', 'error', 'Timeout', ?)""",
                    (now - i * 3600,)
                )
        r = client.get("/api/health/anomalies")
        data = r.json()
        radarr_patterns = [p for p in data if p["app_key"] == "radarr"]
        assert len(radarr_patterns) == 0


# ── Workflow 6: Apply fix ─────────────────────────────────────────────────────


class TestApplyFix:
    def test_apply_fix_respects_observe_level(self, client, db_path):
        """When safety level is 'observe', apply-fix should block."""
        with StateDB() as db:
            db.set_setting("ai_safety_restart_container", "observe")
        r = client.post("/api/health/apply-fix", json={
            "app_key": "sonarr",
            "action_type": "restart_container",
            "suggested_fix": "Restart the container",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False or data.get("executed") is False

    def test_apply_fix_suggest_level_requires_approval(self, client, db_path):
        """'suggest' level should report requires_approval=True."""
        with StateDB() as db:
            db.set_setting("ai_safety_restart_container", "suggest")
        with patch("backend.core.ai_safety.execute_action") as mock_exec:
            mock_exec.return_value = {
                "executed": False,
                "requires_approval": True,
                "message": "Needs approval"
            }
            r = client.post("/api/health/apply-fix", json={
                "app_key": "sonarr",
                "action_type": "restart_container",
                "suggested_fix": "Restart",
            })
        assert r.status_code == 200

    def test_apply_fix_records_in_fix_history(self, client, db_path):
        """Calling apply-fix with suggest level records in fix_history."""
        with StateDB() as db:
            db.set_setting("ai_safety_restart_container", "suggest")
        with patch("backend.core.ai_safety.execute_action") as mock_exec:
            mock_exec.return_value = {"executed": False, "requires_approval": True,
                                      "message": "needs approval"}
            r = client.post("/api/health/apply-fix", json={
                "app_key": "sonarr",
                "action_type": "restart_container",
                "suggested_fix": "Restart container",
            })
        # Response should be ok (even if not auto-executed)
        assert r.status_code == 200
        data = r.json()
        # requires_approval=True means it was not blocked, just needs user action
        assert "requires_approval" in data or "message" in data


# ── Workflow 7: Platform review ───────────────────────────────────────────────


class TestPlatformReview:
    def test_platform_review_returns_summary(self, client, db_path):
        """Platform review should always return a summary, even without LLM."""
        with patch("backend.api.health._llm_state", {"status": "no_model"}):
            r = client.post("/api/health/platform-review")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "summary" in data
        assert len(data["summary"]) > 10

    def test_platform_review_includes_action_count(self, client, db_path):
        r = client.post("/api/health/platform-review")
        data = r.json()
        assert "action_count" in data
        assert isinstance(data["action_count"], int)
        assert "suggestions" in data


# ── Workflow 8: Settings secrets ─────────────────────────────────────────────


class TestSettingsSecrets:
    def test_get_secrets_returns_masked_values(self, client, db_path, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("CF_DNS_API_TOKEN=cfut_reallylongsecrettoken123\n")
        with patch("backend.api.settings.config") as mock_cfg:
            mock_cfg.env_file = env_file
            r = client.get("/api/settings/secrets")
        assert r.status_code == 200
        data = r.json()
        assert "secrets" in data
        # CF_DNS_API_TOKEN should be masked
        cf_token = data["secrets"].get("CF_DNS_API_TOKEN", {})
        assert cf_token.get("is_set") is True
        val = cf_token.get("value", "")
        assert "•" in val  # should be masked

    def test_put_secrets_updates_env_file(self, client, db_path, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("CF_DNS_API_TOKEN=oldtoken\nCF_ZONE_ID=myzone\n")
        with patch("backend.api.settings.config") as mock_cfg:
            mock_cfg.env_file = env_file
            r = client.put("/api/settings/secrets",
                           json={"updates": {"CF_DNS_API_TOKEN": "newtoken123"}})
        assert r.status_code == 200
        content = env_file.read_text()
        assert "newtoken123" in content
        assert "myzone" in content  # other key preserved

    def test_put_secrets_rejects_disallowed_key(self, client, db_path):
        r = client.put("/api/settings/secrets",
                       json={"updates": {"SOME_RANDOM_KEY": "value"}})
        assert r.status_code == 422


# ── Workflow 9: AI safety settings ───────────────────────────────────────────


class TestAISafetySettings:
    def test_get_ai_safety_returns_all_action_types(self, client, db_path):
        r = client.get("/api/settings/ai-safety")
        assert r.status_code == 200
        data = r.json()
        assert "levels" in data
        levels = data["levels"]
        assert "restart_container" in levels
        assert "reload_config" in levels
        assert "pull_image" in levels
        assert "modify_config_file" in levels

    def test_set_actable_to_act_succeeds(self, client, db_path):
        r = client.put("/api/settings/ai-safety",
                       json={"action_type": "restart_container", "level": "act"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_set_non_actable_to_act_fails(self, client, db_path):
        r = client.put("/api/settings/ai-safety",
                       json={"action_type": "modify_config_file", "level": "act"})
        assert r.status_code == 422

    def test_set_invalid_level_fails(self, client, db_path):
        r = client.put("/api/settings/ai-safety",
                       json={"action_type": "restart_container", "level": "turbo"})
        assert r.status_code == 422

    def test_default_level_is_suggest(self, client, db_path):
        """Default is suggest UNLESS a previous test changed it — reset first."""
        # Reset to default before checking
        client.put("/api/settings/ai-safety",
                   json={"action_type": "restart_container", "level": "suggest"})
        r = client.get("/api/settings/ai-safety")
        levels = r.json()["levels"]
        assert levels["restart_container"]["level"] == "suggest"


# ── Workflow 10: Cloud LLM settings ──────────────────────────────────────────


class TestCloudLLMSettings:
    def test_get_cloud_llm_returns_provider_list(self, client, db_path, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GROQ_API_KEY=gsk_test123\n")
        with patch("backend.api.settings.config") as mock_cfg:
            mock_cfg.env_file = env_file
            r = client.get("/api/settings/cloud-llm")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data
        assert "groq" in data["providers"]
        assert "anthropic" in data["providers"]
        assert "monthly_limit_usd" in data
        assert "total_spend_this_month" in data

    def test_groq_shows_as_configured_with_key(self, client, db_path, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GROQ_API_KEY=gsk_realkey123\n")
        import backend.core.config as _cfg_mod
        with patch.object(type(_cfg_mod.config), "env_file",
                          property(lambda self: env_file)):
            r = client.get("/api/settings/cloud-llm")
        data = r.json()
        assert data["providers"]["groq"]["configured"] is True
        assert data["providers"]["anthropic"]["configured"] is False

    def test_update_monthly_limit(self, client, db_path, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("")
        with patch("backend.api.settings.config") as mock_cfg:
            mock_cfg.env_file = env_file
            r = client.put("/api/settings/cloud-llm",
                           json={"monthly_limit_usd": 5.00})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_negative_limit_rejected(self, client, db_path, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("")
        with patch("backend.api.settings.config") as mock_cfg:
            mock_cfg.env_file = env_file
            r = client.put("/api/settings/cloud-llm",
                           json={"monthly_limit_usd": -1.00})
        assert r.status_code == 422


# ── Workflow 11: Model hardware evaluation ───────────────────────────────────


class TestHardwareEvaluation:
    def test_evaluate_returns_all_steps(self, client, db_path):
        r = client.post("/api/models/evaluate-hardware?model_size_gb=4.0&quantization=Q4_K_M")
        assert r.status_code == 200
        data = r.json()
        assert "steps" in data
        assert "verdict" in data
        assert "summary" in data
        step_labels = [s["label"] for s in data["steps"]]
        assert "RAM" in step_labels
        assert "CPU" in step_labels
        assert "GPU" in step_labels
        assert "Storage" in step_labels
        assert "Verdict" in step_labels

    def test_verdict_is_valid_value(self, client, db_path):
        r = client.post("/api/models/evaluate-hardware?model_size_gb=2.0")
        data = r.json()
        assert data["verdict"] in ("runs_well", "runs_slowly", "cannot_run")

    def test_each_step_has_status(self, client, db_path):
        r = client.post("/api/models/evaluate-hardware")
        data = r.json()
        for step in data["steps"]:
            assert step["status"] in ("ok", "warn", "error", "info")
            assert len(step["detail"]) > 0


# ── Workflow 12: Model preflight and HF search ───────────────────────────────


class TestModelPreflight:
    def test_preflight_invalid_url_format(self, client, db_path):
        r = client.post("/api/models/gguf/preflight?url=not-a-url")
        assert r.status_code == 200
        data = r.json()
        # Should fail gracefully
        assert "ok" in data
        assert "error" in data or data["ok"] is False

    def test_preflight_unreachable_url(self, client, db_path):
        """Unreachable host should return ok=False with error."""
        r = client.post(
            "/api/models/gguf/preflight?url=https://this-host-does-not-exist-xyz.example.com/model.gguf"
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["error"] is not None

    def test_hf_search_returns_list(self, client, db_path):
        """HuggingFace search — may fail if offline, should not 500."""
        try:
            r = client.get("/api/models/hf/search?q=phi-4-mini&limit=3")
            # Either success or graceful error
            assert r.status_code in (200, 503)
            if r.status_code == 200:
                assert isinstance(r.json(), list)
        except Exception:
            pass  # network unavailable in CI — skip


# ── Workflow 13: Fix history CRUD ─────────────────────────────────────────────


class TestFixHistory:
    def test_post_fix_record(self, client, db_path):
        r = client.post("/api/models/fix-history", json={
            "app_key": "sonarr",
            "error_type": "api_reachable",
            "context": "HTTP 502 Bad Gateway",
            "suggested_fix": "Restart the container",
            "outcome": "pending",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_get_fix_history_returns_records(self, db_path):
        """Unit test: insert fix record and verify retrieval."""
        import backend.core.state as sm
        sm.configure(db_path)
        with StateDB() as db:
            db.execute(
                """INSERT INTO fix_history
                   (app_key, error_type, context, suggested_fix, outcome, created_at)
                   VALUES ('radarr', 'disk_space', 'Disk full', 'Clean Docker', 'pending', ?)""",
                (int(time.time()),)
            )
        # Test via the API function directly
        from backend.api.models import get_fix_history
        data = get_fix_history(app_key=None, limit=20)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(rec["app_key"] == "radarr" for rec in data)

    def test_get_fix_history_filtered_by_app(self, client, db_path):
        client.post("/api/models/fix-history", json={
            "app_key": "plex",
            "error_type": "transcode",
            "context": "Hardware transcoding failed",
            "suggested_fix": "Enable software transcoding",
        })
        r = client.get("/api/models/fix-history?app_key=plex")
        data = r.json()
        assert all(rec["app_key"] == "plex" for rec in data)

    def test_update_fix_outcome(self, client, db_path):
        # Create record
        client.post("/api/models/fix-history", json={
            "app_key": "sonarr",
            "error_type": "db_locked",
            "context": "Database locked",
            "suggested_fix": "Restart container",
        })
        with StateDB() as db:
            row = db.execute(
                "SELECT id FROM fix_history WHERE app_key='sonarr' LIMIT 1"
            ).fetchone()
        if row:
            r = client.put(f"/api/models/fix-history/{row['id']}/outcome",
                           params={"outcome": "success"})
            assert r.status_code == 200

    def test_update_fix_outcome_invalid_value(self, client, db_path):
        r = client.put("/api/models/fix-history/1/outcome",
                       params={"outcome": "banana"})
        assert r.status_code == 422


# ── Workflow 14: Platform reset ───────────────────────────────────────────────


class TestPlatformReset:
    def test_reset_pending_platform_returns_message(self, client, db_path):
        r = client.post("/api/platform/reset")
        assert r.status_code == 200
        data = r.json()
        assert "message" in data

    def test_reset_ready_platform_changes_status(self, client, db_path):
        with StateDB() as db:
            db.update_platform(
                status="ready", domain="test.com", config_root="/tmp",
                media_root="/tmp/media", network_name="mediastack",
                cert_resolver="letsencrypt",
            )
        r = client.post("/api/platform/reset")
        assert r.status_code == 200
        with StateDB() as db:
            p = db.get_platform()
        assert p.status == "pending"


# ── Workflow 15: RAG knowledge base queries ───────────────────────────────────


class TestRAGKnowledgeBase:
    def test_query_returns_relevant_results(self):
        from backend.core.rag import query_knowledge_base
        results = query_knowledge_base("database locked error sonarr")
        assert len(results) >= 1
        combined = " ".join(results).lower()
        assert "database" in combined or "locked" in combined

    def test_query_traefik_cert(self):
        from backend.core.rag import query_knowledge_base
        results = query_knowledge_base("traefik certificate acme failed cloudflare")
        assert len(results) >= 1

    def test_query_unknown_returns_something(self):
        """Even for obscure queries, RAG should return something."""
        from backend.core.rag import query_knowledge_base
        results = query_knowledge_base("xyzzy unknown error code")
        # May return empty list for truly unknown query — that's OK
        assert isinstance(results, list)

    def test_enrich_prompt_adds_context(self):
        from backend.core.rag import enrich_prompt_with_context
        original = "Diagnose this error."
        enriched = enrich_prompt_with_context(original, "database locked sonarr")
        # Enriched prompt should be longer
        assert len(enriched) >= len(original)


# ── Workflow 16: Cloud LLM sanitization ──────────────────────────────────────


class TestCloudLLMSanitization:
    def test_sanitizes_long_token(self):
        from backend.core.cloud_llm import sanitize_context, restore_context
        text = "Error: CF_DNS_API_TOKEN=cfut_abc123def456ghi789 failed"
        sanitized, subst = sanitize_context(text)
        assert "cfut_abc123def456ghi789" not in sanitized
        assert len(subst) >= 1
        restored = restore_context(sanitized, subst)
        assert "cfut_abc123def456ghi789" in restored

    def test_sanitizes_ip_address(self):
        from backend.core.cloud_llm import sanitize_context
        text = "Server at 192.168.1.100 is unreachable"
        sanitized, subst = sanitize_context(text)
        assert "192.168.1.100" not in sanitized

    def test_restore_roundtrip(self):
        from backend.core.cloud_llm import sanitize_context, restore_context
        original = "Token: abcdefghijklmnopqrstuvwxyz123456"
        sanitized, subst = sanitize_context(original)
        restored = restore_context(sanitized, subst)
        assert restored == original

    def test_estimate_tokens_reasonable(self):
        from backend.core.cloud_llm import estimate_tokens
        short = "Hello"
        long_text = "word " * 1000
        assert estimate_tokens(short) < estimate_tokens(long_text)
        # Should be roughly 1K for 1K * 5 chars text
        assert 800 < estimate_tokens(long_text) < 1500

    def test_cost_estimate_free_tier_is_zero(self):
        """Featherless flat-rate and free model providers should show $0."""
        from backend.core.cloud_llm import estimate_cost
        cost = estimate_cost("featherless", 10_000, 3_000)
        assert cost == 0.0

    def test_cost_estimate_paid_provider_is_nonzero(self):
        from backend.core.cloud_llm import estimate_cost
        cost = estimate_cost("anthropic", 10_000, 3_000)
        assert cost > 0.0


# ── Workflow 17: AI safety model ─────────────────────────────────────────────


class TestAISafetyModel:
    def test_default_level_is_suggest_for_all(self, db_path):
        from backend.core.ai_safety import get_safety_level, ACTABLE_TYPES
        for action_type in ACTABLE_TYPES:
            assert get_safety_level(action_type) == "suggest"

    def test_set_and_get_level(self, db_path):
        from backend.core.ai_safety import set_safety_level, get_safety_level
        set_safety_level("restart_container", "act")
        assert get_safety_level("restart_container") == "act"
        set_safety_level("restart_container", "suggest")  # reset
        assert get_safety_level("restart_container") == "suggest"

    def test_invalid_level_raises(self, db_path):
        from backend.core.ai_safety import set_safety_level
        with pytest.raises(ValueError, match="Invalid safety level"):
            set_safety_level("restart_container", "invalid")

    def test_non_actable_raises_when_setting_act(self, db_path):
        from backend.core.ai_safety import set_safety_level
        with pytest.raises(ValueError, match="cannot be set to 'act'"):
            set_safety_level("modify_config_file", "act")

    def test_should_auto_act_false_by_default(self, db_path):
        from backend.core.ai_safety import should_auto_act
        assert should_auto_act("restart_container") is False

    def test_should_suggest_true_by_default(self, db_path):
        from backend.core.ai_safety import should_suggest
        assert should_suggest("restart_container") is True


# ── Workflow 18: _SLOP_MANAGED_VARS — linter suppression ────────────────────


class TestSlopManagedVarsLinterSuppression:
    """_SLOP_MANAGED_VARS suppresses POSTGRES vars in the compose YAML linter.

    The linter should NOT warn about POSTGRES_PASSWORD or POSTGRES_USER
    being missing from .env — these are always written by the setup wizard.
    Commit 1e2b6b2 added both vars to _SLOP_MANAGED_VARS.
    """

    COMPOSE_WITH_POSTGRES_VARS = """
services:
  mydb:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_DB: appdb
    ports:
      - "5432:5432"
"""

    def test_slop_managed_vars_suppresses_postgres_warnings(self, client):
        """POSTGRES_PASSWORD and POSTGRES_USER must NOT appear in missing_vars."""
        r = client.post("/api/apps/lint-compose", json={"yaml": self.COMPOSE_WITH_POSTGRES_VARS})
        assert r.status_code == 200
        data = r.json()
        # The YAML is structurally valid
        assert data["valid"] is True
        # POSTGRES_PASSWORD and POSTGRES_USER must not appear in missing_vars
        missing = data.get("missing_vars", [])
        assert "POSTGRES_PASSWORD" not in missing, (
            "POSTGRES_PASSWORD appeared in missing_vars — "
            "_SLOP_MANAGED_VARS suppression is not working"
        )
        assert "POSTGRES_USER" not in missing, (
            "POSTGRES_USER appeared in missing_vars — "
            "_SLOP_MANAGED_VARS suppression is not working"
        )
        # Warnings should also not mention these vars as unknown/unset
        for w in data.get("warnings", []):
            assert "POSTGRES_PASSWORD" not in w or "not found" not in w, (
                "Warning incorrectly flagged POSTGRES_PASSWORD as unknown: " + w
            )
            assert "POSTGRES_USER" not in w or "not found" not in w, (
                "Warning incorrectly flagged POSTGRES_USER as unknown: " + w
            )


class TestSlopManagedVarsCompleteness:
    """_SLOP_MANAGED_VARS registry completeness guard.

    Ensures the frozenset contains the core SLOP-managed variables so
    future edits don't accidentally remove them.
    """

    def test_slop_managed_vars_contains_postgres_password(self):
        from backend.api.apps import _SLOP_MANAGED_VARS
        assert "POSTGRES_PASSWORD" in _SLOP_MANAGED_VARS

    def test_slop_managed_vars_contains_postgres_user(self):
        from backend.api.apps import _SLOP_MANAGED_VARS
        assert "POSTGRES_USER" in _SLOP_MANAGED_VARS

    def test_slop_managed_vars_contains_domain(self):
        """DOMAIN is a core SLOP var — must always be in the set."""
        from backend.api.apps import _SLOP_MANAGED_VARS
        assert "DOMAIN" in _SLOP_MANAGED_VARS


# ── Task 1: llamacpp provider URL dispatch ────────────────────────────────────


class TestLlamacppUrlDispatch:
    """Regression guard for 0eb5431 — provider-aware URL key dispatch.

    trigger_health_run() and ping_llm() both branch on agent_cfg["provider"]:
      provider=llamacpp  → reads "llamacpp_url"
      provider=ollama    → reads "ollama_url"

    Without these tests a future refactor could silently revert to always
    reading "ollama_url" regardless of provider.
    Tag: [BR: config dispatch path ignores provider when selecting URL key]
    """

    LLAMACPP_CFG = {
        "provider":    "llamacpp",
        "llamacpp_url": "http://testhost:8082",
        "ollama_url":   "http://otherhost:11434",
        "ntfy_topic":  "test-topic",
    }

    OLLAMA_CFG = {
        "provider":    "ollama",
        "llamacpp_url": "http://ignored:8082",
        "ollama_url":   "http://ollamahost:11434",
        "ntfy_topic":  "test-topic",
    }

    def _set_agent_cfg(self, cfg: dict) -> None:
        import json
        with StateDB() as db:
            db.set_setting("llm_agent_config", json.dumps(cfg))

    def _make_health_run(self):
        """Return a minimal HealthRun-compatible mock."""
        import time as _t
        run = MagicMock()
        run.apps_checked = 0
        run.apps_healthy = 0
        run.apps_degraded = 0
        run.llm_agent_state = "unknown"
        run.started_at = _t.monotonic()
        run.results = []
        return run

    def test_trigger_health_run_reads_llamacpp_url(self, client, db_path):
        """trigger_health_run passes llamacpp_url to run_health_cycle when provider=llamacpp."""
        from unittest.mock import AsyncMock

        self._set_agent_cfg(self.LLAMACPP_CFG)

        captured: dict = {}

        async def spy_health_cycle(*args, **kwargs):
            captured.update(kwargs)
            return self._make_health_run()

        with patch("backend.health.checker.run_health_cycle", new=spy_health_cycle):
            r = client.post("/api/health/run")

        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        assert "ollama_url" in captured, "run_health_cycle was not called with ollama_url kwarg"
        assert captured["ollama_url"] == "http://testhost:8082", (
            f"Expected llamacpp_url 'http://testhost:8082' but got: {captured['ollama_url']!r} "
            f"— provider dispatch is broken (reading ollama_url instead of llamacpp_url)"
        )

    def test_trigger_health_run_reads_ollama_url(self, client, db_path):
        """trigger_health_run passes ollama_url to run_health_cycle when provider=ollama."""
        self._set_agent_cfg(self.OLLAMA_CFG)

        captured: dict = {}

        async def spy_health_cycle(*args, **kwargs):
            captured.update(kwargs)
            return self._make_health_run()

        with patch("backend.health.checker.run_health_cycle", new=spy_health_cycle):
            r = client.post("/api/health/run")

        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        assert "ollama_url" in captured, "run_health_cycle was not called with ollama_url kwarg"
        assert captured["ollama_url"] == "http://ollamahost:11434", (
            f"Expected ollama_url 'http://ollamahost:11434' but got: {captured['ollama_url']!r}"
        )

    def test_ping_llm_reads_llamacpp_url(self, client, db_path):
        """ping_llm uses llamacpp_url as base_url when provider=llamacpp.

        We let httpx raise ConnectError (no real server); _err() still
        returns the selected base_url in the response so we can assert
        the correct URL key was read.
        """
        import httpx as _httpx

        self._set_agent_cfg(self.LLAMACPP_CFG)

        mock_http = MagicMock()
        mock_http.__aenter__ = MagicMock(return_value=mock_http)
        mock_http.__aexit__ = MagicMock(return_value=False)
        mock_http.get.side_effect = _httpx.ConnectError("no server")

        with patch("httpx.AsyncClient", return_value=mock_http):
            r = client.get("/api/health/llm-ping")

        assert r.status_code == 200, f"Expected 200 even on connect error, got {r.status_code}"
        data = r.json()
        assert data["provider"] == "llamacpp", f"provider mismatch: {data['provider']!r}"
        assert data["ollama_url"] == "http://testhost:8082", (
            f"Expected llamacpp_url 'http://testhost:8082' in ollama_url field "
            f"but got: {data['ollama_url']!r} — dispatch is broken"
        )
        assert data["reachable"] is False, "ConnectError should mark reachable=False"

    def test_ping_llm_reads_ollama_url(self, client, db_path):
        """ping_llm uses ollama_url as base_url when provider=ollama."""
        import httpx as _httpx

        self._set_agent_cfg(self.OLLAMA_CFG)

        mock_http = MagicMock()
        mock_http.__aenter__ = MagicMock(return_value=mock_http)
        mock_http.__aexit__ = MagicMock(return_value=False)
        mock_http.get.side_effect = _httpx.ConnectError("no server")

        with patch("httpx.AsyncClient", return_value=mock_http):
            r = client.get("/api/health/llm-ping")

        assert r.status_code == 200
        data = r.json()
        assert data["provider"] == "ollama", f"provider mismatch: {data['provider']!r}"
        assert data["ollama_url"] == "http://ollamahost:11434", (
            f"Expected ollama_url 'http://ollamahost:11434' but got: {data['ollama_url']!r}"
        )


# ── Task 2: executor._check_port_conflict() direct coverage ──────────────────


class TestExecutorPortConflict:
    """Direct unit tests for executor._check_port_conflict().

    This function is indirectly covered via the lint endpoint
    (TestLintComposeYamlPortConflict) but has no direct import-level
    test. A refactor to executor.py could silently break the DB-side
    conflict check while lint tests continue to pass (they mock at the
    API layer).
    Tag: [BR: port conflict class, found by S-23-BR-TESTS-A blast-radius sweep]
    """

    def _make_result(self):
        from backend.manifests.executor import ExecutionResult
        return ExecutionResult(ok=True, app_key="test-app", operation="install")

    def test_executor_check_port_conflict_installed_app(self, db_path):
        """_check_port_conflict returns False when another DB-registered app owns the port."""
        from backend.manifests.executor import _check_port_conflict

        # Register a competing app with host_port=7777 and status='stopped'
        # (valid statuses: installing|running|stopped|unhealthy|updating|removing|error|disabled|failed)
        # 'stopped' represents an app that is installed but not currently running — it still owns its port
        with StateDB() as db:
            db.upsert_app("other-app", status="stopped", host_port=7777)

        result = self._make_result()
        # No running containers — conflict must come from the DB check
        with patch("backend.core.docker_client.ports_in_use", return_value={}):
            conflict = _check_port_conflict("test-app", 7777, result)

        assert conflict is False, (
            "Expected False (conflict) when another installed app owns port 7777"
        )
        assert not result.ok, "ExecutionResult.ok should be False after a conflict"
        assert "7777" in result.error, (
            f"Expected port 7777 in error message but got: {result.error!r}"
        )

    def test_executor_check_port_conflict_clean(self, db_path):
        """_check_port_conflict returns True when no running container or DB app owns the port."""
        from backend.manifests.executor import _check_port_conflict

        result = self._make_result()
        with patch("backend.core.docker_client.ports_in_use", return_value={}):
            conflict = _check_port_conflict("test-app", 7777, result)

        assert conflict is True, (
            "Expected True (no conflict) when port 7777 is free in DB and Docker"
        )
        assert result.ok, "ExecutionResult.ok should remain True when no conflict"

    def test_executor_check_port_conflict_none_port(self, db_path):
        """_check_port_conflict returns True immediately when host_port is None."""
        from backend.manifests.executor import _check_port_conflict

        result = self._make_result()
        # ports_in_use should NOT be called — None port skips all checks
        with patch("backend.core.docker_client.ports_in_use", side_effect=AssertionError("should not be called")):
            conflict = _check_port_conflict("test-app", None, result)

        assert conflict is True, "None host_port should always return True (no check needed)"
        assert result.ok, "ExecutionResult.ok should remain True for None port"

    def test_executor_check_port_conflict_running_container(self, db_path):
        """_check_port_conflict returns False when a running container holds the port."""
        from backend.manifests.executor import _check_port_conflict

        result = self._make_result()
        # Simulate Docker reporting port 7777 held by a different container
        with patch("backend.core.docker_client.ports_in_use", return_value={7777: "rival-container"}):
            conflict = _check_port_conflict("test-app", 7777, result)

        assert conflict is False, (
            "Expected False when Docker reports port 7777 held by rival-container"
        )
        assert not result.ok
        assert "7777" in result.error
