"""Regression tests for the execute_action refactor (step 2.7.i).

`execute_action` previously had cyclomatic complexity 21 — eight inline
action branches dispatched via `if action_type == "..."` / `elif`. The
refactor extracts each branch into a `_action_<name>` helper and walks
them via an alias-normalising dispatch table (`_ACTION_ALIASES` +
`_ACTION_DISPATCHERS`), mirroring 2.7.a's `_attempt_self_heal`.
The orchestrator drops to ≤ 4.

These tests exercise the dispatch + alias-normalising layer, the
should_auto_act gate, and the not-implemented fallback. Per-handler
behaviour (subprocess interactions) is exercised separately by
backend.core.ai_safety's e2e suite.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.ai_safety import (  # noqa: E402
    _ACTION_ALIASES,
    _ACTION_DISPATCHERS,
    execute_action,
)


# ── _ACTION_ALIASES ────────────────────────────────────────────────


def test_aliases_passthrough_canonical_names() -> None:
    """Canonical names map to themselves so manifests can use either form."""
    for canonical in (
        "restart_container", "reload_config", "pull_image", "rewire",
        "restart_managed_service", "remount_storage", "escalate",
        "reprovision_hostname",
    ):
        assert _ACTION_ALIASES[canonical] == canonical


def test_aliases_normalise_short_forms() -> None:
    """`reprovision` (the manifest's short form) maps to the canonical
    `reprovision_hostname`."""
    assert _ACTION_ALIASES["reprovision"] == "reprovision_hostname"


# ── _ACTION_DISPATCHERS table integrity ────────────────────────────


def test_dispatch_table_covers_all_canonical_actions() -> None:
    """Every distinct value in _ACTION_ALIASES must have a dispatcher
    entry — drift here means an alias points to a missing handler."""
    canonical = set(_ACTION_ALIASES.values())
    dispatched = set(_ACTION_DISPATCHERS.keys())
    missing = canonical - dispatched
    assert not missing, f"actions without dispatchers: {missing}"


def test_dispatch_table_handlers_are_callables() -> None:
    for name, handler in _ACTION_DISPATCHERS.items():
        assert callable(handler), f"{name!r} dispatcher is not callable"


# ── execute_action orchestrator ────────────────────────────────────


def test_execute_action_blocks_when_not_auto_actable() -> None:
    """If should_auto_act is False (the default tier-1 behavior), the
    orchestrator must block the action and surface requires_approval=True
    BEFORE looking at the dispatch table."""
    with patch("backend.core.ai_safety.should_auto_act", return_value=False):
        out = asyncio.run(execute_action("restart_container", "sonarr"))
    assert out["executed"] is False
    assert out["requires_approval"] is True
    assert "requires user approval" in out["message"]


def test_execute_action_dispatches_via_alias_table() -> None:
    """`reprovision` (short form) → `_action_reprovision_hostname`."""
    captured = {"app_key": None}

    def _capture(app_key: str, _detail: str) -> dict:
        captured["app_key"] = app_key
        return {"executed": True, "requires_approval": False, "message": "ok"}

    with patch.dict(_ACTION_DISPATCHERS, {"reprovision_hostname": _capture}), \
         patch("backend.core.ai_safety.should_auto_act", return_value=True):
        out = asyncio.run(execute_action("reprovision", "sonarr"))
    assert out["executed"] is True
    assert captured["app_key"] == "sonarr"


def test_execute_action_unknown_action_returns_not_implemented() -> None:
    """An action not in either table → not-implemented fallback,
    requires_approval=True."""
    with patch("backend.core.ai_safety.should_auto_act", return_value=True):
        out = asyncio.run(execute_action("do_a_dance", "sonarr"))
    assert out["executed"] is False
    assert out["requires_approval"] is True
    assert "not implemented" in out["message"]


def test_execute_action_swallows_handler_exceptions() -> None:
    """If the handler raises, the orchestrator returns executed=False with
    the exception as the message — preserves the original behaviour."""
    def _broken(_app_key: str, _detail: str) -> dict:
        raise RuntimeError("simulated docker socket missing")

    with patch.dict(_ACTION_DISPATCHERS, {"restart_container": _broken}), \
         patch("backend.core.ai_safety.should_auto_act", return_value=True):
        out = asyncio.run(execute_action("restart_container", "sonarr"))
    assert out["executed"] is False
    assert "simulated docker socket missing" in out["message"]


def test_execute_action_passes_detail_to_handler() -> None:
    """The `detail` arg flows through to the handler — currently only
    used by some helpers, but the contract must be preserved."""
    captured: dict[str, str] = {}

    def _capture(app_key: str, detail: str) -> dict:
        captured["app_key"] = app_key
        captured["detail"] = detail
        return {"executed": True, "requires_approval": False, "message": "ok"}

    with patch.dict(_ACTION_DISPATCHERS, {"restart_container": _capture}), \
         patch("backend.core.ai_safety.should_auto_act", return_value=True):
        asyncio.run(execute_action(
            "restart_container", "sonarr", detail="container OOMed",
        ))
    assert captured == {"app_key": "sonarr", "detail": "container OOMed"}
