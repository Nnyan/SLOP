# S-63-ROUTER-WIRING-AND-COST — Wire the router into live dispatch + persist decisions

## Goal
Wire the standalone router engine (S-62) into the live LLM dispatch path so that
diagnosis/health LLM calls select a complexity-appropriate provider with
free/local-first fallback, and persist every routing decision + outcome + cost to
a new `router_decisions` table. Each per-provider dispatch continues to go through
`_dispatch_llm_call`, which already scrubs external calls — so the S-61
anonymization choke-point is preserved unchanged. This wave deliberately FOLDS the
originally-separate "router wiring" and "cost/success persistence" items into one
wave because they share the `log_decision()` recording contract and persistence is
meaningless until wiring produces real decisions.

## Context
- S-62 shipped `backend/agent/router/` on main @ `084d9d8`:
  `select(req, available) -> RouteDecision(tier, chain, reason)`,
  `available_providers(cfg) -> list[str]`, and `log_decision(decision)` which is
  **structlog-only** (no DB).
- S-61 shipped `scrub()` at the `_dispatch_llm_call` choke point plus the
  `ms-enforce::check_llm_outbound_scrubbed` gate — both on main. Wiring MUST keep
  that gate green.
- Current dispatch is single-provider: `backend/health/checker.py::_dispatch_llm_call(
  client, prompt, ollama_url, provider, api_key, model, cloud_providers, *, allow_raw=False)`.
  Two callers, neither router-aware:
  `backend/agent/classifier.py::_query_llm_for_diagnosis` (~line 153–170) and
  `backend/health/checker.py` (~line 586).
- Highest migration on main = `008` → this wave adds `009`.
- `pending_fixes`/`fix_history` are unaffected; this wave only adds `router_decisions`.

## Rules to follow
- `backend/agent/**` and `backend/health/**` hard cap 500 lines (soft 400). The new
  dispatch helper lives in its own module `backend/agent/router/dispatch.py`.
- MUST NOT bypass scrub: every outbound call continues through `_dispatch_llm_call`
  (per-provider), so `check_llm_outbound_scrubbed` stays green. Do not add a second
  egress path.
- Fallback is bounded: try each provider in `decision.chain` at most once, stop on
  first success. On an EMPTY chain (no router-eligible providers), fall back to
  today's single-provider `_dispatch_llm_call` behavior so nothing regresses.
- Graceful degrade: if router/config is unavailable or raises, preserve today's
  exact diagnosis behavior (the agent must never get WORSE at diagnosing because of
  routing).
- Migration must be the next sequential number; confirm with `ls migrations/`
  (expect `009`). `check_migration_sequence` + `check_py_migration_api` stay green.

## Authorized deletions
- None expected.

## Parallelization
This batch fires under ONE orchestrator covering all waves (one-orchestrator-per-batch
rule); the assignments below govern only THIS wave's subagents. **Coordinator = opus.**
Stream A (persistence foundation) merges to the wave branch first; B (wiring) codes
against A's `log_decision` signature; C (integration tests) after A+B.

| Stream | Model | Subagent type | Scope |
|---|---|---|---|
| A — persistence | sonnet | `general-purpose` in worktree | `backend/agent/router/decisions.py` (edit), `migrations/009_router_decisions.sql` (new), `backend/core/schema.sql` (edit), `tests/test_router_decisions.py` (new) |
| B — dispatch + wiring | opus | `general-purpose` in worktree | `backend/agent/router/dispatch.py` (new), `backend/health/checker.py` (edit the ~586 caller), `backend/agent/classifier.py` (edit `_query_llm_for_diagnosis`) |
| C — integration tests | sonnet | `general-purpose` in worktree | `tests/test_router_wiring.py` (new) |

## Deliverables

### Stream A — persistence (defines the contract B codes against)
- `migrations/009_router_decisions.sql`: create `router_decisions`
  (`id` PK, `prompt_chars` INT, `tier` TEXT, `chain` TEXT (JSON array),
  `chosen_provider` TEXT, `outcome` TEXT, `cost_usd` REAL, `latency_ms` INT,
  `created_at` INT default unixepoch()) + index on `created_at` and on
  `chosen_provider`. Mirror into `backend/core/schema.sql` (schema-sync check).
- Extend `router/decisions.py` to the EXACT signature (Stream B depends on this):
  ```python
  def log_decision(
      decision: RouteDecision, *,
      chosen_provider: str | None = None,
      outcome: str | None = None,       # 'success' | 'all_failed' | None
      cost_usd: float | None = None,
      latency_ms: int | None = None,
  ) -> None:
      """Emit the structlog event (unchanged) AND best-effort insert a
      router_decisions row. Never raises. Existing single-arg callers
      (cli.py dry-run) keep working — extra kwargs are optional."""
  ```
- Tests: row written with/without outcome; None-safe; never raises on DB error.

### Stream B — dispatch helper + wiring
- `backend/agent/router/dispatch.py`:
  ```python
  async def route_and_dispatch(
      client, prompt: str, cfg: dict, *,
      ollama_url: str, model: str, api_key: str, cloud_providers: set[str],
      max_tier: Tier = Tier.REASONING,
  ) -> str:
      """Select a provider chain and dispatch with free/local-first fallback.
      Empty chain → legacy single _dispatch_llm_call(cfg provider). Each chain
      entry dispatched via _dispatch_llm_call(provider=name, ...) so scrub
      applies. On first success → log_decision(outcome='success', chosen_provider=name)
      and return. On exhaustion → log_decision(outcome='all_failed') and return ''."""
  ```
- Wire `_query_llm_for_diagnosis` (classifier) and the checker.py ~586 caller to use
  `route_and_dispatch`. Preserve existing return semantics (graceful '' / None on
  failure exactly as today).
- Per-provider url/model: v1 reuses the cfg url/model for the call (do not build a
  per-provider model matrix — see Out of scope).

### Stream C — integration tests (`tests/test_router_wiring.py`)
- Fallback: first chain provider raises → second is used → success.
- Scrub preserved: a cloud provider in the chain → outbound payload is scrubbed
  (mock httpx, assert identifiers redacted).
- Empty chain → legacy single-provider path is taken (no regression).
- A `router_decisions` row is persisted with the chosen provider + outcome.

## Verification
1. `.venv/bin/pytest tests/test_router_decisions.py tests/test_router_wiring.py tests/test_router_registry.py tests/test_router_selection.py tests/test_router_cli.py -v` — all pass.
2. `python3 ms-enforce` — exit 0. **Especially `check_llm_outbound_scrubbed` (must stay green), `check_migration_sequence`, `check_py_migration_api`, mypy, file-size ratchet.**
3. `python3 -m backend.agent.router status` still runs end-to-end.

## Out of scope
- Routing the `scheduler.py` weekly-summary LLM call (it's a local-only ollama call;
  minor follow-up, not worth the cross-file coupling with S-64).
- Per-provider model/url configuration matrix (v1 reuses the existing cfg url/model).
- Any frontend/Vue surface for routing decisions (CLI + DB only this wave).
- Safe-tier auto-fix (S-64).

## Cross-wave dependencies (EXPLICIT)
- **Depends only on already-merged main** (`084d9d8`: S-61 scrub + S-62 router engine).
  Self-contained — no dependency on S-64.
- **Independent of and file-disjoint from S-64** (this wave: `router/*`, `checker.py`,
  `classifier.py`, migration `009`; S-64: `scheduler.py`, `autofix.py`). **May merge to
  main in ANY order relative to S-64.**
- Adds the ONLY migration in batch 2 (`009`) — no numbering collision with S-64.

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine v4. Stream A merges to the wave branch
first; B then C. Coordinator merges all to `wave/S-63-router-wiring-and-cost`, never
main. Post-wave merge to main goes through the sanctioned operator channel.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-63-ROUTER-WIRING-AND-COST.md as orchestrator.`
