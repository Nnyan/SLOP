"""Regression tests for the _llm_diagnose refactor (step 1.4.d, refactor 3/5).

`_llm_diagnose` previously had cyclomatic complexity 27. The refactor splits
it into ~11 helpers (`_check_ram_for_llm`, `_build_diagnosis_prompt`,
`_load_provider_config`, `_call_ollama`, `_call_cloud_provider`,
`_call_openai_compatible`, `_dispatch_llm_call`, `_maybe_rag_expand`,
`_track_llm_success`, `_classify_llm_error`, `_extract_diagnosis`,
`_persist_pending_fix`) plus a module-scope `_LLM_ACTION_MAP`.

These tests exercise the pure helpers (action mapping, error classification,
diagnosis extraction) and the synchronous DB-backed helpers
(`_persist_pending_fix`, `_load_provider_config`).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.state import StateDB, init_db  # noqa: E402
from backend.health.checker import (  # noqa: E402
    CheckResult,
    _LLM_ACTION_MAP,
    _check_ram_for_llm,
    _classify_llm_error,
    _extract_diagnosis,
    _llm_state,
    _load_provider_config,
    _persist_pending_fix,
    _track_llm_success,
)


@pytest.fixture(autouse=True, scope="module")
def _fresh_state_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Schema-migrated StateDB; provider config + pending_fixes need it."""
    db_path = tmp_path_factory.mktemp("llm_refactor") / "state.db"
    init_db(db_path)
    return db_path


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """Each test starts with the canonical _llm_state AND a clean
    `llm_agent_config` setting in the shared module-scoped DB.

    The DB is module-scoped (fast) but tests within the file mutate it
    (e.g. `test_load_provider_config_reads_from_db` writes the setting).
    Without this autouse cleanup, downstream tests like
    `test_load_provider_config_defaults_when_unset` would see the
    previous test's writes — making the file order-dependent under
    pytest-randomly. Cleaning between tests preserves the speed of
    module-scoped init_db while keeping per-test isolation.
    """
    # Clear settings that test cases mutate
    try:
        with StateDB() as db:
            db.set_setting("llm_agent_config", "")
    except Exception:
        pass
    snap = dict(_llm_state)
    _llm_state.update({
        "status": "unknown",
        "consecutive_failures": 0,
        "consecutive_slow": 0,
        "last_checked": 0,
        "last_error": "",
        "last_error_type": "",
        "ollama_url": "http://ollama:11434",
        "model_tried": "",
        "last_success_at": 0,
        "configured_provider": "",
        "configured_model": "",
    })
    yield
    _llm_state.clear()
    _llm_state.update(snap)


# ── _LLM_ACTION_MAP — the lookup table used by _extract_diagnosis ──


def test_action_map_normalises_legacy_aliases() -> None:
    """The original code had aliases (restart→restart_container, etc.) that
    must remain stable so existing fix_history rows keep matching."""
    assert _LLM_ACTION_MAP["restart"] == "restart_container"
    assert _LLM_ACTION_MAP["reload"] == "reload_config"
    assert _LLM_ACTION_MAP["pull"] == "pull_image"
    assert _LLM_ACTION_MAP["update_image"] == "pull_image"
    assert _LLM_ACTION_MAP["restart_service"] == "restart_managed_service"
    assert _LLM_ACTION_MAP["remount"] == "remount_storage"
    assert _LLM_ACTION_MAP["reprovision"] == "reprovision_hostname"


def test_action_map_explicit_self_entries() -> None:
    """The original map only lists SOME canonical actions explicitly; the
    rest pass through via `_LLM_ACTION_MAP.get(raw, raw)`'s default. Document
    which entries are explicit so future edits don't accidentally remove them."""
    assert _LLM_ACTION_MAP["restart_container"] == "restart_container"
    assert _LLM_ACTION_MAP["rewire"] == "rewire"
    assert _LLM_ACTION_MAP["manual"] == "manual"
    assert _LLM_ACTION_MAP["escalate"] == "escalate"


def test_extract_diagnosis_passes_canonical_through_via_default() -> None:
    """Canonical actions not in the map (reload_config, pull_image, etc.)
    are passed through unchanged via the dict's `.get(raw, raw)` default."""
    for canonical in ("reload_config", "pull_image",
                      "restart_managed_service", "remount_storage",
                      "reprovision_hostname"):
        action_type, _, _, _ = _extract_diagnosis(dict(action=canonical))
        assert action_type == canonical


# ── _extract_diagnosis ─────────────────────────────────────────────


def test_extract_diagnosis_canonical_payload() -> None:
    data = dict(
        action="restart",
        confidence=0.85,
        problem="API not responding",
        cause="postgres down",
        suggested_fix="restart postgres",
    )
    action_type, problem, suggested, confidence = _extract_diagnosis(data)
    assert action_type == "restart_container"
    assert confidence == pytest.approx(0.85)
    assert "API not responding" in problem
    assert "(Root cause: postgres down)" in problem  # cause appended
    assert suggested == "restart postgres"


def test_extract_diagnosis_unknown_action_passes_through() -> None:
    """Original behaviour: actions not in the map are returned verbatim
    (lowered) so unrecognised LLM responses don't crash the caller."""
    data = dict(action="DO_SOMETHING_NEW", confidence=0.5,
                problem="x", suggested_fix="y")
    action_type, *_ = _extract_diagnosis(data)
    assert action_type == "do_something_new"


def test_extract_diagnosis_handles_missing_problem() -> None:
    data = dict(action="manual", confidence=0.7, cause="weird thing",
                suggested_fix="check logs")
    _, problem, _, _ = _extract_diagnosis(data)
    # cause becomes the problem when problem is absent
    assert problem == "weird thing"


def test_extract_diagnosis_skips_redundant_cause() -> None:
    """If cause is already mentioned in problem, don't append it (preserved
    case-insensitive substring check from original)."""
    data = dict(action="manual", confidence=0.7,
                problem="postgres is down — restart it",
                cause="POSTGRES IS DOWN",
                suggested_fix="restart")
    _, problem, _, _ = _extract_diagnosis(data)
    assert problem.count("postgres is down") == 1  # not duplicated
    assert "Root cause:" not in problem


def test_extract_diagnosis_appends_escalation_notes() -> None:
    data = dict(action="escalate", confidence=0.4,
                problem="unsure",
                suggested_fix="get cloud opinion",
                escalation_notes="local model lacks domain knowledge for this stack")
    _, _, suggested, _ = _extract_diagnosis(data)
    assert "[Escalation context:" in suggested
    assert "local model lacks domain knowledge" in suggested


def test_extract_diagnosis_defaults_confidence_to_05() -> None:
    data = dict(action="manual", problem="x", suggested_fix="y")
    _, _, _, confidence = _extract_diagnosis(data)
    assert confidence == 0.5


# ── _classify_llm_error — error-string classification ──────────────


def test_classify_connection_refused() -> None:
    _classify_llm_error(ConnectionRefusedError("Connection refused"),
                        "http://o:1", "model-x")
    assert _llm_state["last_error_type"] == "connection"
    assert "Cannot reach http://o:1" in _llm_state["last_error"]
    assert _llm_state["consecutive_failures"] == 1


def test_classify_timeout() -> None:
    _classify_llm_error(TimeoutError("operation timed out"),
                        "http://o:1", "model-x")
    assert _llm_state["last_error_type"] == "timeout"
    assert "timed out" in _llm_state["last_error"]


def test_classify_404_or_model_not_found() -> None:
    """Original quirk: '404' alone OR ('model' AND 'not found') — preserved."""
    _classify_llm_error(Exception("HTTP 404"), "http://o:1", "phi4-mini")
    assert _llm_state["last_error_type"] == "model"
    assert "phi4-mini" in _llm_state["last_error"]


def test_classify_json_parse_error() -> None:
    _classify_llm_error(ValueError("JSONDecodeError: bad token"),
                        "http://o:1", "model-x")
    assert _llm_state["last_error_type"] == "parse"


def test_classify_unknown_falls_through() -> None:
    _classify_llm_error(RuntimeError("weird new failure mode"),
                        "http://o:1", "model-x")
    assert _llm_state["last_error_type"] == "unknown"
    assert "RuntimeError" in _llm_state["last_error"]


def test_classify_offline_after_streak_threshold() -> None:
    """After PERF_THRESHOLDS['llm_parse_fail_streak'] consecutive failures,
    status goes offline."""
    from backend.manifests.executor import PERF_THRESHOLDS
    streak = PERF_THRESHOLDS["llm_parse_fail_streak"]
    for _ in range(streak):
        _classify_llm_error(RuntimeError("boom"), "http://o:1", "m")
    assert _llm_state["status"] == "offline"


# ── _track_llm_success — _llm_state on success ─────────────────────


def test_track_success_resets_failure_counters() -> None:
    _llm_state["consecutive_failures"] = 5
    _llm_state["last_error"] = "old error"
    _track_llm_success(elapsed=1.0, ollama_url="http://o", model="m")
    assert _llm_state["consecutive_failures"] == 0
    assert _llm_state["last_error"] == ""
    assert _llm_state["status"] == "active"


def test_track_success_marks_degraded_after_3_slow() -> None:
    """After 3 consecutive slow inferences, status = degraded."""
    from backend.manifests.executor import PERF_THRESHOLDS
    slow = PERF_THRESHOLDS["llm_inference_seconds"] + 1.0
    _track_llm_success(slow, "http://o", "m")
    _track_llm_success(slow, "http://o", "m")
    _track_llm_success(slow, "http://o", "m")
    assert _llm_state["status"] == "degraded"
    assert _llm_state["consecutive_slow"] >= 3


def test_track_success_fast_resets_slow_counter() -> None:
    """A fast call after slow ones resets to active and clears slow streak."""
    from backend.manifests.executor import PERF_THRESHOLDS
    slow = PERF_THRESHOLDS["llm_inference_seconds"] + 1.0
    fast = 0.1
    _track_llm_success(slow, "http://o", "m")
    _track_llm_success(slow, "http://o", "m")
    _track_llm_success(fast, "http://o", "m")
    assert _llm_state["status"] == "active"
    assert _llm_state["consecutive_slow"] == 0


# ── _check_ram_for_llm ─────────────────────────────────────────────


def test_check_ram_returns_bool() -> None:
    """Smoke test: helper returns bool without raising on real system_eval."""
    out = _check_ram_for_llm("phi4-mini")
    assert isinstance(out, bool)


def test_check_ram_returns_false_when_quick_check_fails() -> None:
    with patch("backend.core.system_eval.quick_ram_check",
               return_value=(False, "out of RAM")):
        assert _check_ram_for_llm("any-model") is False


# ── _persist_pending_fix — DB write contract ───────────────────────


def test_persist_pending_fix_inserts_then_upserts() -> None:
    _persist_pending_fix(
        "sonarr", "http_check", "restart_container",
        "API timing out", "restart sonarr container", 0.85, "phi4-mini",
    )
    with StateDB() as db:
        rows = db.execute(
            "SELECT app_key, action_type, problem, suggested_fix, "
            "confidence, status, model FROM pending_fixes "
            "WHERE app_key='sonarr' AND check_name='http_check'"
        ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["action_type"] == "restart_container"
    assert r["problem"] == "API timing out"
    assert r["suggested_fix"] == "restart sonarr container"
    assert r["confidence"] == pytest.approx(0.85)
    assert r["status"] == "pending"
    assert r["model"] == "phi4-mini"

    # Second call with the same (app, check, action) should UPDATE in place
    _persist_pending_fix(
        "sonarr", "http_check", "restart_container",
        "API still timing out", "longer wait", 0.9, "phi4-mini",
    )
    with StateDB() as db:
        rows = db.execute(
            "SELECT problem, suggested_fix, confidence "
            "FROM pending_fixes "
            "WHERE app_key='sonarr' AND check_name='http_check' "
            "AND action_type='restart_container'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["problem"] == "API still timing out"
    assert rows[0]["confidence"] == pytest.approx(0.9)


# ── _load_provider_config — defaults + DB-backed read ──────────────


def test_load_provider_config_defaults_when_unset() -> None:
    """When llm_agent_config is missing, defaults to ollama / no key."""
    provider, api_key, model_cfg, cloud = _load_provider_config()
    assert provider == "ollama"
    assert api_key == ""
    assert model_cfg == ""
    assert isinstance(cloud, set)


def test_load_provider_config_reads_from_db() -> None:
    import json as _j
    with StateDB() as db:
        db.set_setting("llm_agent_config", _j.dumps(dict(
            provider="anthropic",
            api_key="sk-test-key",
            model="claude-sonnet",
        )))
    provider, api_key, model_cfg, cloud = _load_provider_config()
    assert provider == "anthropic"
    assert api_key == "sk-test-key"
    assert model_cfg == "claude-sonnet"
    assert _llm_state["configured_provider"] == "anthropic"
    assert _llm_state["configured_model"] == "claude-sonnet"


# ── _llm_diagnose orchestrator — smoke test ────────────────────────


def test_llm_diagnose_returns_none_when_ram_check_fails() -> None:
    """The pre-flight RAM check short-circuits before any I/O."""
    import asyncio
    from backend.health.checker import _llm_diagnose
    cr = CheckResult(app_key="x", check_name="ping", ok=False, message="boom")
    with patch("backend.core.system_eval.quick_ram_check",
               return_value=(False, "low RAM")):
        out = asyncio.run(_llm_diagnose("x", cr, "no logs",
                                        ollama_url="http://nowhere", model="m"))
    assert out is None
