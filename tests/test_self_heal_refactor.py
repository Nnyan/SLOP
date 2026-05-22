"""Regression tests for the _attempt_self_heal refactor (step 2.7.a).

The function previously had cyclomatic complexity 16 (above Core Rule
8.1's threshold of 15). The refactor extracts the 6 action branches
into individual `_heal_<action>` helpers + an action-dispatch table
`_HEAL_DISPATCHERS`. The orchestrator drops to complexity ≤ 4.

These tests exercise the dispatch + alias-normalization layer so the
table-driven structure can't silently lose entries. Per-handler
behaviour (subprocess interactions) is exercised separately in
tests/test_step7.py + integration tests against a real docker daemon.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.health.checker import (  # noqa: E402
    CheckResult,
    _HEAL_ALIASES,
    _HEAL_DISPATCHERS,
    _attempt_self_heal,
)


def _result() -> CheckResult:
    return CheckResult(app_key="x", check_name="ping", ok=False, message="m")


# ── _HEAL_ALIASES ──────────────────────────────────────────────────


def test_heal_aliases_normalise_short_forms() -> None:
    """Short manifest forms map to the canonical action names that
    _HEAL_DISPATCHERS keys on. Drift would silently break self-heal."""
    assert _HEAL_ALIASES["restart"] == "restart_container"
    assert _HEAL_ALIASES["reload"] == "reload_config"
    assert _HEAL_ALIASES["pull"] == "pull_image"
    assert _HEAL_ALIASES["remount"] == "remount_storage"


def test_heal_aliases_passthrough_canonical_names() -> None:
    """Canonical names map to themselves so manifests can use either form."""
    for canonical in (
        "restart_container", "reload_config", "pull_image",
        "rewire", "remount_storage", "restart_managed_service",
    ):
        assert _HEAL_ALIASES[canonical] == canonical


# ── _HEAL_DISPATCHERS table integrity ──────────────────────────────


def test_dispatch_table_covers_all_canonical_actions() -> None:
    """Every distinct value in _HEAL_ALIASES has a matching dispatcher."""
    canonical = set(_HEAL_ALIASES.values())
    dispatched = set(_HEAL_DISPATCHERS.keys())
    missing = canonical - dispatched
    assert not missing, f"actions without dispatchers: {missing}"


def test_dispatch_table_handlers_are_callables() -> None:
    for name, handler in _HEAL_DISPATCHERS.items():
        assert callable(handler), f"{name!r} dispatcher is not callable"


# ── _attempt_self_heal orchestrator ────────────────────────────────


def test_attempt_self_heal_dispatches_to_matching_handler() -> None:
    """`restart` → `_heal_restart_container` per the alias + dispatch tables."""
    with patch.dict(_HEAL_DISPATCHERS,
                    {"restart_container": lambda app_key: True}):
        out = asyncio.run(_attempt_self_heal("sonarr", "restart", _result()))
    assert out is True


def test_attempt_self_heal_unknown_action_returns_false() -> None:
    """An action not in either table → return False, no crash."""
    out = asyncio.run(_attempt_self_heal("sonarr", "do_a_dance", _result()))
    assert out is False


def test_attempt_self_heal_swallows_handler_exceptions() -> None:
    """If the handler raises, the orchestrator logs at warning + returns False
    rather than propagating to caller (preserving the original behaviour)."""
    def _broken_handler(_app_key: str) -> bool:
        raise RuntimeError("simulated docker unavailable")

    with patch.dict(_HEAL_DISPATCHERS,
                    {"restart_container": _broken_handler}):
        out = asyncio.run(_attempt_self_heal("sonarr", "restart", _result()))
    assert out is False


def test_attempt_self_heal_canonical_form_dispatches() -> None:
    """`restart_container` (the canonical form) is also a valid manifest input."""
    captured = {"app_key": None}

    def _capture(app_key: str) -> bool:
        captured["app_key"] = app_key
        return True

    with patch.dict(_HEAL_DISPATCHERS, {"restart_container": _capture}):
        asyncio.run(_attempt_self_heal("sonarr", "restart_container", _result()))
    assert captured["app_key"] == "sonarr"
