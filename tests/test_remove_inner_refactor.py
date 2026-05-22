"""Regression tests for the _remove_inner refactor (step 2.7.b).

Mirrors the 1.4.d `_install_inner` refactor: 7 inline phases extract
into per-phase helpers (`_remove_unregister_hostname`,
`_remove_companions`, `_remove_stop_container`,
`_remove_cf_hostname_warning`, `_remove_unwire`,
`_remove_config_folder`). Drops cyclomatic complexity from 16 to ≤ 5.

These tests exercise the cleanly-isolatable helpers
(`_remove_config_folder`, `_remove_unregister_hostname` partial) since
the docker- and DB-driven phases are covered end-to-end by
test_executor.py's `TestRemoveApp` class.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.manifests.executor import (  # noqa: E402
    ExecutionResult,
    _remove_config_folder,
    _remove_unregister_hostname,
)


def _result() -> ExecutionResult:
    return ExecutionResult(ok=True, app_key="testapp", operation="remove")


# ── _remove_config_folder ──────────────────────────────────────────


def test_remove_config_folder_silent_when_no_config_path() -> None:
    """If app.config_path is None/empty, the helper is a no-op."""
    app = SimpleNamespace(config_path=None)
    result = _result()
    _remove_config_folder(app, delete_config=True, result=result)
    assert all(s.name != "config" for s in result.steps), \
        "no config step expected when config_path is empty"


def test_remove_config_folder_skipped_when_dir_missing(tmp_path: Path) -> None:
    """If the dir is already gone, helper records 'skipped' (not error)."""
    app = SimpleNamespace(config_path=str(tmp_path / "ghost"))
    result = _result()
    _remove_config_folder(app, delete_config=True, result=result)
    step = next(s for s in result.steps if s.name == "config")
    assert step.status == "skipped"


def test_remove_config_folder_warning_when_delete_config_none(tmp_path: Path) -> None:
    """`delete_config=None` is the 'ask each time' policy — warn and retain."""
    cfg_dir = tmp_path / "appcfg"
    cfg_dir.mkdir()
    (cfg_dir / "settings.yaml").write_text("foo: bar\n")
    app = SimpleNamespace(config_path=str(cfg_dir))
    result = _result()
    _remove_config_folder(app, delete_config=None, result=result)
    step = next(s for s in result.steps if s.name == "config")
    assert step.status == "warning"
    assert cfg_dir.exists(), "config dir must be retained when delete_config=None"
    assert (cfg_dir / "settings.yaml").exists(), "contents preserved"


def test_remove_config_folder_deletes_when_requested(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "appcfg"
    cfg_dir.mkdir()
    (cfg_dir / "settings.yaml").write_text("foo: bar\n")
    app = SimpleNamespace(config_path=str(cfg_dir))
    result = _result()
    _remove_config_folder(app, delete_config=True, result=result)
    step = next(s for s in result.steps if s.name == "config")
    assert step.status == "ok"
    assert not cfg_dir.exists(), "config dir must be removed when delete_config=True"


def test_remove_config_folder_skipped_when_delete_config_false(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "appcfg"
    cfg_dir.mkdir()
    app = SimpleNamespace(config_path=str(cfg_dir))
    result = _result()
    _remove_config_folder(app, delete_config=False, result=result)
    step = next(s for s in result.steps if s.name == "config")
    assert step.status == "skipped"
    assert cfg_dir.exists(), "explicit False must retain the dir"


# ── _remove_unregister_hostname ────────────────────────────────────


def test_remove_unregister_hostname_returns_none_on_load_failure() -> None:
    """If load_manifest raises (catalog miss / catalog deleted),
    the helper returns None — caller can decide to skip companions."""
    result = _result()
    with patch("backend.manifests.executor.load_manifest",
               side_effect=KeyError("no such app")):
        manifest = _remove_unregister_hostname("ghost", result)
    assert manifest is None
    step = next(s for s in result.steps if s.name == "hostname_unregister")
    assert step.status == "warning"
    assert "Could not unregister" in step.message
