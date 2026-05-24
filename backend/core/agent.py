"""backend/core/agent.py

SLOP Agent — tier-0 system component registration.

This module owns the canonical constants for the SLOP Agent and provides
ensure_agent_registered() which is called at every backend startup to
guarantee the agent DB record and its baseline health check exist.

The SLOP Agent is NOT a Docker-based catalog app.  It is the backend process
itself acting as an autonomous monitor and remediator.  Its DB record
(tier=0, category="agent") is the anchor for health checks, operations, and
future pattern/remediation storage.

Tier meanings:
  0  — system component (SLOP Agent, future core services)
  1  — (reserved)
  2  — standard catalog app (default)
  3  — community / custom-installed app
"""
from __future__ import annotations

from backend.core.logging import get_logger
from backend.core.state import StateDB

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_KEY: str = "slop_agent"
AGENT_DISPLAY_NAME: str = "SLOP Agent"
AGENT_TIER: int = 0
AGENT_CATEGORY: str = "agent"
AGENT_SUBJECT_TYPE: str = "agent"

HEALTH_CHECK_AGENT_STATUS: str = "agent_status"


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def ensure_agent_registered() -> None:
    """Idempotent startup hook.

    Guarantees that:
    1. The slop_agent app record exists in the DB with tier=0, category="agent".
       If the record already exists, only display_name and manifest_source are
       refreshed — status, tier, and category are never overwritten on restart.
    2. A baseline health check row (subject_type="agent", status="unknown")
       exists so health queries always return a result.

    Safe to call multiple times — every operation is a no-op if the data is
    already correct.
    """
    with StateDB() as db:
        existing = db.get_app(AGENT_KEY)
        if existing is None:
            db.upsert_app(
                AGENT_KEY,
                display_name=AGENT_DISPLAY_NAME,
                tier=AGENT_TIER,
                category=AGENT_CATEGORY,
                status="registered",
                image="",
                image_tag="",
                container_name=AGENT_KEY,
                manifest_source="system",
            )
            log.info("SLOP Agent record created (tier=0)")
        else:
            # Refresh human-readable fields only; never touch status/tier/category
            db.upsert_app(
                AGENT_KEY,
                display_name=AGENT_DISPLAY_NAME,
                manifest_source="system",
            )

        # Register baseline health check if none exists yet.
        # Phase B will populate this with real connectivity status.
        existing_checks = db.get_health_checks(
            subject_type=AGENT_SUBJECT_TYPE,
            subject_key=AGENT_KEY,
        )
        if not existing_checks:
            db.upsert_health_check(
                subject_type=AGENT_SUBJECT_TYPE,
                subject_key=AGENT_KEY,
                check_name=HEALTH_CHECK_AGENT_STATUS,
                status="unknown",
                summary="SLOP Agent registered — health check pending",
            )
            log.info("SLOP Agent baseline health check registered")
