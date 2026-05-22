"""Regression tests for the install_app wrapper refactor (step 2.7.c).

`install_app` previously had cyclomatic complexity 18 (above ruff's
project threshold of 15). The refactor extracts the orchestrator's
phase logic into 6 helpers (`_install_clear_stale_locks`,
`_install_load_manifest`, `_install_clear_stale_failed_record`,
`_install_register_cf_hostname`, `_install_autoconfig_ollama`,
`_install_cleanup_failed_record`, `_install_finalize`). The
orchestrator drops to ≤ 5.

These tests exercise the cleanly-isolatable helpers — the DB / docker /
docker-compose-driven phases stay covered by the end-to-end tests in
test_executor.py.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.manifests.executor import (  # noqa: E402
    ExecutionResult,
    MAX_INSTALL_SECONDS,
    _install_clear_stale_locks,
    _install_finalize,
    _install_load_manifest,
    _installing,
    _installing_started,
)


def _result() -> ExecutionResult:
    return ExecutionResult(ok=True, app_key="testapp", operation="install")


# ── _install_clear_stale_locks ─────────────────────────────────────


def test_clear_stale_locks_removes_expired_entries() -> None:
    """A lock older than MAX_INSTALL_SECONDS is gone after the call."""
    _installing.add("ghost")
    _installing_started["ghost"] = time.time() - (MAX_INSTALL_SECONDS + 100)
    try:
        _install_clear_stale_locks()
        assert "ghost" not in _installing
        assert "ghost" not in _installing_started
    finally:
        _installing.discard("ghost")
        _installing_started.pop("ghost", None)


def test_clear_stale_locks_preserves_fresh_entries() -> None:
    """A fresh lock is left intact."""
    _installing.add("fresh")
    _installing_started["fresh"] = time.time()
    try:
        _install_clear_stale_locks()
        assert "fresh" in _installing
        assert "fresh" in _installing_started
    finally:
        _installing.discard("fresh")
        _installing_started.pop("fresh", None)


# ── _install_load_manifest ─────────────────────────────────────────


def test_load_manifest_returns_manifest_on_success() -> None:
    sentinel = object()
    with patch("backend.manifests.executor.load_manifest",
               return_value=sentinel):
        result = _result()
        out = _install_load_manifest("anything", result)
    assert out is sentinel
    assert result.ok is True
    assert all(s.name != "load_manifest" for s in result.steps)


def test_load_manifest_records_keyerror_as_failure() -> None:
    """A KeyError (no app in catalog) → returns None, records failure."""
    with patch("backend.manifests.executor.load_manifest",
               side_effect=KeyError("nope")):
        result = _result()
        out = _install_load_manifest("ghost", result)
    assert out is None
    assert result.ok is False
    step = next(s for s in result.steps if s.name == "load_manifest")
    assert step.status == "error"
    assert "No app 'ghost'" in step.message


def test_load_manifest_records_other_errors_as_failure() -> None:
    """A non-KeyError (e.g. corrupted manifest) → returns None, records failure."""
    with patch("backend.manifests.executor.load_manifest",
               side_effect=ValueError("yaml parse error")):
        result = _result()
        out = _install_load_manifest("broken", result)
    assert out is None
    assert result.ok is False
    step = next(s for s in result.steps if s.name == "load_manifest")
    assert step.status == "error"
    assert "yaml parse error" in step.detail


# ── _install_finalize ──────────────────────────────────────────────


def test_finalize_no_op_when_op_id_is_none() -> None:
    """If we never logged the operation (no op_id), finalize is a no-op —
    no DB calls. Verified by patching StateDB to ensure it's untouched."""
    with patch("backend.manifests.executor.StateDB") as mock_db:
        _install_finalize(None, "any", _result())
    mock_db.assert_not_called()
