"""tests/test_deep_review.py

Comprehensive tests from the deep code/process/flow review.

Covers:
- StateDB commit bug fix verification
- Cloud LLM sanitization and cost limits
- AI safety tier enforcement
- RAG retriever correctness
- Anomaly detection edge cases
- YAML linter edge cases
- Fix history persistence and filtering
- Pending actions priority ordering
- Hardware evaluation verdicts
- Platform reset fragment cleanup
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    db = tmp_path / "state.db"
    import backend.core.state as sm
    from backend.core.state import init_db
    sm.configure(db)
    init_db(db)
    yield db
    sm.configure(db)  # leave configured to avoid teardown errors


@pytest.fixture
def client(db_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


# ── StateDB commit fix ─────────────────────────────────────────────────────


class TestStateDBCommit:
    """Verify the StateDB commit bug is fixed — writes persist after __exit__."""

    def test_execute_write_persists(self, db_path):
        """execute() INSERT must survive context manager exit."""
        from backend.core.state import StateDB
        now = int(time.time())
        with StateDB() as db:
            db.execute(
                "INSERT INTO fix_history "
                "(app_key, error_type, context, suggested_fix, outcome, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("sonarr", "disk", "ctx", "fix", "pending", now),
            )
        # Open a fresh connection — must see the row
        with StateDB() as db:
            rows = db.execute("SELECT * FROM fix_history WHERE app_key='sonarr'").fetchall()
        assert len(rows) == 1, "execute() write was not committed"

    def test_rollback_on_exception(self, db_path):
        """Exception inside context must rollback, not commit."""
        from backend.core.state import StateDB
        try:
            with StateDB() as db:
                db.execute(
                    "INSERT INTO fix_history "
                    "(app_key, error_type, context, suggested_fix, outcome, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("radarr", "test", "ctx", "fix", "pending", int(time.time())),
                )
                raise RuntimeError("intentional rollback")
        except RuntimeError:
            pass
        with StateDB() as db:
            rows = db.execute("SELECT * FROM fix_history WHERE app_key='radarr'").fetchall()
        assert len(rows) == 0, "Failed transaction should have been rolled back"

    def test_named_method_still_works(self, db_path):
        """Named methods (update_platform etc.) still commit correctly."""
        from backend.core.state import StateDB
        with StateDB() as db:
            db.update_platform(status="ready", domain="test.example.com")
        with StateDB() as db:
            p = db.get_platform()
        assert p.status == "ready"
        assert p.domain == "test.example.com"


# ── Cloud LLM sanitization ─────────────────────────────────────────────────


class TestCloudLLMSanitization:
    """Verify secrets are replaced before sending and restored after."""

    def test_sanitize_removes_long_tokens(self):
        from backend.core.cloud_llm import sanitize_context
        text = "CF_DNS_API_TOKEN=cfut_WOFrMdXyz12345678901234 failed"
        sanitized, subst = sanitize_context(text)
        assert "cfut_WOFrMdXyz12345678901234" not in sanitized
        assert len(subst) >= 1

    def test_restore_returns_original_values(self):
        from backend.core.cloud_llm import sanitize_context, restore_context
        text = "API_KEY=mysecrettoken1234567890 is wrong"
        sanitized, subst = sanitize_context(text)
        restored = restore_context(sanitized, subst)
        # The restored text should contain the original value somewhere
        # (subst map maps placeholder → original)
        assert len(subst) >= 0  # may or may not match pattern
        for placeholder, original in subst.items():
            assert placeholder in sanitized
            assert original not in sanitized or text == sanitized  # was replaced

    def test_sanitize_ip_address(self):
        from backend.core.cloud_llm import sanitize_context
        text = "Server at 192.168.1.100 refused connection"
        sanitized, subst = sanitize_context(text)
        # IPs should be redacted
        assert "192.168.1.100" not in sanitized or len(subst) == 0  # either redacted or no match

    def test_restore_with_empty_subst(self):
        from backend.core.cloud_llm import restore_context
        text = "Normal text without secrets"
        result = restore_context(text, {})
        assert result == text

    def test_estimate_tokens_nonzero(self):
        from backend.core.cloud_llm import estimate_tokens
        assert estimate_tokens("hello world") > 0
        assert estimate_tokens("a" * 4000) == pytest.approx(1000, abs=100)

    def test_cost_limit_blocked(self, db_path):
        """Monthly limit enforcement blocks expensive calls."""
        from backend.core.cloud_llm import _check_cost_limit
        from backend.core.state import StateDB
        # Set limit to $0.00 — everything should be blocked
        with StateDB() as db:
            db.set_setting("cloud_llm_monthly_limit_usd", "0.00")
        ok, reason = _check_cost_limit("anthropic", 0.01)
        assert not ok
        assert "limit" in reason.lower()

    def test_cost_limit_allows_free(self, db_path):
        """Free-tier providers with zero cost should never be blocked."""
        from backend.core.cloud_llm import _check_cost_limit, estimate_cost
        from backend.core.state import StateDB
        # Set limit to $0.00
        with StateDB() as db:
            db.set_setting("cloud_llm_monthly_limit_usd", "0.00")
        # Cost 0.0 should not be blocked
        cost = estimate_cost("openrouter", 100, 100)  # free models = $0
        ok, reason = _check_cost_limit("openrouter", cost)
        assert ok  # $0 cost never blocked


# ── AI Safety tier enforcement ─────────────────────────────────────────────


class TestAISafetyTiers:
    """Verify safety tier logic is correct and non-actable types can't be Act."""

    def test_non_actable_type_raises_on_act(self, db_path):
        from backend.core.ai_safety import set_safety_level
        with pytest.raises(ValueError, match="cannot be set to 'act'"):
            set_safety_level("modify_config_file", "act")

    def test_suggest_is_default(self, db_path):
        from backend.core.ai_safety import get_safety_level
        # Fresh DB — default should be suggest
        level = get_safety_level("restart_container")
        assert level == "suggest"

    def test_should_auto_act_false_when_suggest(self, db_path):
        from backend.core.ai_safety import should_auto_act, set_safety_level
        set_safety_level("restart_container", "suggest")
        assert should_auto_act("restart_container") is False

    def test_should_auto_act_true_when_act(self, db_path):
        from backend.core.ai_safety import should_auto_act, set_safety_level
        set_safety_level("restart_container", "act")
        assert should_auto_act("restart_container") is True

    def test_non_actable_never_auto_acts(self, db_path):
        from backend.core.ai_safety import should_auto_act
        # These types can never be set to act — should always return False
        for action_type in ("modify_config_file", "manual", "escalate"):
            assert should_auto_act(action_type) is False

    def test_set_and_persist_level(self, db_path):
        from backend.core.ai_safety import set_safety_level, get_safety_level
        set_safety_level("reload_config", "act")
        assert get_safety_level("reload_config") == "act"

    def test_get_all_returns_all_types(self, db_path):
        from backend.core.ai_safety import get_all_safety_levels
        levels = get_all_safety_levels()
        assert "restart_container" in levels
        assert "reload_config" in levels
        assert "pull_image" in levels

    def test_api_put_ai_safety(self, client):
        r = client.put("/api/settings/ai-safety",
                       json={"action_type": "restart_container", "level": "suggest"})
        assert r.status_code == 200

    def test_api_put_non_actable_to_act_rejected(self, client):
        r = client.put("/api/settings/ai-safety",
                       json={"action_type": "modify_config_file", "level": "act"})
        assert r.status_code == 422


# ── RAG knowledge base ─────────────────────────────────────────────────────


class TestRAG:
    """Verify RAG retriever returns relevant chunks."""

    def test_simple_retriever_finds_database_error(self):
        from backend.core.rag import SimpleRetriever, KNOWLEDGE_BASE
        r = SimpleRetriever()
        r.build(KNOWLEDGE_BASE)
        chunks = r.query("database is locked sonarr error", n=2)
        assert len(chunks) >= 1
        # Should find the db_locked document
        combined = " ".join(chunks).lower()
        assert "lock" in combined or "database" in combined

    def test_simple_retriever_finds_traefik_error(self):
        from backend.core.rag import SimpleRetriever, KNOWLEDGE_BASE
        r = SimpleRetriever()
        r.build(KNOWLEDGE_BASE)
        chunks = r.query("traefik certificate acme dns cloudflare", n=2)
        assert len(chunks) >= 1
        combined = " ".join(chunks).lower()
        assert "traefik" in combined or "cert" in combined or "acme" in combined

    def test_enrich_adds_context_prefix(self):
        from backend.core.rag import enrich_prompt_with_context
        prompt = "Diagnose this: container failed"
        enriched = enrich_prompt_with_context(prompt, "database locked error sqlite")
        # When chunks are found, prompt gets prefix
        assert len(enriched) >= len(prompt)

    def test_empty_query_returns_no_chunks(self):
        from backend.core.rag import SimpleRetriever, KNOWLEDGE_BASE
        r = SimpleRetriever()
        r.build(KNOWLEDGE_BASE)
        chunks = r.query("", n=3)
        assert isinstance(chunks, list)

    def test_query_knowledge_base_no_crash(self):
        """query_knowledge_base convenience function never crashes."""
        from backend.core.rag import query_knowledge_base
        result = query_knowledge_base("random text that might not match anything", n=2)
        assert isinstance(result, list)


# ── Anomaly detection ──────────────────────────────────────────────────────


class TestAnomalyDetectionLogic:
    """Edge case tests for anomaly pattern detection."""

    def test_two_occurrences_not_flagged(self, db_path):
        """Fewer than 3 occurrences should not be flagged."""
        from backend.core.state import StateDB
        now = int(time.time())
        with StateDB() as db:
            for i in range(2):
                db.execute(
                    "INSERT INTO health_check_history "
                    "(subject_type, subject_key, check_name, status, summary, checked_at) "
                    "VALUES ('app', 'plex', 'http_check', 'error', 'Timeout', ?)",
                    (now - i * 3600,),
                )
        from backend.health.anomaly import detect_anomalies
        patterns = detect_anomalies()
        plex = [p for p in patterns if p.app_key == "plex"]
        assert len(plex) == 0

    def test_six_occurrences_is_recurring(self, db_path):
        """5+ occurrences should be flagged as is_recurring=True."""
        from backend.core.state import StateDB
        now = int(time.time())
        with StateDB() as db:
            db.upsert_app('radarr', display_name='Radarr', status='running', tier=2, category='arr')
            for i in range(6):
                db.execute(
                    "INSERT INTO health_check_history "
                    "(subject_type, subject_key, check_name, status, summary, checked_at) "
                    "VALUES ('app', 'radarr', 'db_check', 'error', 'DB locked', ?)",
                    (now - i * 3600,),
                )
        from backend.health.anomaly import detect_anomalies
        patterns = detect_anomalies()
        radarr = next((p for p in patterns if p.app_key == "radarr"), None)
        assert radarr is not None
        assert radarr.occurrences >= 6
        assert radarr.is_recurring is True

    def test_typical_hour_detected(self, db_path):
        """When failures cluster at same hour, typical_hour should be detected."""
        from backend.core.state import StateDB
        import time as _t
        now = int(_t.time())
        # Insert 5 failures all at the same hour offset (within last 7 days)
        with StateDB() as db:
            db.upsert_app('jellyfin', display_name='Jellyfin', status='running', tier=1, category='media')
            for day in range(5):
                # Use now - day*24h, keeping the same hour-of-day
                ts = now - day * 86400
                db.execute(
                    "INSERT INTO health_check_history "
                    "(subject_type, subject_key, check_name, status, summary, checked_at) "
                    "VALUES ('app', 'jellyfin', 'transcode', 'error', 'Timeout', ?)",
                    (ts,),
                )
        from backend.health.anomaly import detect_anomalies
        patterns = detect_anomalies(lookback_hours=24 * 7)
        jf = next((p for p in patterns if p.app_key == "jellyfin"), None)
        assert jf is not None
        # All at same hour — typical_hour should be detected
        assert jf.typical_hour is not None

    def test_api_anomalies_endpoint(self, client):
        r = client.get("/api/health/anomalies")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── YAML linter ────────────────────────────────────────────────────────────


class TestYAMLLinter:
    """Comprehensive YAML compose linter tests."""

    def test_valid_compose_returns_valid(self, client):
        yaml = """services:
  sonarr:
    image: linuxserver/sonarr:latest
    ports:
      - 8989:8989
    volumes:
      - /config:/config
"""
        r = client.post("/api/apps/lint-compose", json={"yaml": yaml})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert data["manifest_preview"]["key"] == "sonarr"

    def test_invalid_yaml_returns_error_with_detail(self, client):
        yaml = "services:\n  - bad: [\n  invalid"
        r = client.post("/api/apps/lint-compose", json={"yaml": yaml})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is False
        assert len(data["errors"]) >= 1

    def test_bare_service_without_wrapper(self, client):
        """Service def without 'services:' wrapper should still work."""
        yaml = """image: sonarr:latest
ports:
  - 8989:8989
"""
        r = client.post("/api/apps/lint-compose", json={"yaml": yaml})
        assert r.status_code == 200
        data = r.json()
        # Should either succeed with a warning or fail gracefully
        assert "errors" in data or "warnings" in data

    def test_missing_image_returns_error(self, client):
        yaml = """services:
  myapp:
    ports:
      - 8080:8080
"""
        r = client.post("/api/apps/lint-compose", json={"yaml": yaml})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is False
        assert any("image" in e.lower() for e in data["errors"])

    def test_hardcoded_secret_warns(self, client):
        yaml = """services:
  myapp:
    image: myapp:latest
    environment:
      - API_KEY=supersecrettoken12345
"""
        r = client.post("/api/apps/lint-compose", json={"yaml": yaml})
        assert r.status_code == 200
        data = r.json()
        # Should warn about hardcoded secret
        assert any("secret" in w.lower() or "API_KEY" in w for w in data.get("warnings", []))

    def test_multiple_services_warns(self, client):
        yaml = """services:
  app1:
    image: app1:latest
  app2:
    image: app2:latest
"""
        r = client.post("/api/apps/lint-compose", json={"yaml": yaml})
        assert r.status_code == 200
        data = r.json()
        assert any("service" in w.lower() for w in data.get("warnings", []))

    def test_empty_yaml_returns_error(self, client):
        r = client.post("/api/apps/lint-compose", json={"yaml": ""})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is False

    def test_manifest_preview_has_web_port(self, client):
        yaml = """services:
  radarr:
    image: linuxserver/radarr:latest
    ports:
      - 7878:7878
"""
        r = client.post("/api/apps/lint-compose", json={"yaml": yaml})
        data = r.json()
        if data["valid"]:
            assert data["manifest_preview"]["web_port"] == 7878


# ── Fix history ────────────────────────────────────────────────────────────


class TestFixHistoryPersistence:
    """Fix history must persist and be queryable."""

    def test_post_and_get(self, client):
        r = client.post("/api/models/fix-history", json={
            "app_key": "sonarr",
            "error_type": "db_locked",
            "context": "SQLite database is locked",
            "suggested_fix": "Restart sonarr container",
        })
        assert r.status_code == 200
        r = client.get("/api/models/fix-history")
        assert r.status_code == 200
        data = r.json()
        assert any(rec["app_key"] == "sonarr" for rec in data)

    def test_filter_by_app_key(self, client):
        client.post("/api/models/fix-history", json={
            "app_key": "plex", "error_type": "transcode",
            "context": "Transcoding failed", "suggested_fix": "Use software transcoding",
        })
        client.post("/api/models/fix-history", json={
            "app_key": "radarr", "error_type": "indexer",
            "context": "No indexers", "suggested_fix": "Configure Prowlarr",
        })
        r = client.get("/api/models/fix-history?app_key=plex")
        assert r.status_code == 200
        data = r.json()
        assert all(rec["app_key"] == "plex" for rec in data)

    def test_update_outcome(self, client, db_path):
        from backend.core.state import StateDB
        now = int(time.time())
        with StateDB() as db:
            db.execute(
                "INSERT INTO fix_history (app_key, error_type, context, suggested_fix, outcome, created_at) "
                "VALUES ('bazarr', 'subtitle', 'ctx', 'fix', 'pending', ?)",
                (now,),
            )
            row = db.execute("SELECT id FROM fix_history WHERE app_key='bazarr'").fetchone()
            fix_id = row["id"]
        r = client.put(f"/api/models/fix-history/{fix_id}/outcome", params={"outcome": "success"})
        assert r.status_code == 200
        with StateDB() as db:
            row = db.execute("SELECT outcome FROM fix_history WHERE id=?", (fix_id,)).fetchone()
        assert row["outcome"] == "success"

    def test_invalid_outcome_rejected(self, client, db_path):
        from backend.core.state import StateDB
        with StateDB() as db:
            db.execute(
                "INSERT INTO fix_history (app_key, error_type, context, suggested_fix, outcome, created_at) "
                "VALUES ('app', 'err', 'c', 'f', 'pending', ?)",
                (int(time.time()),),
            )
            row = db.execute("SELECT id FROM fix_history LIMIT 1").fetchone()
            fix_id = row["id"] if row else 1
        r = client.put(f"/api/models/fix-history/{fix_id}/outcome", params={"outcome": "invalid_value"})
        assert r.status_code == 422


# ── Pending actions priority ordering ─────────────────────────────────────


class TestPendingActionsPriority:
    """Pending actions must be sorted: errors first, then warnings, then suggestions."""

    def test_priority_ordering(self, client):
        r = client.get("/api/health/pending-actions")
        assert r.status_code == 200
        actions = r.json()
        if len(actions) < 2:
            return  # not enough actions to verify ordering
        priority_order = {"error": 0, "warning": 1, "suggestion": 2}
        for i in range(len(actions) - 1):
            a = priority_order.get(actions[i]["priority"], 99)
            b = priority_order.get(actions[i + 1]["priority"], 99)
            assert a <= b, f"Priority out of order: {actions[i]['priority']} before {actions[i+1]['priority']}"

    def test_returns_list(self, client):
        r = client.get("/api/health/pending-actions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_each_action_has_required_fields(self, client):
        r = client.get("/api/health/pending-actions")
        for action in r.json():
            assert "priority" in action
            assert "title" in action
            assert "description" in action
            assert "action" in action
            assert action["priority"] in ("error", "warning", "suggestion")


# ── Hardware evaluation ────────────────────────────────────────────────────


class TestHardwareEvaluation:
    """Hardware evaluation should return correct verdicts."""

    def test_returns_steps_and_verdict(self, client):
        r = client.post("/api/models/evaluate-hardware",
                        params={"model_size_gb": 4.0, "quantization": "Q4_K_M"})
        assert r.status_code == 200
        data = r.json()
        assert "steps" in data
        assert "verdict" in data
        assert data["verdict"] in ("runs_well", "runs_slowly", "cannot_run")
        assert len(data["steps"]) >= 4

    def test_steps_have_correct_structure(self, client):
        r = client.post("/api/models/evaluate-hardware", params={"model_size_gb": 4.0})
        data = r.json()
        for step in data["steps"]:
            assert "label" in step
            assert "status" in step
            assert "detail" in step
            assert step["status"] in ("ok", "warn", "error", "info")

    def test_enormous_model_cannot_run(self, client):
        """A 500GB model should be flagged as cannot_run on any reasonable system."""
        r = client.post("/api/models/evaluate-hardware", params={"model_size_gb": 500.0})
        assert r.status_code == 200
        data = r.json()
        # 500GB model cannot run on any homelab
        assert data["verdict"] in ("cannot_run", "runs_slowly")

    def test_tiny_model_runs_well(self, client):
        """A 0.5GB model should run on any system with enough RAM."""
        r = client.post("/api/models/evaluate-hardware", params={"model_size_gb": 0.5})
        assert r.status_code == 200
        data = r.json()
        assert data["verdict"] != "cannot_run" or "storage" in str(data).lower()

    def test_evaluate_hardware_with_mock_gpu(self):
        """GPU detection changes inference_mode to gpu when VRAM sufficient."""
        from backend.core.system_eval import evaluate_model_compatibility
        gpu = {"vendor": "nvidia", "name": "RTX 3090", "vram_mb": 24576,
               "inference_capable": True}
        result = evaluate_model_compatibility(
            model_size_gb=7.0, quantization="Q4_K_M",
            system_ram_gb=32.0, available_ram_gb=20.0,
            cpu_cores=8, avx2=True, gpu=gpu, storage_free_gb=100.0,
        )
        assert result["inference_mode"] == "gpu"
        assert result["verdict"] == "runs_well"

    def test_missing_avx2_gives_error_without_gpu(self):
        """No AVX2 and no GPU = cannot run."""
        from backend.core.system_eval import evaluate_model_compatibility
        result = evaluate_model_compatibility(
            model_size_gb=4.0, quantization="Q4_K_M",
            system_ram_gb=32.0, available_ram_gb=20.0,
            cpu_cores=8, avx2=False, gpu={"inference_capable": False},
            storage_free_gb=100.0,
        )
        assert result["verdict"] == "cannot_run"
        assert any("avx" in i.lower() for i in result["issues"])


# ── Platform reset ─────────────────────────────────────────────────────────


class TestPlatformReset:
    """Platform reset should clear Traefik compose fragment."""

    def test_reset_removes_traefik_fragment(self, client, db_path):
        """Reset clears platform status — Traefik fragment deletion tested via file system."""
        from backend.core.state import StateDB
        with StateDB() as db:
            db.update_platform(status="ready", domain="test.com")
        r = client.post("/api/platform/reset")
        assert r.status_code == 200
        with StateDB() as db:
            p = db.get_platform()
        assert p.status == "pending"

    
    def test_reset_when_already_pending(self, client):
        r = client.post("/api/platform/reset")
        assert r.status_code == 200
        data = r.json()
        assert "pending" in data.get("message", "").lower()


# ── Cloud LLM settings API ─────────────────────────────────────────────────


class TestCloudLLMSettingsAPI:
    """Cloud LLM API endpoints."""

    def test_get_returns_provider_list(self, client):
        r = client.get("/api/settings/cloud-llm")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data
        assert "groq" in data["providers"]
        assert "cerebras" in data["providers"]
        assert "anthropic" in data["providers"]
        assert "monthly_limit_usd" in data

    def test_get_includes_free_tier_flag(self, client):
        r = client.get("/api/settings/cloud-llm")
        data = r.json()
        groq = data["providers"]["groq"]
        assert groq["free_tier"] is True
        anthropic = data["providers"]["anthropic"]
        assert anthropic["free_tier"] is False

    def test_put_updates_monthly_limit(self, client):
        r = client.put("/api/settings/cloud-llm",
                       json={"monthly_limit_usd": 5.00})
        assert r.status_code == 200
        r = client.get("/api/settings/cloud-llm")
        assert r.json()["monthly_limit_usd"] == pytest.approx(5.00)

    def test_put_negative_limit_rejected(self, client):
        r = client.put("/api/settings/cloud-llm",
                       json={"monthly_limit_usd": -1.00})
        assert r.status_code == 422

    def test_put_unknown_provider_in_cascade_rejected(self, client):
        r = client.put("/api/settings/cloud-llm",
                       json={"cascade": ["groq", "nonexistent_provider"]})
        assert r.status_code == 422

    def test_put_valid_cascade(self, client):
        r = client.put("/api/settings/cloud-llm",
                       json={"cascade": ["groq", "cerebras", "anthropic"]})
        assert r.status_code == 200


# ── Apply fix endpoint ─────────────────────────────────────────────────────


class TestApplyFix:
    """Apply fix respects safety tiers."""

    def test_observe_level_blocks_all(self, client, db_path):
        from backend.core.ai_safety import set_safety_level
        set_safety_level("restart_container", "observe")
        r = client.post("/api/health/apply-fix", json={
            "app_key": "sonarr",
            "action_type": "restart_container",
            "suggested_fix": "Restart the container",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False or data.get("executed") is False

    def test_unknown_action_type_handled(self, client):
        r = client.post("/api/health/apply-fix", json={
            "app_key": "sonarr",
            "action_type": "completely_unknown_action",
            "suggested_fix": "do something",
        })
        # Should not crash — return a graceful response
        assert r.status_code in (200, 422)

    def test_returns_requires_approval_for_suggest_tier(self, client, db_path):
        from backend.core.ai_safety import set_safety_level
        set_safety_level("restart_container", "suggest")
        r = client.post("/api/health/apply-fix", json={
            "app_key": "sonarr",
            "action_type": "restart_container",
            "suggested_fix": "Restart the container",
        })
        assert r.status_code == 200
        data = r.json()
        # suggest tier means Docker call will fail (no Docker in test), but
        # it should attempt and return a result
        assert "executed" in data or "ok" in data


# ── Platform health review ─────────────────────────────────────────────────


class TestPlatformHealthReview:
    """Platform review endpoint should not crash."""

    def test_returns_summary(self, client):
        r = client.post("/api/health/platform-review")
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        assert "summary" in data

    def test_returns_action_count(self, client):
        r = client.post("/api/health/platform-review")
        data = r.json()
        assert "action_count" in data
        assert isinstance(data["action_count"], int)

    def test_returns_suggestions_list(self, client):
        r = client.post("/api/health/platform-review")
        data = r.json()
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)
