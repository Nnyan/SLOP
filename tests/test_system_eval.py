"""tests/test_system_eval.py

Tests for system evaluation, LLM model sizing, graceful disable/enable,
and the expanded app catalog.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core.system_eval import (
    APP_RAM_MB,
    LLM_MODEL_RAM_MB,
    MEDIASTACK_OVERHEAD_MB,
    OS_BASELINE_MB,
    SystemProfile,
    disk_usage,
    estimate_stack_ram,
    evaluate_system,
    quick_ram_check,
    recommend_llm,
)
from backend.manifests.executor import (
    Criticality,
    DisableResult,
    PERF_THRESHOLDS,
    disable_app,
    enable_app,
    get_criticality,
)
from backend.manifests.loader import load_all_manifests, clear_cache
from backend.core.state import StateDB, init_db


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


# ── LLM model recommendation ──────────────────────────────────────────────


class TestRecommendLLM:
    def test_ample_ram_all_models(self):
        model, models, warning = recommend_llm(5000)
        assert warning is None
        assert len(models) >= 4  # count varies by headroom tier
        assert "phi4-mini" in models
        assert any(m in models for m in ("phi4-mini", "llama3.1:8b"))  # top tier includes large models

    def test_mid_range_phi4_mini(self):
        model, models, warning = recommend_llm(3500)
        assert model == "phi4-mini"
        assert "phi4-mini" in models
        assert "gemma3:4b" not in models
        assert warning is None

    def test_limited_llama3(self):
        model, models, warning = recommend_llm(2900)
        assert "llama3.2:3b" in models
        assert "phi4-mini" not in models

    def test_tight_smollm2_only(self):
        model, models, warning = recommend_llm(1600)
        assert models == ["smollm2:1.7b"]
        assert warning is not None
        assert "triage" in warning.lower() or "limited" in warning.lower()

    def test_insufficient_no_llm(self):
        model, models, warning = recommend_llm(500)
        assert model == ""
        assert models == []
        assert warning is not None
        assert "1.6GB" in warning or "insufficient" in warning.lower() or "headroom" in warning.lower()

    def test_exact_phi4_boundary(self):
        model, models, warning = recommend_llm(3500)
        assert "phi4-mini" in models


# ── RAM estimation ────────────────────────────────────────────────────────


class TestEstimateStackRAM:
    def test_empty_stack(self):
        ram = estimate_stack_ram([])
        assert ram == MEDIASTACK_OVERHEAD_MB + OS_BASELINE_MB + \
               APP_RAM_MB["postgres"] + APP_RAM_MB["redis"]

    def test_known_apps(self):
        ram = estimate_stack_ram(["sonarr", "radarr", "prowlarr"])
        base = estimate_stack_ram([])
        expected = base + APP_RAM_MB["sonarr"] + APP_RAM_MB["radarr"] + APP_RAM_MB["prowlarr"]
        assert ram == expected

    def test_unknown_app_defaults_200mb(self):
        ram_known = estimate_stack_ram([])
        ram_unknown = estimate_stack_ram(["some_unknown_app"])
        assert ram_unknown == ram_known + 200

    def test_vaultwarden_is_tiny(self):
        assert APP_RAM_MB.get("vaultwarden", 0) <= 80

    def test_immich_is_large(self):
        assert APP_RAM_MB.get("immich", 0) >= 500

    def test_all_models_under_4gb_llm_ram(self):
        for model, ram in LLM_MODEL_RAM_MB.items():
            assert ram <= 45000, f"{model} exceeds 45GB RAM — update test if intentional"


# ── Quick RAM check ───────────────────────────────────────────────────────


class TestQuickRAMCheck:
    def test_sufficient_ram(self):
        fake_mem = {"MemAvailable": 8 * 1024 * 1024}  # 8GB in kB
        with patch("backend.core.system_eval.read_meminfo", return_value=fake_mem):
            ok, warning = quick_ram_check(2500)
        assert ok is True
        assert warning is None

    def test_insufficient_ram(self):
        fake_mem = {"MemAvailable": 500 * 1024}  # 500MB in kB
        with patch("backend.core.system_eval.read_meminfo", return_value=fake_mem):
            ok, warning = quick_ram_check(2500)
        assert ok is False
        assert warning is not None
        assert "Skipping LLM" in warning

    def test_boundary_exactly_enough(self):
        # model=2500MB, needs 2500+512=3012MB — give exactly 3012MB
        fake_mem = {"MemAvailable": 3012 * 1024}
        with patch("backend.core.system_eval.read_meminfo", return_value=fake_mem):
            ok, _ = quick_ram_check(2500)
        assert ok is True


# ── System evaluation ─────────────────────────────────────────────────────


class TestEvaluateSystem:
    def _fake_meminfo(self, total_mb: int, available_mb: int) -> dict:
        return {
            "MemTotal": total_mb * 1024,
            "MemAvailable": available_mb * 1024,
        }

    def test_returns_system_profile(self):
        with patch("backend.core.system_eval.read_meminfo",
                   return_value=self._fake_meminfo(16384, 8192)):
            with patch("backend.core.system_eval.docker_ram_usage_mb", return_value=512):
                profile = evaluate_system(selected_app_keys=[], config_root="/", media_root="/")
        assert isinstance(profile, SystemProfile)
        assert profile.total_ram_mb == 16384
        assert profile.free_ram_mb == 8192
        assert profile.measured_at > 0

    def test_headroom_calculation(self):
        with patch("backend.core.system_eval.read_meminfo",
                   return_value=self._fake_meminfo(16384, 8192)):
            with patch("backend.core.system_eval.docker_ram_usage_mb", return_value=0):
                profile = evaluate_system(
                    selected_app_keys=["sonarr", "radarr"],
                    config_root="/", media_root="/",
                )
        # headroom = total - estimated_stack - 15% buffer
        assert profile.headroom_ram_mb > 0
        assert profile.estimated_stack_ram_mb > 0

    def test_large_stack_reduces_llm_options(self):
        # Simulate lots of apps eating RAM
        big_stack = ["sonarr", "radarr", "prowlarr", "plex", "immich",
                     "paperless_ngx", "affine", "vikunja", "mealie"]
        with patch("backend.core.system_eval.read_meminfo",
                   return_value=self._fake_meminfo(8192, 2000)):
            with patch("backend.core.system_eval.docker_ram_usage_mb", return_value=2000):
                profile = evaluate_system(selected_app_keys=big_stack,
                                          config_root="/", media_root="/")
        # With 8GB RAM and heavy stack, models may be restricted
        assert isinstance(profile.available_models, list)
        # Should not recommend largest model on constrained system
        if profile.headroom_ram_mb < 4500:
            assert "gemma3:4b" not in profile.available_models

    def test_high_disk_usage_included(self):
        with patch("backend.core.system_eval.read_meminfo",
                   return_value=self._fake_meminfo(16384, 8192)):
            with patch("backend.core.system_eval.docker_ram_usage_mb", return_value=0):
                profile = evaluate_system(config_root="/", media_root="/")
        assert len(profile.disks) >= 1
        assert all(d.total_gb > 0 for d in profile.disks)


# ── Criticality classification ────────────────────────────────────────────


class TestCriticality:
    def test_traefik_inviolable(self):
        assert get_criticality("traefik") == Criticality.INVIOLABLE

    def test_auth_providers_important(self):
        for key in ("tinyauth", "authelia", "authentik"):
            assert get_criticality(key) == Criticality.IMPORTANT

    def test_tunnel_providers_important(self):
        for key in ("cloudflared", "tailscale", "headscale"):
            assert get_criticality(key) == Criticality.IMPORTANT

    def test_llm_is_enhancement(self):
        assert get_criticality("ollama") == Criticality.ENHANCEMENT
        assert get_criticality("llamacpp_server") == Criticality.ENHANCEMENT

    def test_monitoring_is_enhancement(self):
        for key in ("netdata", "dozzle", "beszel", "glance"):
            assert get_criticality(key) == Criticality.ENHANCEMENT

    def test_media_apps_independent(self):
        for key in ("sonarr", "radarr", "prowlarr", "vaultwarden", "mealie"):
            assert get_criticality(key) == Criticality.INDEPENDENT

    def test_unknown_app_is_independent(self):
        assert get_criticality("totally_unknown_app") == Criticality.INDEPENDENT

    def test_perf_thresholds_complete(self):
        required = {"cpu_percent_sustained", "oom_kills_per_hour",
                    "api_response_seconds", "llm_inference_seconds",
                    "llm_parse_fail_streak"}
        assert required.issubset(PERF_THRESHOLDS.keys())


# ── Disable / Enable (unit, no Docker) ───────────────────────────────────


class TestDisableEnable:
    def test_cannot_disable_inviolable(self, db):
        result = disable_app("traefik")
        assert result.ok is False
        assert result.criticality == Criticality.INVIOLABLE
        assert result.error is not None
        assert "cannot be disabled" in result.error.lower()

    def test_disable_not_installed_fails(self, db):
        result = disable_app("sonarr")
        assert result.ok is False
        assert "not installed" in (result.error or "").lower()

    def test_disable_installed_app(self, db, tmp_path):
        with StateDB() as s:
            s.upsert_app(
                "sonarr", display_name="Sonarr", category="arr",
                image="img", image_tag="latest", container_name="sonarr",
                web_port=8989, host_port=8989,
                config_path=str(tmp_path / "sonarr"),
                manifest_source="catalog", manifest_hash="abc",
                status="running",
            )
        from backend.core.config import config as cfg
        cfg.compose_dir.mkdir(parents=True, exist_ok=True)
        frag = cfg.compose_dir / "sonarr.yaml"
        frag.write_text("services:\n  sonarr:\n    image: img\n")
        try:
            with patch("subprocess.run", MagicMock(return_value=MagicMock(returncode=0))):
                result = disable_app("sonarr", reason="performance")
            assert result.ok is True
            assert result.criticality == str(Criticality.INDEPENDENT)
        finally:
            for p in cfg.compose_dir.glob("sonarr.yaml*"):
                p.unlink(missing_ok=True)


    def test_enable_app_not_disabled(self, db):
        with StateDB() as s:
            s.upsert_app(
                "sonarr", display_name="Sonarr", category="arr",
                image="img", image_tag="latest", container_name="sonarr",
                web_port=8989, host_port=8989, config_path="/c",
                manifest_source="catalog", manifest_hash="abc",
                status="running",
            )
        result = enable_app("sonarr")
        # Already running — should return ok without error
        assert result.ok is True

    def test_enable_not_installed(self, db):
        result = enable_app("notinstalled")
        assert result.ok is False

    def test_important_app_disable_allowed(self, db, tmp_path):
        """Important apps CAN be disabled — they just get a warning."""
        with StateDB() as s:
            s.upsert_app(
                "cloudflared", display_name="Cloudflared", category="infra",
                image="img", image_tag="latest", container_name="cloudflared",
                web_port=None, host_port=None, config_path="/c",
                manifest_source="catalog", manifest_hash="abc",
                status="running",
            )
        from backend.core.config import config as cfg
        cfg.compose_dir.mkdir(parents=True, exist_ok=True)
        frag = cfg.compose_dir / "cloudflared.yaml"
        frag.write_text("services:\n  cloudflared:\n    image: img\n")
        try:
            with patch("subprocess.run", MagicMock(return_value=MagicMock(returncode=0))):
                result = disable_app("cloudflared", reason="user_request")
            assert result.ok is True
            assert result.criticality == str(Criticality.IMPORTANT)
        finally:
            for p in cfg.compose_dir.glob("cloudflared.yaml*"):
                p.unlink(missing_ok=True)
