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
  fix_history:   new row, outcome='success' or 'failed_verification'
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from backend.core.logging import get_logger
from backend.core.state import StateDB
from backend.agent.backoff import attempt_allowed, record_attempt
from backend.agent.verify import verify_container_healthy

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

ApplyResult = dict[str, Any]  # {"ok": bool, "message": str, "fix_type": str}


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

    # --- backoff gate: check before touching the container ---
    allowed, reason = attempt_allowed(app_key, fix_type)
    if not allowed:
        log.info(
            "apply_safe_fix: backoff denied fix_id=%s app_key=%s fix_type=%s: %s",
            fix_id,
            app_key,
            fix_type,
            reason,
        )
        return {"ok": False, "message": reason, "fix_type": fix_type}

    # Short-circuit non-subprocess paths before writing the DB record.
    if fix_type == "env_var_format":
        # Phase H (future): compose fragment edit + force-recreate.
        # [DEFER] env_var_format auto-apply not implemented
        return {
            "ok": False,
            "message": "env_var_format auto-apply is not yet implemented (Phase H, future)",
            "fix_type": fix_type,
        }
    if fix_type not in SAFE_FIX_TYPES or fix_type == "":
        # Caller should have rejected this before reaching apply_safe_fix,
        # but guard defensively.
        return {
            "ok": False,
            "message": "fix_type not in safe tier",
            "fix_type": fix_type,
        }

    # Pre-execution DB record — MUST be written before any subprocess call.
    # Fail-closed: if log_operation raises, the action does NOT proceed.
    with StateDB() as db:
        op_id = db.log_operation(
            operation="auto_apply",
            subject_type="app",
            subject_key=app_key,
            triggered_by="agent",
            detail={"fix_type": fix_type, "fix_id": fix_id},
        )

    # --- pre-risky-action backup check (non-blocking WARN) ---
    # Before any mutating action we verify a recent backup exists for the app and
    # WARN if not. This is advisory hygiene, never a gate: recoverability is a
    # separate concern from availability, so we never refuse to act on it.
    _warn_if_no_recent_backup(app_key)

    op_status = "completed"
    op_error: str | None = None
    try:
        if fix_type == "restart_container":
            result = _restart_container(app_key)
        elif fix_type == "repull_restart":
            try:
                metadata = json.loads(row["fix_metadata"] or "{}")
            except (ValueError, TypeError):
                metadata = {}
            result = _repull_restart(app_key, metadata)
        else:
            result = {
                "ok": False,
                "message": "fix_type not in safe tier",
                "fix_type": fix_type,
            }

        if result["ok"]:
            # --- verify health after a returncode-0 action ---
            healthy, summary = verify_container_healthy(app_key)
            if healthy:
                _mark_applied(fix_id, app_key, row, fix_type)
                record_attempt(app_key, fix_type, "success")
                result["message"] = result["message"] + "; " + summary
            else:
                _mark_failed(fix_id, app_key, row, fix_type)
                record_attempt(app_key, fix_type, "failed_verification")
                op_status = "failed"
                result = {
                    "ok": False,
                    "message": summary,
                    "fix_type": fix_type,
                }
        else:
            op_status = "failed"
            record_attempt(app_key, fix_type, result.get("outcome", "failed"))

        return result
    except Exception as _e:
        op_status = "failed"
        op_error = str(_e)
        raise
    finally:
        try:
            with StateDB() as db:
                db.complete_operation(op_id, status=op_status, error=op_error)
        except Exception as _fin_e:
            log.warning("apply_safe_fix: complete_operation failed for op_id=%s: %s", op_id, _fin_e)


# ---------------------------------------------------------------------------
# Private helpers — pre-risky-action backup verification (non-blocking)
# ---------------------------------------------------------------------------


def _warn_if_no_recent_backup(app_key: str) -> None:
    """Log a WARN when *app_key* opts into backup but has no recent one.

    Wholly best-effort: any failure to resolve the manifest, config_root, or
    backup state is swallowed (logged at debug) so the verification can never
    block or break a mutating action. Generic by app_key so it covers every
    current and future mutating action routed through ``apply_safe_fix``.
    """
    try:
        from backend.agent.backup import verify_recent_backup_before_action
        from backend.manifests.loader import load_manifest

        manifest = load_manifest(app_key)
        if not getattr(manifest, "backup_supported", False):
            return  # app has no durable state opted into backup — nothing to check

        config_root: str | None = None
        try:
            with StateDB() as db:
                config_root = db.get_platform().config_root
        except Exception as cr_err:
            log.debug("backup check: could not resolve config_root: %s", cr_err)

        ok, reason = verify_recent_backup_before_action(
            manifest, config_root, action=f"auto-apply on {app_key}"
        )
        if not ok:
            log.warning("pre-action backup check (%s): %s", app_key, reason)
    except Exception as exc:  # never let the backup check break the action
        log.debug("pre-action backup check skipped for %s: %s", app_key, exc)


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


def _repull_restart(app_key: str, metadata: dict[str, Any]) -> ApplyResult:
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


def _mark_failed(fix_id: int, app_key: str, row: Any, fix_type: str) -> None:
    """Insert a fix_history record with outcome 'failed_verification'.

    Does NOT update pending_fixes status — the fix is not considered applied
    since the container did not become healthy after the action.
    """
    with StateDB() as db:
        db.execute(
            """
            INSERT INTO fix_history
                (app_key, error_type, context, suggested_fix, outcome, created_at)
            VALUES (?, ?, ?, ?, 'failed_verification', unixepoch())
            """,
            (
                app_key,
                row["diagnosis_class"],
                fix_type,
                row["suggested_fix"],
            ),
        )
        log.info(
            "_mark_failed: fix_id=%s fix_history row inserted (failed_verification)",
            fix_id,
        )
