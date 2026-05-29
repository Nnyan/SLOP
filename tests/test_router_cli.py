"""Tests for backend.agent.router.decisions and backend.agent.router.cli.

Covers:
- log_decision runs without error on a sample RouteDecision
- log_decision emits correct structlog fields (tier, chain, reason)
- cmd_status prints the provider registry (provider names present)
- cmd_status prints the "available providers" section header
- cmd_status handles empty / unconfigured state gracefully
- Dry-run decision path is guarded: skipped when selector is absent
"""

from __future__ import annotations

import io
import sys
from unittest.mock import patch, MagicMock

import pytest

from backend.agent.router.types import Tier, RouteDecision, RouteRequest
from backend.agent.router.decisions import log_decision
from backend.agent.router.registry import PROVIDER_REGISTRY


# ---------------------------------------------------------------------------
# log_decision tests
# ---------------------------------------------------------------------------

class TestLogDecision:
    def test_runs_without_error(self):
        """log_decision must not raise on a valid RouteDecision."""
        decision = RouteDecision(
            tier=Tier.STANDARD,
            chain=["ollama", "groq"],
            reason="standard complexity; local provider preferred",
        )
        # Should complete without raising
        log_decision(decision)

    def test_emits_correct_fields(self, capsys):
        """log_decision emits tier, chain, reason via structlog."""
        decision = RouteDecision(
            tier=Tier.SIMPLE,
            chain=["ollama"],
            reason="simple prompt; cheapest local path",
        )
        # Use a mock structlog logger to capture bound calls
        with patch("backend.agent.router.decisions.log") as mock_log:
            log_decision(decision)
            mock_log.info.assert_called_once()
            call_kwargs = mock_log.info.call_args
            # Positional arg: event name
            assert call_kwargs.args[0] == "router.decision"
            assert call_kwargs.kwargs["tier"] == "SIMPLE"
            assert call_kwargs.kwargs["chain"] == ["ollama"]
            assert "simple" in call_kwargs.kwargs["reason"].lower()

    def test_all_tiers_accepted(self):
        """log_decision accepts all four Tier values."""
        for tier in Tier:
            decision = RouteDecision(
                tier=tier,
                chain=["provider-a"],
                reason="test",
            )
            log_decision(decision)  # must not raise

    def test_empty_chain_accepted(self):
        """log_decision does not raise when chain is empty."""
        decision = RouteDecision(
            tier=Tier.REASONING,
            chain=[],
            reason="no providers available",
        )
        log_decision(decision)


# ---------------------------------------------------------------------------
# CLI: status output tests
# ---------------------------------------------------------------------------

class TestCmdStatus:
    """Capture stdout from cmd_status and assert key content."""

    def _run_status(self, cfg: dict | None = None) -> str:
        """Run cmd_status with a mocked llm_agent_config and return stdout."""
        if cfg is None:
            cfg = {}
        buf = io.StringIO()
        from backend.agent.router.cli import cmd_status
        import argparse

        args = argparse.Namespace(command="status")
        with patch(
            "backend.agent.router.cli._fetch_llm_agent_config",
            return_value=cfg,
        ):
            with patch("sys.stdout", buf):
                cmd_status(args)
        return buf.getvalue()

    def test_registry_header_present(self):
        output = self._run_status()
        assert "Provider Registry" in output

    def test_registry_lists_ollama(self):
        """ollama should appear in the registry section."""
        output = self._run_status()
        assert "ollama" in output

    def test_registry_lists_anthropic(self):
        """anthropic should appear in the registry section (cloud provider)."""
        output = self._run_status()
        assert "anthropic" in output

    def test_registry_contains_all_providers(self):
        """All registered providers must appear in status output."""
        output = self._run_status()
        for name in PROVIDER_REGISTRY:
            assert name in output, f"Provider {name!r} missing from status output"

    def test_available_providers_header_present(self):
        output = self._run_status()
        assert "Available Providers" in output

    def test_empty_config_shows_none(self):
        """Empty llm_agent_config → 'none' notice in available section."""
        output = self._run_status(cfg={})
        assert "none" in output.lower() or "(none" in output

    def test_configured_provider_appears(self):
        """When a provider is configured, it shows up in the available section."""
        cfg = {"provider": "ollama", "enabled": True, "ollama_url": "http://localhost:11434"}
        output = self._run_status(cfg=cfg)
        # ollama should appear at least twice: registry + available
        assert output.count("ollama") >= 2

    def test_disabled_config_shows_none(self):
        """enabled=False → no providers available."""
        cfg = {"provider": "ollama", "enabled": False}
        output = self._run_status(cfg=cfg)
        assert "none" in output.lower() or "(none" in output


# ---------------------------------------------------------------------------
# CLI: dry-run decision tests (guarded by importorskip)
# ---------------------------------------------------------------------------

class TestCmdStatusDryRun:
    """Dry-run decision assertions — skipped if selector is absent."""

    def _run_with_mock_selector(self, providers: list[str]) -> str:
        """Run cmd_status with selector/scoring mocked and return stdout."""
        selector_mod = pytest.importorskip("backend.agent.router.selector")
        scoring_mod = pytest.importorskip("backend.agent.router.scoring")

        from backend.agent.router.cli import cmd_status
        import argparse

        buf = io.StringIO()
        args = argparse.Namespace(command="status")
        cfg = {"provider": "ollama", "enabled": True}

        with patch("backend.agent.router.cli._fetch_llm_agent_config", return_value=cfg):
            with patch("sys.stdout", buf):
                cmd_status(args)
        return buf.getvalue()

    def test_dry_run_section_present(self):
        output = self._run_with_mock_selector(["ollama"])
        assert "Dry-run" in output or "dry-run" in output.lower()

    def test_dry_run_shows_tier(self):
        output = self._run_with_mock_selector(["ollama"])
        # One of the tier names should appear
        tier_names = {t.name for t in Tier}
        assert any(name in output for name in tier_names), (
            "Expected at least one Tier name in dry-run output"
        )


# ---------------------------------------------------------------------------
# CLI: main() entry point
# ---------------------------------------------------------------------------

class TestCliMain:
    def test_status_command_exits_zero(self):
        from backend.agent.router.cli import main
        with patch("backend.agent.router.cli._fetch_llm_agent_config", return_value={}):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                rc = main(["status"])
        assert rc == 0

    def test_no_command_exits_nonzero(self):
        from backend.agent.router.cli import main
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = main([])
        assert rc == 1
