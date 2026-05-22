"""Regression tests for the check_app refactor (step 1.4.d, refactor 2/5).

`check_app` previously had cyclomatic complexity 32 — well above Core Rule
8.1's threshold of 15. The refactor extracts ~13 helpers (`_load_manifest_or_skip`,
`_precheck_fragment`, `_precheck_oom`, `_grace_results`, `_run_one_check`,
`_resolve_pending_fixes`, `_record_healthy`, `_try_self_heal`,
`_mass_failure_diagnosis`, `_filter_error_logs`, `_collect_net_checks`,
`_diagnose_with_llm`, `_notify_failure`, `_record_unhealthy`,
`_maybe_perf_warn`) and turns `check_app` into a thin orchestrator.

These tests lock in helper-level behaviour for the parts that do not
require docker, ntfy, or LLM I/O. End-to-end coverage of the orchestrator
remains in test_health_scheduler.py / test_fsm_health_check.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.state import init_db  # noqa: E402
from backend.health.checker import (  # noqa: E402
    CheckResult,
    check_app,
    _filter_error_logs,
    _grace_results,
    _load_manifest_or_skip,
    _precheck_fragment,
    _precheck_oom,
    _run_one_check,
    _try_self_heal,
)


@pytest.fixture(autouse=True, scope="module")
def _fresh_state_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Fresh, schema-migrated StateDB for the whole module.

    `check_app` and several helpers open StateDB(); without configuration
    they raise StateError. Module-scoped to amortise migration cost.
    """
    db_path = tmp_path_factory.mktemp("checker_refactor") / "state.db"
    init_db(db_path)
    return db_path


def _check_def(name: str = "ping", check_type: str = "custom",
               path: str = "/", port: int | None = None,
               expect_status: int = 200) -> SimpleNamespace:
    """Build a synthetic CheckDef stand-in suitable for the helpers."""
    return SimpleNamespace(
        name=name,
        check_type=check_type,
        path=path,
        port=port,
        expect_status=expect_status,
    )


def _manifest(display_name: str = "TestApp",
              health_checks: list | None = None,
              self_heal: list | None = None,
              start_grace_s: int = 0) -> SimpleNamespace:
    """Build a synthetic Manifest stand-in for the helpers."""
    return SimpleNamespace(
        display_name=display_name,
        health_checks=health_checks if health_checks is not None else [_check_def()],
        self_heal=self_heal or [],
        start_grace_s=start_grace_s,
        web_port=None,
    )


# ── _precheck_fragment ─────────────────────────────────────────────


def test_precheck_fragment_returns_none_when_fragment_present(tmp_path: Path) -> None:
    """When the compose fragment exists, the pre-check is a no-op."""
    frag = tmp_path / "myapp.yaml"
    frag.write_text("services: {}\n")
    fake_cfg = SimpleNamespace(compose_dir=tmp_path)
    with patch("backend.core.config.config", fake_cfg):
        out = _precheck_fragment("myapp", SimpleNamespace(status="running"),
                                 _manifest())
    assert out is None


def test_precheck_fragment_returns_error_results_when_missing(tmp_path: Path) -> None:
    """When the fragment is missing on a non-failed app, return one error
    CheckResult per defined health check (preserves original semantics)."""
    fake_cfg = SimpleNamespace(compose_dir=tmp_path)
    manifest = _manifest(health_checks=[_check_def("ping"), _check_def("api", "http")])
    with patch("backend.core.config.config", fake_cfg):
        out = _precheck_fragment("noapp", SimpleNamespace(status="running"),
                                 manifest)
    assert out is not None
    assert len(out) == 2
    assert all(not r.ok for r in out)
    assert all("No compose fragment for 'noapp'" in r.message for r in out)


def test_precheck_fragment_silent_when_app_already_failed(tmp_path: Path) -> None:
    """Apps in failed/disabled/removing state already known broken — don't
    duplicate the diagnosis."""
    fake_cfg = SimpleNamespace(compose_dir=tmp_path)  # empty dir, no fragment
    with patch("backend.core.config.config", fake_cfg):
        out = _precheck_fragment("noapp", SimpleNamespace(status="failed"),
                                 _manifest())
    assert out is None


# ── _precheck_oom ──────────────────────────────────────────────────


def test_precheck_oom_returns_single_result_when_killed() -> None:
    out = _precheck_oom(
        "memhog", _manifest(display_name="MemHog"),
        runtime_state={"oom_killed": True, "restart_count": 7},
        in_grace=False,
    )
    assert out is not None
    assert len(out) == 1
    r = out[0]
    assert r.check_name == "oom_killed"
    assert r.ok is False
    assert "MemHog was killed due to out-of-memory" in r.message
    assert "Restart count: 7" in r.message
    assert r.action_type == "restart_container"
    assert r.llm_diagnosis is not None
    assert "OOM KILL" in r.llm_diagnosis


def test_precheck_oom_silent_when_in_grace() -> None:
    """During startup grace OOM may be a transient signal — don't fire."""
    out = _precheck_oom(
        "memhog", _manifest(),
        runtime_state={"oom_killed": True, "restart_count": 0},
        in_grace=True,
    )
    assert out is None


def test_precheck_oom_silent_when_not_killed() -> None:
    out = _precheck_oom(
        "ok", _manifest(),
        runtime_state={"oom_killed": False, "restart_count": 0},
        in_grace=False,
    )
    assert out is None


def test_precheck_oom_handles_missing_restart_count() -> None:
    out = _precheck_oom(
        "memhog", _manifest(display_name="MemHog"),
        runtime_state={"oom_killed": True},
        in_grace=False,
    )
    assert out is not None
    assert "Restart count: ?" in out[0].message


# ── _grace_results ─────────────────────────────────────────────────


def test_grace_results_one_per_health_check() -> None:
    manifest = _manifest(health_checks=[
        _check_def("ping"), _check_def("api", "http"), _check_def("port", "tcp"),
    ])
    out = _grace_results("starting_app", manifest, container_age=12, grace_s=120)
    assert len(out) == 3
    assert all(r.ok for r in out)
    assert all("Starting — 12s into 120s grace period" in r.message for r in out)


def test_grace_results_handles_zero_health_checks() -> None:
    out = _grace_results("x", _manifest(health_checks=[]), 5, 60)
    assert out == []


# ── _run_one_check (custom branch only — no I/O needed) ────────────


def test_run_one_check_custom_returns_not_implemented() -> None:
    import asyncio
    cd = _check_def(name="weird", check_type="custom")
    r = asyncio.run(_run_one_check("app", cd, base_url="", host_port=None,
                                   container_name="app"))
    assert r.ok is True
    assert "not implemented" in r.message
    assert r.check_name == "weird"


def test_run_one_check_http_without_base_url_falls_through_to_custom() -> None:
    """HTTP dispatch requires base_url; without it, falls through to the
    'not implemented' branch (preserving original behaviour)."""
    import asyncio
    cd = _check_def(name="httpx", check_type="http")
    r = asyncio.run(_run_one_check("app", cd, base_url="", host_port=None,
                                   container_name="app"))
    assert r.ok is True
    assert "not implemented" in r.message


# ── _try_self_heal — preserves loop-variable semantics ─────────────


def test_try_self_heal_returns_matched_entry_and_invokes_action() -> None:
    """When a self_heal condition matches, return the matched entry; the
    `auto_fix` recorded later in the DB will use this entry's action."""
    import asyncio
    from unittest.mock import AsyncMock
    heal_a = SimpleNamespace(condition="ping", action="restart_container")
    heal_b = SimpleNamespace(condition="api", action="reload_config")
    manifest = _manifest(self_heal=[heal_a, heal_b])
    cd = _check_def(name="api")
    result = CheckResult(app_key="x", check_name="api", ok=False,
                         message="boom")

    mock_heal = AsyncMock(return_value=False)
    with patch("backend.health.checker._attempt_self_heal", mock_heal):
        out = asyncio.run(_try_self_heal("x", manifest, cd, result))

    assert out is heal_b  # matched the second entry
    mock_heal.assert_awaited_once_with("x", "reload_config", result)
    assert result.auto_healed is False


def test_try_self_heal_returns_last_when_no_match() -> None:
    """Original semantics: when no condition matches but list is non-empty,
    `heal` retains the last loop value (used for auto_fix recording)."""
    import asyncio
    from unittest.mock import AsyncMock
    heal_a = SimpleNamespace(condition="apple", action="restart_container")
    heal_b = SimpleNamespace(condition="banana", action="reload_config")
    manifest = _manifest(self_heal=[heal_a, heal_b])
    cd = _check_def(name="cherry")
    result = CheckResult(app_key="x", check_name="cherry", ok=False,
                         message="cherry boom")

    mock_heal = AsyncMock(return_value=False)
    with patch("backend.health.checker._attempt_self_heal", mock_heal):
        out = asyncio.run(_try_self_heal("x", manifest, cd, result))

    assert out is heal_b  # last entry, no match attempted
    mock_heal.assert_not_called()
    assert result.auto_healed is False


def test_try_self_heal_returns_none_for_empty_list() -> None:
    import asyncio
    manifest = _manifest(self_heal=[])
    result = CheckResult(app_key="x", check_name="any", ok=False, message="m")
    out = asyncio.run(_try_self_heal("x", manifest, _check_def(), result))
    assert out is None


def test_try_self_heal_matches_via_message_substring() -> None:
    """Original supports both name-match and substring-match against the
    failure message (useful for generic conditions like 'connection refused')."""
    import asyncio
    from unittest.mock import AsyncMock
    heal = SimpleNamespace(condition="refused", action="restart_container")
    manifest = _manifest(self_heal=[heal])
    cd = _check_def(name="ping")
    result = CheckResult(app_key="x", check_name="ping", ok=False,
                         message="connection refused")

    mock_heal = AsyncMock(return_value=True)
    with patch("backend.health.checker._attempt_self_heal", mock_heal):
        out = asyncio.run(_try_self_heal("x", manifest, cd, result))

    assert out is heal
    mock_heal.assert_awaited_once()
    assert result.auto_healed is True


# ── _filter_error_logs ─────────────────────────────────────────────


def test_filter_error_logs_returns_placeholder_on_failure() -> None:
    with patch("backend.core.docker_client.container_logs",
               side_effect=RuntimeError("docker down")):
        assert _filter_error_logs("missing_app") == "(logs unavailable)"


def test_filter_error_logs_keeps_only_error_lines() -> None:
    raw = (
        "INFO startup\n"
        "DEBUG handshake\n"
        "ERROR connection refused\n"
        "WARN slow query\n"
        "INFO request 200\n"
    )
    with patch("backend.core.docker_client.container_logs", return_value=raw):
        out = _filter_error_logs("app")
    assert "ERROR connection refused" in out
    assert "WARN slow query" in out
    assert "INFO startup" not in out


def test_filter_error_logs_falls_back_to_tail_when_no_errors() -> None:
    raw = "ok\n" * 600  # ~1800 chars of plain logs, no error keywords
    with patch("backend.core.docker_client.container_logs", return_value=raw):
        out = _filter_error_logs("app")
    assert out.endswith("ok\n") or out.endswith("ok")
    assert len(out) <= 2000  # the [-2000:] tail is the bound


# ── _load_manifest_or_skip — orchestrator-level behaviour ──────────


def test_load_manifest_or_skip_returns_manifest_for_known_app() -> None:
    fake_manifest = SimpleNamespace(display_name="ok")
    with patch("backend.health.checker.load_manifest", return_value=fake_manifest):
        assert _load_manifest_or_skip("anyapp") is fake_manifest


def test_load_manifest_or_skip_returns_none_for_unmanaged_app() -> None:
    """Catalog miss + not in apps table → unmanaged → caller returns []."""
    with patch("backend.health.checker.load_manifest",
               side_effect=KeyError("no such app")):
        out = _load_manifest_or_skip("never_existed_app_xyz")
    assert out is None


# ── check_app orchestrator — smoke test ────────────────────────────


def test_check_app_returns_empty_list_for_unknown_app() -> None:
    """Smoke test: unknown app produces no CheckResults and no exceptions —
    the failure path through `_load_manifest_or_skip` returning None."""
    import asyncio
    out = asyncio.run(check_app("totally_unknown_app_xyz_2_4d", "http://o",
                                "http://n", "t"))
    assert out == []
