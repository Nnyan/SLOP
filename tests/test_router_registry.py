"""Tests for backend.agent.router.registry and backend.agent.router.types.

Covers:
- Registry covers every name in the imported _CLOUD_PROVIDERS + _LOCAL_OAI_PROVIDERS
- Local providers have local=True and cost_per_1k=0.0
- available_providers filters correctly for a sample cfg
- available_providers returns [] for empty cfg
- available_providers returns [] when enabled=False
- Tier is ordered (IntEnum)
- ProviderSpec, RouteRequest, RouteDecision are dataclasses with correct fields
"""

from __future__ import annotations

import pytest

from backend.core.agent import _CLOUD_PROVIDERS, _LOCAL_OAI_PROVIDERS
from backend.agent.router.types import Tier, ProviderSpec, RouteRequest, RouteDecision
from backend.agent.router.registry import PROVIDER_REGISTRY, available_providers


# ---------------------------------------------------------------------------
# Tier tests
# ---------------------------------------------------------------------------

class TestTierOrdering:
    def test_order_simple_lt_standard(self):
        assert Tier.SIMPLE < Tier.STANDARD

    def test_order_standard_lt_complex(self):
        assert Tier.STANDARD < Tier.COMPLEX

    def test_order_complex_lt_reasoning(self):
        assert Tier.COMPLEX < Tier.REASONING

    def test_simple_is_lowest(self):
        assert Tier.SIMPLE == min(Tier)

    def test_reasoning_is_highest(self):
        assert Tier.REASONING == max(Tier)

    def test_int_enum_values(self):
        # Verify ordering is strict numeric
        assert int(Tier.SIMPLE) < int(Tier.STANDARD) < int(Tier.COMPLEX) < int(Tier.REASONING)

    def test_cap_comparison(self):
        # Simulate selector capping: req.max_tier cap
        req = RouteRequest(prompt="hello", max_tier=Tier.STANDARD)
        assert Tier.COMPLEX > req.max_tier
        assert Tier.SIMPLE <= req.max_tier


# ---------------------------------------------------------------------------
# Dataclass shape tests
# ---------------------------------------------------------------------------

class TestDataclassShapes:
    def test_provider_spec_fields(self):
        spec = ProviderSpec(
            name="ollama",
            kind="ollama",
            tiers=frozenset({Tier.SIMPLE}),
            cost_per_1k=0.0,
            local=True,
        )
        assert spec.name == "ollama"
        assert spec.kind == "ollama"
        assert Tier.SIMPLE in spec.tiers
        assert spec.cost_per_1k == 0.0
        assert spec.local is True

    def test_route_request_default_max_tier(self):
        req = RouteRequest(prompt="hello")
        assert req.max_tier == Tier.REASONING

    def test_route_request_custom_max_tier(self):
        req = RouteRequest(prompt="hello", max_tier=Tier.STANDARD)
        assert req.max_tier == Tier.STANDARD

    def test_route_decision_fields(self):
        dec = RouteDecision(tier=Tier.COMPLEX, chain=["groq", "openrouter"], reason="test")
        assert dec.tier == Tier.COMPLEX
        assert dec.chain == ["groq", "openrouter"]
        assert dec.reason == "test"


# ---------------------------------------------------------------------------
# PROVIDER_REGISTRY coverage tests
# ---------------------------------------------------------------------------

class TestRegistryCoverage:
    def test_all_cloud_providers_in_registry(self):
        """Every name in _CLOUD_PROVIDERS must appear in PROVIDER_REGISTRY."""
        missing = _CLOUD_PROVIDERS - set(PROVIDER_REGISTRY.keys())
        assert missing == set(), f"Cloud providers missing from registry: {missing}"

    def test_all_local_oai_providers_in_registry(self):
        """Every name in _LOCAL_OAI_PROVIDERS must appear in PROVIDER_REGISTRY."""
        missing = _LOCAL_OAI_PROVIDERS - set(PROVIDER_REGISTRY.keys())
        assert missing == set(), f"Local OAI providers missing from registry: {missing}"

    def test_ollama_in_registry(self):
        assert "ollama" in PROVIDER_REGISTRY

    def test_llamacpp_in_registry(self):
        assert "llamacpp" in PROVIDER_REGISTRY

    def test_registry_values_are_provider_specs(self):
        for name, spec in PROVIDER_REGISTRY.items():
            assert isinstance(spec, ProviderSpec), f"{name} is not a ProviderSpec"

    def test_registry_names_match_spec_names(self):
        for key, spec in PROVIDER_REGISTRY.items():
            assert key == spec.name, f"Key '{key}' != spec.name '{spec.name}'"


# ---------------------------------------------------------------------------
# Local provider constraints
# ---------------------------------------------------------------------------

class TestLocalProviders:
    LOCAL_EXPECTED = {"ollama", "llamacpp"} | _LOCAL_OAI_PROVIDERS

    def test_local_providers_have_local_true(self):
        for name in self.LOCAL_EXPECTED:
            spec = PROVIDER_REGISTRY[name]
            assert spec.local is True, f"{name} should be local=True"

    def test_local_providers_have_zero_cost(self):
        for name in self.LOCAL_EXPECTED:
            spec = PROVIDER_REGISTRY[name]
            assert spec.cost_per_1k == 0.0, f"{name} should have cost_per_1k=0.0"

    def test_cloud_providers_have_local_false(self):
        for name in _CLOUD_PROVIDERS:
            spec = PROVIDER_REGISTRY[name]
            assert spec.local is False, f"{name} should be local=False"

    def test_local_providers_have_tiers(self):
        for name in self.LOCAL_EXPECTED:
            spec = PROVIDER_REGISTRY[name]
            assert len(spec.tiers) > 0, f"{name} should have at least one tier"


# ---------------------------------------------------------------------------
# available_providers tests
# ---------------------------------------------------------------------------

class TestAvailableProviders:
    def test_empty_cfg_returns_empty(self):
        assert available_providers({}) == []

    def test_none_like_empty_cfg(self):
        # Callers sometimes pass {} after json.loads fails
        assert available_providers({}) == []

    def test_disabled_returns_empty(self):
        cfg = {"provider": "groq", "enabled": False, "api_key": "sk-test"}
        assert available_providers(cfg) == []

    def test_active_provider_included_first(self):
        cfg = {"provider": "groq", "enabled": True, "api_key": "sk-groq-key"}
        result = available_providers(cfg)
        assert len(result) > 0
        assert result[0] == "groq"

    def test_ollama_config_returns_local_providers(self):
        cfg = {"provider": "ollama", "enabled": True, "ollama_url": "http://localhost:11434"}
        result = available_providers(cfg)
        assert "ollama" in result
        # Should not include cloud providers
        for name in result:
            spec = PROVIDER_REGISTRY[name]
            assert spec.local is True, f"Unexpected cloud provider '{name}' in local config result"

    def test_llamacpp_config_returns_local_providers(self):
        cfg = {"provider": "llamacpp", "enabled": True, "llamacpp_url": "http://localhost:8081"}
        result = available_providers(cfg)
        assert "llamacpp" in result
        for name in result:
            spec = PROVIDER_REGISTRY[name]
            assert spec.local is True

    def test_cloud_config_with_api_key_returns_cloud_providers(self):
        cfg = {"provider": "groq", "enabled": True, "api_key": "sk-groq-realkey"}
        result = available_providers(cfg)
        # All returned names should be in registry
        for name in result:
            assert name in PROVIDER_REGISTRY
        # groq must be present
        assert "groq" in result
        # Should include other cloud providers
        cloud_in_result = [n for n in result if not PROVIDER_REGISTRY[n].local]
        assert len(cloud_in_result) > 1

    def test_cloud_config_empty_api_key_returns_only_active(self):
        cfg = {"provider": "groq", "enabled": True, "api_key": ""}
        result = available_providers(cfg)
        # active provider still included even without api_key (provider is configured)
        assert "groq" in result

    def test_unknown_provider_not_in_result(self):
        cfg = {"provider": "nonexistent_provider_xyz", "enabled": True, "api_key": "key"}
        result = available_providers(cfg)
        assert "nonexistent_provider_xyz" not in result

    def test_result_contains_only_registry_keys(self):
        cfg = {"provider": "anthropic", "enabled": True, "api_key": "sk-ant-key"}
        result = available_providers(cfg)
        for name in result:
            assert name in PROVIDER_REGISTRY

    def test_no_duplicates_in_result(self):
        cfg = {"provider": "openrouter", "enabled": True, "api_key": "sk-or-key"}
        result = available_providers(cfg)
        assert len(result) == len(set(result)), "Duplicates found in available_providers result"
