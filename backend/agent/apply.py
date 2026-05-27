"""backend/agent/apply.py

Phase E: safe auto-apply tier for LLM-suggested fixes.

Implements the three low-risk, reversible fix patterns that this tier
handles without human approval:

  restart_container  — docker restart <app_key>
  repull_restart     — docker pull <image>; docker restart <app_key>
  env_var_format     — STUB (Phase H, future) — returns 501-equivalent dict

Mapping from diagnosis_class → fix_type:
  CRASH_LOOP, HEALTHCHECK_TIMEOUT, DEPENDENCY_DOWN  → restart_container
  IMAGE_PULL_FAIL                                   → repull_restart
  UNRESOLVED_PLACEHOLDER                            → env_var_format

All other diagnosis_class values produce fix_type='' which is outside
SAFE_FIX_TYPES — the API layer returns 422 for those.

DB mutations:
  pending_fixes: status='applied', resolved_at=unixepoch()
  fix_history:   new row, outcome='success'
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from backend.core.logging import get_logger
from backend.core.state import StateDB

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Taxonomy mappings
# ---------------------------------------------------------------------------

# Derive fix_type from the stored diagnosis_class.
# Only diagnosis classes that map here are candidates for auto-apply.
DIAGNOSIS_TO_FIX_TYPE: dict[str, str] = {
    "CRASH_LOOP": "restart_container",
    "HEALTHCHECK_TIMEOUT": "restart_container",
    "DEPENDENCY_DOWN": "restart_container",
    "IMAGE_PULL_FAIL": "repull_restart",
    "UNRESOLVED_PLACEHOLDER": "env_var_format",
}

# The set of fix types this tier will execute without human approval.
# All other fix types → 422 (requires human review).
SAFE_FIX_TYPES: set[str] = {"restart_container", "repull_restart", "env_var_format"}

ApplyResult = dict  # {"ok": bool, "message": str, "fix_type": str}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_fix_type(diagnosis_class: str) -> str:
    """Return the fix_type for a given diagnosis_class, or '' if not mapped.

    An empty string indicates no safe auto-apply strategy is known for
    this diagnosis — the endpoint returns 422 in that case.
    """
    return DIAGNOSIS_TO_FIX_TYPE.get(diagnosis_class, "")


def apply_safe_fix(fix_id: int, row: Any) -> ApplyResult:
    """Execute the safe auto-apply action for *row* and update the DB.

    Args:
        fix_id: Primary key of the pending_fixes row.
        row:    sqlite3.Row (or dict-like) with at least:
                app_key, diagnosis_class, suggested_fix, fix_metadata.

    Returns:
        ApplyResult dict: {"ok": bool, "message": str, "fix_type": str}.

    Raises:
        subprocess.CalledProcessError  if the underlying docker command fails.
        subprocess.TimeoutExpired      if the command hangs.
    """
    app_key = row["app_key"]
    diagnosis_class = row["diagnosis_class"]
    fix_type = get_fix_type(diagnosis_class)

    log.info("apply_safe_fix: fix_id=%s app_key=%s fix_type=%s", fix_id, app_key, fix_type)

    if fix_type == "restart_container":
        result = _restart_container(app_key)
    elif fix_type == "repull_restart":
        try:
            metadata = json.loads(row["fix_metadata"] or "{}")
        except (ValueError, TypeError):
            metadata = {}
        result = _repull_restart(app_key, metadata)
    elif fix_type == "env_var_format":
        # Phase H (future): compose fragment edit + force-recreate.
        # [WAVE-DEFER: S-41-LLM-AGENT-F] env_var_format auto-apply not implemented
        result = {
            "ok": False,
            "message": "env_var_format auto-apply is not yet implemented (Phase H, future)",
            "fix_type": fix_type,
        }
        return result
    else:
        # Caller should have rejected this before reaching apply_safe_fix,
        # but guard defensively.
        result = {
            "ok": False,
            "message": "fix_type not in safe tier",
            "fix_type": fix_type,
        }
        return result

    if result["ok"]:
        _mark_applied(fix_id, app_key, row, fix_type)

    return result


# ---------------------------------------------------------------------------
# Private helpers — subprocess actions
# ---------------------------------------------------------------------------


def _restart_container(app_key: str) -> ApplyResult:
    """Run `docker restart <app_key>` synchronously.

    Timeout: 30 s.  Raises CalledProcessError / TimeoutExpired on failure.
    """
    subprocess.run(
        ["docker", "restart", app_key],
        check=True,
        timeout=30,
        capture_output=True,
    )
    log.info("_restart_container: %s restarted successfully", app_key)
    return {
        "ok": True,
        "message": "Container restarted",
        "fix_type": "restart_container",
    }


def _repull_restart(app_key: str, metadata: dict) -> ApplyResult:
    """Run `docker pull <image>` then `docker restart <app_key>`.

    Image defaults to app_key if not found in metadata.
    Pull timeout: 120 s.  Restart timeout: 30 s.
    """
    image = metadata.get("image") or app_key
    subprocess.run(
        ["docker", "pull", image],
        check=True,
        timeout=120,
        capture_output=True,
    )
    subprocess.run(
        ["docker", "restart", app_key],
        check=True,
        timeout=30,
        capture_output=True,
    )
    log.info("_repull_restart: %s re-pulled (%s) and restarted", app_key, image)
    return {
        "ok": True,
        "message": "Image re-pulled and container restarted",
        "fix_type": "repull_restart",
    }


# ---------------------------------------------------------------------------
# Private helpers — DB mutations
# ---------------------------------------------------------------------------


def _mark_applied(fix_id: int, app_key: str, row: Any, fix_type: str) -> None:
    """Update pending_fixes and insert a fix_history record atomically."""
    with StateDB() as db:
        db.execute(
            """
            UPDATE pending_fixes
            SET    status = 'applied',
                   resolved_at = unixepoch()
            WHERE  id = ?
            """,
            (fix_id,),
        )
        db.execute(
            """
            INSERT INTO fix_history
                (app_key, error_type, context, suggested_fix, outcome, created_at)
            VALUES (?, ?, ?, ?, 'success', unixepoch())
            """,
            (
                app_key,
                row["diagnosis_class"],
                fix_type,
                row["suggested_fix"],
            ),
        )
        log.info("_mark_applied: fix_id=%s marked applied; fix_history row inserted", fix_id)
