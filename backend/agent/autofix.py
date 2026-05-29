"""backend/agent/autofix.py

Selection layer for autonomous safe-tier auto-apply (S-64).

This module is the read-only contract the scheduler codes against. It answers
a single question: *which pending_fixes rows are eligible to be applied
autonomously, right now, without human approval?*

It deliberately does NOT mutate the DB or apply anything — applying is the job
of `backend.agent.apply.apply_safe_fix`, which the scheduler calls for each row
returned here and which enforces S-60's backoff + post-fix health verification.

Eligibility (ALL must hold):
  - status == 'pending'
  - confidence >= min_confidence
  - get_fix_type(diagnosis_class) in SAFE_FIX_TYPES, MINUS the 'env_var_format'
    Phase-H stub (which is excluded from auto-apply by design).

`SAFE_FIX_TYPES` and `get_fix_type` are imported from `backend.agent.apply` —
the single source of truth. We do not hardcode a second copy of the taxonomy.
"""
from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.core.state import StateDB
from backend.agent.apply import SAFE_FIX_TYPES, get_fix_type

log = get_logger(__name__)

# The Phase-H stub is never auto-applied; subtract it from the safe set to get
# the set of fix_types eligible for autonomous apply.
_EXCLUDED_FIX_TYPES: frozenset[str] = frozenset({"env_var_format"})
AUTO_APPLICABLE_FIX_TYPES: frozenset[str] = frozenset(SAFE_FIX_TYPES) - _EXCLUDED_FIX_TYPES


def select_auto_applicable(*, min_confidence: float) -> list[Any]:
    """Return pending_fixes rows eligible for autonomous safe-tier apply:
    status='pending', confidence >= min_confidence, and
    get_fix_type(diagnosis_class) in SAFE_FIX_TYPES MINUS {'env_var_format'}.
    Ordered by confidence DESC. Read-only; never raises (returns [] on error)."""
    try:
        with StateDB() as db:
            rows = db.execute(
                """
                SELECT *
                FROM   pending_fixes
                WHERE  status = 'pending'
                  AND  confidence >= ?
                ORDER BY confidence DESC
                """,
                (min_confidence,),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 — best-effort, never raise into caller
        log.warning("select_auto_applicable: read failed, returning []: %s", exc)
        return []

    # Filter on fix_type in Python: get_fix_type maps diagnosis_class → fix_type
    # and is the single source of truth for the taxonomy. Keep only fix_types in
    # the auto-applicable set (safe tier minus the env_var_format stub).
    eligible = [
        row
        for row in rows
        if get_fix_type(row["diagnosis_class"]) in AUTO_APPLICABLE_FIX_TYPES
    ]
    log.info(
        "select_auto_applicable: %d/%d pending rows eligible (min_confidence=%.2f)",
        len(eligible), len(rows), min_confidence,
    )
    return eligible
