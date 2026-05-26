"""backend/agent/listener.py

Install-failure listener — Phase A of the LLM agent pipeline.

Architecture overview (§3 of LLM-AGENT-DESIGN.md):
  executor.py fires install_failure_listener() as a fire-and-forget
  coroutine whenever a step lands with status='error'.  This module
  writes a stub pending_fixes row (diagnosis_class='UNKNOWN') so the
  existing UI can surface it immediately.  Phase B will replace the
  UNKNOWN class with a regex-based taxonomy; Phase C adds LLM diagnosis.

Invariant: this module MUST be a no-op if anything goes wrong — it
must never propagate exceptions back into the install pipeline.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_SUGGESTED_FIX_STUB = (
    "Diagnosis pending — LLM agent will classify shortly."
)
_CHECK_NAME = "install_monitor"
_ACTION_TYPE = "diagnose"
_PROBLEM_TRUNCATE = 512


async def install_failure_listener(app_key: str, step_log: dict[str, Any]) -> None:
    """Fire-and-forget coroutine called on every install step with status='error'.

    Only acts when step_log["status"] == "error".  All exceptions are
    swallowed — the install pipeline must never be slowed or broken by
    agent code.

    Args:
        app_key:  The catalog key of the app being installed.
        step_log: A dict representation of a StepLog (name, status,
                  message, detail).
    """
    if step_log.get("status") != "error":
        return

    problem = str(step_log.get("detail") or step_log.get("message") or "")[:_PROBLEM_TRUNCATE]

    try:
        from backend.core.state import StateDB
        with StateDB() as db:
            _write_pending_fix(db, app_key, problem)
    except Exception as exc:
        # Never propagate — agent is a best-effort observer.
        log.debug("install_failure_listener: DB write failed for %s: %s", app_key, exc)


def _write_pending_fix(db: Any, app_key: str, problem: str) -> None:
    """Insert or upsert a stub pending_fixes row for this install failure.

    Uses ON CONFLICT to update an existing row so repeated failures on
    the same app don't stack up duplicate rows.

    Args:
        db:       An open StateDB context-manager instance.
        app_key:  The catalog key of the failing app.
        problem:  Truncated error detail string (max 512 chars).
    """
    db.execute(
        """
        INSERT INTO pending_fixes
            (app_key, check_name, action_type, problem, suggested_fix,
             confidence, status, diagnosis_class)
        VALUES (?, ?, ?, ?, ?, 0.0, 'pending', 'UNKNOWN')
        ON CONFLICT(app_key, check_name, action_type)
        DO UPDATE SET
            problem        = excluded.problem,
            suggested_fix  = excluded.suggested_fix,
            confidence     = 0.0,
            status         = 'pending',
            diagnosis_class= 'UNKNOWN',
            created_at     = unixepoch(),
            resolved_at    = NULL
        """,
        (app_key, _CHECK_NAME, _ACTION_TYPE, problem, _SUGGESTED_FIX_STUB),
    )
