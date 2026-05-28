"""tests/test_agent_integrity.py

Unit tests for backend/agent/integrity.py and its wiring as a SLOP Agent
health dimension.

Covered:
  1. test_agent_process_integrity_produces_health_record
       run_process_integrity_check() → write to health_checks
       (subject_type='process_integrity') succeeds, and the row maps to the
       'process_integrity_status' field on /api/v1/health/summary.
  2. test_integrity_result_not_ok_when_critical_gaps_present
       Forcing the coverage map to contain a critical uncovered rule node
       yields IntegrityResult.ok=False and critical_gaps>=1.
  3. test_integrity_summary_is_non_empty
       Every IntegrityResult.summary returned by the function — happy path,
       failure path, and missing-map path — is a non-empty string.
  4. test_integrity_check_never_raises_on_missing_script
       Pointing the runner at a non-existent script returns an
       IntegrityResult(ok=False, ...) instead of propagating FileNotFoundError.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent import integrity as integ_mod
from backend.agent.integrity import IntegrityResult, run_process_integrity_check
from backend.core.agent import AGENT_INTEGRITY_KEY, AGENT_SUBJECT_TYPE_INTEGRITY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_coverage_map(path: Path, nodes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": 0,
        "commit": "test",
        "nodes": nodes,
        "summary": {"total": len(nodes), "covered": sum(1 for n in nodes if n.get("covered")), "uncovered": 0},
        "gaps": [],
        "known_bugs": [],
    }))


class _FakeProc:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_agent_process_integrity_produces_health_record(tmp_path, monkeypatch, test_db):
    """End-to-end: integrity check + DB write + summary surfacing."""
    cov = tmp_path / "data" / "coverage_map.json"
    _write_coverage_map(cov, [
        {"kind": "rule", "id": "r1", "risk": "high", "covered": True},
        {"kind": "rule", "id": "r2", "risk": "critical", "covered": True},
    ])
    monkeypatch.setattr(integ_mod, "_COVERAGE_MAP", cov)
    monkeypatch.setattr(integ_mod, "_COVERAGE_SCRIPT", tmp_path / "fake-ms-coverage")
    monkeypatch.setattr(integ_mod.subprocess, "run", lambda *a, **kw: _FakeProc(0))

    result = run_process_integrity_check()
    assert isinstance(result, IntegrityResult)
    assert result.ok is True
    assert result.total_rules == 2
    assert result.critical_gaps == 0

    # Persist to the DB the same way the health cycle does, then verify the
    # summary endpoint exposes it as process_integrity_status.
    from backend.core.state import StateDB

    if result.critical_gaps > 0:
        status = "critical"
    elif result.high_gaps > 0:
        status = "degraded"
    else:
        status = "ok"

    with StateDB() as db:
        db.upsert_health_check(
            subject_type=AGENT_SUBJECT_TYPE_INTEGRITY,
            subject_key=AGENT_INTEGRITY_KEY,
            check_name="enforcement_coverage",
            status=status,
            summary=result.summary,
        )

    from backend.api.health import get_health_summary

    summary = get_health_summary()
    assert "process_integrity_status" in summary
    assert summary["process_integrity_status"] in {"ok", "degraded", "critical", "unknown"}


def test_integrity_result_not_ok_when_critical_gaps_present(tmp_path, monkeypatch):
    cov = tmp_path / "data" / "coverage_map.json"
    _write_coverage_map(cov, [
        {"kind": "rule", "id": "r1", "risk": "critical", "covered": False},
        {"kind": "rule", "id": "r2", "risk": "high", "covered": False},
        {"kind": "rule", "id": "r3", "risk": "high", "covered": True},
    ])
    monkeypatch.setattr(integ_mod, "_COVERAGE_MAP", cov)
    monkeypatch.setattr(integ_mod, "_COVERAGE_SCRIPT", tmp_path / "fake-ms-coverage")
    monkeypatch.setattr(integ_mod.subprocess, "run", lambda *a, **kw: _FakeProc(0))

    result = run_process_integrity_check()
    assert result.ok is False
    assert result.critical_gaps == 1
    assert result.high_gaps == 1
    assert result.total_rules == 3
    assert "critical" in result.summary.lower()


def test_integrity_summary_is_non_empty(tmp_path, monkeypatch):
    cov = tmp_path / "data" / "coverage_map.json"
    _write_coverage_map(cov, [
        {"kind": "rule", "id": "r1", "risk": "high", "covered": True},
    ])
    monkeypatch.setattr(integ_mod, "_COVERAGE_MAP", cov)
    monkeypatch.setattr(integ_mod, "_COVERAGE_SCRIPT", tmp_path / "fake-ms-coverage")

    # Happy path
    monkeypatch.setattr(integ_mod.subprocess, "run", lambda *a, **kw: _FakeProc(0))
    happy = run_process_integrity_check()
    assert isinstance(happy.summary, str) and happy.summary.strip()

    # Failure path — non-zero return from ms-coverage
    monkeypatch.setattr(integ_mod.subprocess, "run", lambda *a, **kw: _FakeProc(2, "boom"))
    failed = run_process_integrity_check()
    assert failed.ok is False
    assert isinstance(failed.summary, str) and failed.summary.strip()

    # Missing-map path — runs but coverage file disappears
    monkeypatch.setattr(integ_mod.subprocess, "run", lambda *a, **kw: _FakeProc(0))
    monkeypatch.setattr(integ_mod, "_COVERAGE_MAP", tmp_path / "does-not-exist.json")
    missing = run_process_integrity_check()
    assert missing.ok is False
    assert isinstance(missing.summary, str) and missing.summary.strip()


def test_integrity_check_never_raises_on_missing_script(tmp_path, monkeypatch):
    monkeypatch.setattr(integ_mod, "_COVERAGE_SCRIPT", tmp_path / "definitely-not-here")
    monkeypatch.setattr(integ_mod, "_COVERAGE_MAP", tmp_path / "also-not-here.json")

    def _boom(*a, **kw):
        raise FileNotFoundError("simulated")

    monkeypatch.setattr(integ_mod.subprocess, "run", _boom)
    result = run_process_integrity_check()
    assert isinstance(result, IntegrityResult)
    assert result.ok is False
    assert "integrity check failed" in result.summary.lower()
