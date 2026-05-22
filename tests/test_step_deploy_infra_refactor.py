"""Regression tests for the step_deploy_infra refactor (step 2.7.h).

`step_deploy_infra` previously had cyclomatic complexity 20 — five
deploy phases (tunnels / auth / VPN / dashboard / management) inlined,
each with its own cfg-building branches, plus an inner `_deploy`
closure and trailing result-formatting logic.

The refactor extracts each phase into its own module-level helper +
the closure into `_try_deploy_one` + result formatting into
`_format_deploy_result`. The orchestrator drops to ≤ 4.

These tests focus on `_format_deploy_result` (pure result-shaping
logic — no I/O) and the basic shape of each `_deploy_*` phase
(no-op when slot unselected). Per-provider deploy is exercised
end-to-end by the existing wizard e2e tests.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.platform.wizard import (  # noqa: E402
    StepResult,
    _deploy_auth,
    _deploy_dashboard,
    _deploy_management,
    _deploy_tunnels,
    _deploy_vpn,
    _format_deploy_result,
)


# ── _format_deploy_result ──────────────────────────────────────────


def test_format_skipped_when_all_buckets_empty() -> None:
    """No providers selected → 'skipped' StepResult."""
    out = _format_deploy_result([], [], [])
    assert out.status == "skipped"
    assert "No infrastructure" in out.message


def test_format_error_when_only_failures() -> None:
    """Failures with zero successes → 'error' (deploy_infra blocks the wizard)."""
    out = _format_deploy_result([], [], ["x: boom"])
    assert out.status == "error"
    assert out.message == "Infrastructure deployment failed."
    assert "x: boom" in out.detail


def test_format_ok_with_partial_success() -> None:
    """Some successes + some failures → 'ok' (partial-success doesn't
    block the wizard, but failures are surfaced in the message)."""
    out = _format_deploy_result(["a"], [], ["b: boom"])
    assert out.status == "ok"
    assert "Deployed: a" in out.message
    assert "Failed: b: boom" in out.message
    assert "b: boom" in out.detail


def test_format_ok_full_success() -> None:
    """All providers deployed → 'ok' with no detail."""
    out = _format_deploy_result(["a", "b"], [], [])
    assert out.status == "ok"
    assert "Deployed: a, b" in out.message
    assert out.detail == ""


def test_format_ok_with_skipped_listed() -> None:
    """`skipped` providers (currently unused but the API takes the list) appear in the message."""
    out = _format_deploy_result(["a"], ["b"], [])
    assert out.status == "ok"
    assert "Skipped: b" in out.message


# ── per-slot phase helpers (no-op when slot unselected) ────────────


def _empty_inp(**over) -> SimpleNamespace:
    """Build a minimal WizardInput-shaped object for the helper tests.
    Each helper only reads the attributes it needs from `inp`."""
    base = dict(
        domain=None, config_root=None, network_name=None, secrets=None,
        tunnels=None, auth=None, vpn=None, dashboard=None, management=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_deploy_auth_noop_when_unset() -> None:
    """auth=None → helper returns without touching either result list."""
    deployed: list[str] = []
    failed: list[str] = []
    _deploy_auth(_empty_inp(), "ex.com", "net", deployed, failed)
    assert deployed == [] and failed == []


def test_deploy_auth_noop_when_none_string() -> None:
    """auth='none' is the wizard's sentinel for 'don't deploy' — same as None."""
    deployed: list[str] = []
    failed: list[str] = []
    _deploy_auth(_empty_inp(auth="none"), "ex.com", "net", deployed, failed)
    assert deployed == [] and failed == []


def test_deploy_vpn_noop_when_unset() -> None:
    deployed: list[str] = []
    failed: list[str] = []
    _deploy_vpn(_empty_inp(), "ex.com", "net", deployed, failed)
    assert deployed == [] and failed == []


def test_deploy_dashboard_noop_when_unset() -> None:
    deployed: list[str] = []
    failed: list[str] = []
    _deploy_dashboard(_empty_inp(), "ex.com", "net", deployed, failed)
    assert deployed == [] and failed == []


def test_deploy_management_noop_when_unset() -> None:
    deployed: list[str] = []
    failed: list[str] = []
    _deploy_management(_empty_inp(), "ex.com", "net", deployed, failed)
    assert deployed == [] and failed == []


def test_deploy_tunnels_noop_when_empty_list() -> None:
    """tunnels=[] → for loop runs zero times, no provider lookups."""
    deployed: list[str] = []
    failed: list[str] = []
    _deploy_tunnels(_empty_inp(tunnels=[]), "ex.com", "net", deployed, failed)
    assert deployed == [] and failed == []


def test_deploy_tunnels_noop_when_none() -> None:
    """tunnels=None coerces to [] via `inp.tunnels or []`."""
    deployed: list[str] = []
    failed: list[str] = []
    _deploy_tunnels(_empty_inp(), "ex.com", "net", deployed, failed)
    assert deployed == [] and failed == []
