# S-62-MS-ROUTER — Complexity-tiered LLM router engine (standalone, registry-based)

## Goal
Build a SLOP-native LLM routing decision engine as a backend package: an explicit
provider registry, complexity scoring → tier, and fallback-chain ordering on
rate-limit/failure. Built standalone and fully unit-tested. Wiring it into the
live dispatch path is DEFERRED to a follow-up batch — this wave produces no
live-path edits, so it cannot conflict with S-61.

## Context
- Build ON the existing plumbing (do not duplicate): `_load_provider_config` +
  `_dispatch_llm_call` (`backend/health/checker.py`); provider sets
  `_CLOUD_PROVIDERS` / `_LOCAL_OAI_PROVIDERS` (`backend/core/agent.py`); config
  in settings key `llm_agent_config`.
- **ADR-0010 (`docs/adr/0010-no-plugin-system.md`) forbids plugin systems.** The
  router uses an EXPLICIT registry (frozenset/dict, like `_DEFAULT_STACKS` /
  `_SLOP_MANAGED_VARS`), NOT dynamic file/plugin loading.
- This wave is the engine only: given a prompt + provider availability it RETURNS
  a decision (tier + ordered provider chain). Actual dispatch stays with the
  existing `_dispatch_llm_call`. No new migration, no new API route, no main.py edit.

## Rules to follow
- New package `backend/agent/router/`; every module < 500 lines (soft 400).
- Explicit registry only (ADR-0010). No dynamic import of provider files.
- No persistence this batch (cost/success tracking → future batch). Decisions are
  returned and logged via structlog only.
- CLI-first surface; no Vue, no FastAPI route.

## Authorized deletions
- None.

## Parallelization
**Models:** coordinator = **opus**. Stream A (foundation) first; B∥C concurrent
after A merges (both import `router/types.py`). Stream B is **opus** — it carries
the wave's design judgment (complexity heuristic + fallback-chain ordering); the
rest are sonnet.

| Stream | Model | Subagent type | Scope |
|---|---|---|---|
| A — types + registry | sonnet | `general-purpose` in worktree | `backend/agent/router/__init__.py`, `router/types.py`, `router/registry.py` (all new), `tests/test_router_registry.py` (new) |
| B — scoring + selection | opus | `general-purpose` in worktree | `backend/agent/router/scoring.py`, `router/selector.py` (new), `tests/test_router_selection.py` (new) |
| C — decisions log + CLI | sonnet | `general-purpose` in worktree | `backend/agent/router/decisions.py`, `router/cli.py` (new, `python -m backend.agent.router status`), `tests/test_router_cli.py` (new) |

## Deliverables

### Stream A — types + registry
- `router/types.py`: `Tier` enum (`SIMPLE`/`STANDARD`/`COMPLEX`/`REASONING`),
  `@dataclass ProviderSpec(name, kind, tiers, cost_per_1k, local)`,
  `@dataclass RouteRequest(prompt, max_tier)`, `@dataclass RouteDecision(tier,
  chain: list[str], reason)`.
- `router/registry.py`: `PROVIDER_REGISTRY: dict[str, ProviderSpec]` covering the
  current provider set (ollama, llamacpp local; groq/google/anthropic/openai/
  openrouter/etc. cloud — derive names from `_CLOUD_PROVIDERS`/`_LOCAL_OAI_PROVIDERS`
  by import, do not edit core.agent). `available_providers(cfg) -> list[str]`
  filters by what `llm_agent_config` has configured.

### Stream B — scoring + selection
- `router/scoring.py`: `complexity_score(prompt: str) -> Tier` — heuristic on
  length, code-block/stacktrace presence, reasoning keywords. Deterministic.
- `router/selector.py`: `select(req: RouteRequest, available: list[str]) ->
  RouteDecision` — pick tier from score, build an ordered fallback chain
  (free/local first, paid fallback), capped at `req.max_tier`.

### Stream C — decisions log + CLI
- `router/decisions.py`: `log_decision(decision: RouteDecision) -> None` via
  structlog (no DB this batch).
- `router/cli.py`: `python -m backend.agent.router status` prints the registry,
  configured/available providers, and a dry-run decision for a sample prompt.

## Verification
1. `.venv/bin/pytest tests/test_router_registry.py tests/test_router_selection.py tests/test_router_cli.py -v` — pass.
2. `python3 -m backend.agent.router status` prints a coherent registry + sample decision.
3. `python3 ms-enforce` — exit 0 (no new migration/ADR; just confirm caps + ruff/mypy).
4. No `frontend/` changes, no `backend/api/main.py` edit.

## Out of scope
- Wiring the router into `_dispatch_llm_call` (future batch — must preserve the
  S-61 scrub check).
- Persistent cost/success tracking + migration (future batch).
- ZeroClaw, Docker-MCP, memU, self-training, Vue dashboards (rejected/deferred per scope review).

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine v4. Stream A first; B and C dispatched
concurrently after A merges to `wave/S-62-ms-router` (both import router/types).
Coordinator merges all to `wave/S-62-ms-router`, never main.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-62-MS-ROUTER.md as orchestrator.`
