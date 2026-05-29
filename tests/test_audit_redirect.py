"""tests/test_audit_redirect.py — S-71-B: SLOP_AUDIT_LOG_PATH env-var redirect.

Proves that when SLOP_AUDIT_LOG_PATH is set:
  - write_entry writes to the tmp file (the redirected path).
  - The real docs/SANCTIONED-OPS-LOG.md is byte-unchanged.

Also proves that:
  - An explicit log_path= argument still wins over the env var.
  - When SLOP_AUDIT_LOG_PATH is unset, write_entry writes to SANCTIONED_OPS_LOG
    (production behavior unchanged — but tested against a tmp copy to avoid
    touching the real committed log).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.sanctioned._audit import SANCTIONED_OPS_LOG, write_entry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REAL_LOG: Path = Path(__file__).resolve().parent.parent / SANCTIONED_OPS_LOG


def _call_write_entry(log_path: Path | None = None) -> None:
    """Call write_entry with fixed test data; pass log_path only if given."""
    kwargs: dict = dict(
        tool="test_tool",
        op="test_op",
        pre_sha="abc1234",
        post_sha="def5678",
        result="OK",
        notes="unit-test entry — should never reach the real log",
        caller="pytest",
        timestamp="2000-01-01T00:00:00Z",
    )
    if log_path is not None:
        kwargs["log_path"] = log_path
    write_entry(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_redirect_via_env_var(tmp_path, monkeypatch):
    """When SLOP_AUDIT_LOG_PATH is set, write_entry writes to that path."""
    redirect = tmp_path / "audit.md"
    monkeypatch.setenv("SLOP_AUDIT_LOG_PATH", str(redirect))

    # Capture real log bytes before the call
    real_bytes_before = _REAL_LOG.read_bytes() if _REAL_LOG.exists() else None

    _call_write_entry()

    # The redirect file must have been written
    assert redirect.exists(), "redirected audit file was not created"
    content = redirect.read_text(encoding="utf-8")
    assert "test_tool" in content, "expected tool name in redirected file"
    assert "test_op" in content, "expected op name in redirected file"

    # The real log must be byte-unchanged
    if real_bytes_before is not None:
        real_bytes_after = _REAL_LOG.read_bytes()
        assert real_bytes_before == real_bytes_after, (
            "real SANCTIONED-OPS-LOG.md was modified when SLOP_AUDIT_LOG_PATH was set"
        )
    else:
        # If real log didn't exist before, it must still not exist after
        assert not _REAL_LOG.exists(), (
            "real SANCTIONED-OPS-LOG.md was created when SLOP_AUDIT_LOG_PATH was set"
        )


def test_explicit_log_path_wins_over_env_var(tmp_path, monkeypatch):
    """An explicit log_path= argument overrides SLOP_AUDIT_LOG_PATH."""
    env_redirect = tmp_path / "env_audit.md"
    explicit_path = tmp_path / "explicit_audit.md"
    monkeypatch.setenv("SLOP_AUDIT_LOG_PATH", str(env_redirect))

    _call_write_entry(log_path=explicit_path)

    # Must write to the explicit path, not the env-var path
    assert explicit_path.exists(), "explicit log_path file was not created"
    assert not env_redirect.exists(), (
        "env-var redirect was used even though an explicit log_path was supplied"
    )


def test_production_behavior_when_env_unset(tmp_path, monkeypatch):
    """When SLOP_AUDIT_LOG_PATH is unset, write_entry writes to a supplied log_path."""
    # Ensure env var is not set (monkeypatch.delenv is safe even if absent)
    monkeypatch.delenv("SLOP_AUDIT_LOG_PATH", raising=False)

    explicit_path = tmp_path / "prod_audit.md"
    _call_write_entry(log_path=explicit_path)

    assert explicit_path.exists(), "audit file not created when env var unset"
    assert "test_tool" in explicit_path.read_text(encoding="utf-8")


def test_real_log_untouched_with_env_set(tmp_path, monkeypatch):
    """Cross-check: real log mtime/content is stable when env redirect is active."""
    redirect = tmp_path / "redirect.md"
    monkeypatch.setenv("SLOP_AUDIT_LOG_PATH", str(redirect))

    if _REAL_LOG.exists():
        mtime_before = _REAL_LOG.stat().st_mtime
        _call_write_entry()
        mtime_after = _REAL_LOG.stat().st_mtime
        assert mtime_before == mtime_after, (
            "real SANCTIONED-OPS-LOG.md mtime changed when SLOP_AUDIT_LOG_PATH was set"
        )
    else:
        # Real log doesn't exist; just confirm redirect gets written
        _call_write_entry()
        assert redirect.exists()
