"""backend.agent.router.decisions — Decision logging for the LLM routing engine.

Emits a structured log event for each RouteDecision so that routing choices
are observable via the structlog pipeline without any database writes.

This is intentionally log-only in batch 1.  Persistence / metrics can be
added in a later batch once the routing pipeline is fully wired.
"""

from __future__ import annotations

import structlog

from backend.agent.router.types import RouteDecision

log = structlog.get_logger(__name__)


def log_decision(decision: RouteDecision) -> None:
    """Emit a structured log event describing *decision*.

    Fields emitted:
        event:   "router.decision"
        tier:    Tier name string, e.g. "SIMPLE"
        chain:   List of provider names in dispatch order
        reason:  Human-readable explanation from the selector

    No database writes.  No exceptions are raised — errors are logged as
    warnings so the caller is never blocked by a logging failure.
    """
    try:
        log.info(
            "router.decision",
            tier=decision.tier.name,
            chain=decision.chain,
            reason=decision.reason,
        )
    except Exception as exc:  # pragma: no cover — defensive only
        log.warning("router.decisions: failed to log decision", error=str(exc))
