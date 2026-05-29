"""backend.agent.router.dispatch — Wire the routing engine into live dispatch.

``route_and_dispatch`` selects a complexity-appropriate provider chain via the
S-62 router (``select`` + ``available_providers``) and dispatches the call with
free/local-first bounded fallback.  EVERY per-provider call is routed through
``backend.health.checker._dispatch_llm_call`` so the S-61 ``scrub()`` choke
point (ADR-0018) is preserved unchanged — there is deliberately NO second
egress path in this module.

Graceful degrade is the overriding contract: if the router or its config is
unavailable, raises, or yields an empty chain, this falls back to today's exact
single-provider ``_dispatch_llm_call`` behavior so the agent never gets *worse*
at diagnosing because of routing.

v1 reuses the caller-supplied ``model`` / ``ollama_url`` for every provider in
the chain (no per-provider model matrix — see the wave's "Out of scope").
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from backend.agent.router.types import Tier

log = structlog.get_logger(__name__)


async def route_and_dispatch(
    client: Any,
    prompt: str,
    cfg: dict[str, Any],
    *,
    ollama_url: str,
    model: str,
    api_key: str,
    cloud_providers: set[str],
    max_tier: Tier = Tier.REASONING,
) -> str:
    """Select a provider chain and dispatch with free/local-first fallback.

    Behavior:
    - Build a :class:`RouteRequest` from *prompt* / *max_tier*, compute the
      available providers from *cfg*, and ask the router to ``select`` a chain.
    - EMPTY chain (or any router/config failure) → legacy single-provider
      ``_dispatch_llm_call`` using ``cfg['provider']`` so nothing regresses.
    - Otherwise try each provider in ``decision.chain`` at most once, in order,
      stopping on the first success.  Each attempt goes through
      ``_dispatch_llm_call(provider=name, ...)`` so scrub still applies
      per-provider.
    - On first success → ``log_decision(decision, outcome='success',
      chosen_provider=name, latency_ms=...)`` and return the text.
    - On exhaustion of the whole chain → ``log_decision(decision,
      outcome='all_failed')`` and return ``''``.

    Never raises: any unexpected failure degrades to the legacy path.
    """
    # Deferred imports: avoid circular dependency with backend.health.checker
    # and keep router/selector optional at module load.
    from backend.health.checker import _dispatch_llm_call

    legacy_provider = (cfg or {}).get("provider", "ollama")

    async def _legacy() -> str:
        """Today's exact single-provider behavior — the degrade target."""
        return await _dispatch_llm_call(
            client, prompt, ollama_url, legacy_provider, api_key, model, cloud_providers,
        )

    # ── 1. Build the routing decision (graceful degrade on any failure) ──────
    try:
        from backend.agent.router.registry import available_providers
        from backend.agent.router.selector import select
        from backend.agent.router.types import RouteRequest

        available = available_providers(cfg or {})
        decision = select(RouteRequest(prompt=prompt, max_tier=max_tier), available)
    except Exception as exc:
        log.warning("router.dispatch: selection failed; using legacy path", error=str(exc))
        return await _legacy()

    # ── 2. Empty chain → legacy single-provider path (no regression) ─────────
    if not decision.chain:
        log.debug("router.dispatch: empty chain; using legacy single-provider path")
        return await _legacy()

    # ── 3. Bounded free/local-first fallback over the chain ──────────────────
    start = time.monotonic()
    for name in decision.chain:
        try:
            raw = await _dispatch_llm_call(
                client, prompt, ollama_url, name, api_key, model, cloud_providers,
            )
        except Exception as exc:
            log.debug("router.dispatch: provider failed; trying next", provider=name, error=str(exc))
            continue
        # Success on the first provider that returns.
        from backend.agent.router.decisions import log_decision
        log_decision(
            decision,
            chosen_provider=name,
            outcome="success",
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return raw

    # ── 4. Whole chain exhausted ─────────────────────────────────────────────
    from backend.agent.router.decisions import log_decision
    log_decision(
        decision,
        outcome="all_failed",
        latency_ms=int((time.monotonic() - start) * 1000),
    )
    return ""
