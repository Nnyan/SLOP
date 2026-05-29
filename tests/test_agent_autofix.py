"""tests/test_agent_autofix.py — S-64 Stream A.

Unit tests for backend.agent.autofix.select_auto_applicable — the read-only
selection layer that returns pending_fixes rows eligible for autonomous
safe-tier apply.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core.state as _state_mod
from backend.core.state import StateDB, init_db
from backend.agent.autofix import select_auto_applicable, AUTO_APPLICABLE_FIX_TYPES


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated fresh database — applies all migrations via init_db."""
    p = tmp_path / "state.db"
    init_db(p)
    _state_mod.configure(p)
    return p


def _insert_fix(
    *,
    app_key: str = "dozzle",
    diagnosis_class: str = "CRASH_LOOP",
    confidence: float = 0.95,
    status: str = "pending",
    check_name: str = "install_monitor",
    action_type: str = "diagnose",
) -> int:
    """Insert a pending_fixes row; return the new row id.

    check_name/action_type vary so the UNIQUE(app_key, check_name, action_type)
    constraint does not collide across inserts in one test.
    """
    with StateDB() as db:
        cur = db.execute(
            """
            INSERT INTO pending_fixes
                (app_key, check_name, action_type, problem, suggested_fix,
                 confidence, status, diagnosis_class, fix_metadata)
            VALUES (?, ?, ?, 'problem', 'fix', ?, ?, ?, '{}')
            """,
            (app_key, check_name, action_type, confidence, status, diagnosis_class),
        )
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Sanity: the eligible set excludes the Phase-H stub.
# ---------------------------------------------------------------------------


def test_eligible_set_excludes_env_var_format() -> None:
    assert "env_var_format" not in AUTO_APPLICABLE_FIX_TYPES
    assert "restart_container" in AUTO_APPLICABLE_FIX_TYPES
    assert "repull_restart" in AUTO_APPLICABLE_FIX_TYPES


# ---------------------------------------------------------------------------
# Inclusion / exclusion
# ---------------------------------------------------------------------------


def test_high_confidence_safe_row_included(db_path: Path) -> None:
    fid = _insert_fix(diagnosis_class="CRASH_LOOP", confidence=0.95)
    rows = select_auto_applicable(min_confidence=0.9)
    assert [r["id"] for r in rows] == [fid]


def test_low_confidence_excluded(db_path: Path) -> None:
    _insert_fix(diagnosis_class="CRASH_LOOP", confidence=0.5)
    rows = select_auto_applicable(min_confidence=0.9)
    assert rows == []


def test_non_safe_diagnosis_class_excluded(db_path: Path) -> None:
    # A diagnosis_class with no fix_type mapping → get_fix_type returns ''.
    _insert_fix(diagnosis_class="SOMETHING_UNKNOWN", confidence=0.99)
    rows = select_auto_applicable(min_confidence=0.9)
    assert rows == []


def test_env_var_format_excluded(db_path: Path) -> None:
    # UNRESOLVED_PLACEHOLDER → env_var_format fix_type → the Phase-H stub,
    # which must NEVER be auto-applied.
    _insert_fix(diagnosis_class="UNRESOLVED_PLACEHOLDER", confidence=0.99)
    rows = select_auto_applicable(min_confidence=0.9)
    assert rows == []


def test_already_applied_excluded(db_path: Path) -> None:
    _insert_fix(diagnosis_class="CRASH_LOOP", confidence=0.99, status="applied")
    rows = select_auto_applicable(min_confidence=0.9)
    assert rows == []


def test_repull_restart_included(db_path: Path) -> None:
    fid = _insert_fix(diagnosis_class="IMAGE_PULL_FAIL", confidence=0.92)
    rows = select_auto_applicable(min_confidence=0.9)
    assert [r["id"] for r in rows] == [fid]


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_ordered_by_confidence_desc(db_path: Path) -> None:
    low = _insert_fix(
        diagnosis_class="CRASH_LOOP", confidence=0.91,
        check_name="c1", action_type="a1",
    )
    high = _insert_fix(
        diagnosis_class="CRASH_LOOP", confidence=0.99,
        check_name="c2", action_type="a2",
    )
    mid = _insert_fix(
        diagnosis_class="CRASH_LOOP", confidence=0.95,
        check_name="c3", action_type="a3",
    )
    rows = select_auto_applicable(min_confidence=0.9)
    assert [r["id"] for r in rows] == [high, mid, low]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_db_error_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """If StateDB read raises, select_auto_applicable swallows and returns []."""
    import backend.agent.autofix as autofix_mod

    class _BoomDB:
        def __enter__(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated DB failure")

        def __exit__(self, *a):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(autofix_mod, "StateDB", _BoomDB)
    assert select_auto_applicable(min_confidence=0.9) == []
