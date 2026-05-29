# ADR 0003 — Structured Logging via structlog with Correlation IDs

**Status:** Accepted 2026-05-08 (step 2.3)
**Decided by:** OPUS during cleanup step 2.3.a + 2.3.c
**Supersedes:** the implicit pre-2.3 convention of `logging.getLogger(__name__)` + f-string messages
**See also:** STEP_2_3_STRUCTURED_LOGGING_STRATEGY.md (cleanup strategy doc moved to slop-process private repo), Core Rule 4.13 (Structured Logging Discipline) — enforced by ms-enforce
**Review by:** 2026-11-08

## Context

Pre-2.3 `backend/` had 153 logging call sites across 40 modules, all using the stdlib `logging` API with f-string event messages:

```python
log.info(f"App {key} installed at {path} ({elapsed:.2f}s)")
```

This format breaks down for incident response. When production fails at 3am, the on-call needs to:

1. Find every log line for a single failed request — there's no shared identifier across the chain.
2. Filter for "all install failures in the last hour" — but the relevant data is buried in interpolated strings, not greppable keys.
3. Correlate scheduler-cycle logs with the LLM diagnoses they produced — same problem.

Constraints:

- **Single-binary FastAPI service** — no separate log router; whatever ships with the process IS the production logger.
- **Mixed sync/async code** — `asyncio.create_task`, threading, in-process scheduler. Thread-locals leak; need contextvars.
- **Operator-facing CLI alongside server** — `ms-update`, `ms-test`, etc. share the codebase. Their stdout IS their UX; they must NOT route through the structured logger.
- **Migration burden** — 153 sites; can't rewrite all at once.

## Decision

Adopt `structlog` as the project's logging library, with these specifics:

1. **Schema** (always-present fields): `timestamp` (ISO 8601 UTC), `level`, `logger`, `event` (short string), `correlation_id`, `subsystem` (derived from logger name).
2. **Event-specific kwargs become first-class JSON keys.** `log.info("event", apps_checked=10)` produces `{"event": "event", "apps_checked": 10, ...}` — never `f"event ({apps_checked} checked)"`.
3. **Output format is env-driven**: `MEDIASTACK_LOG_FORMAT=json` for production; `console` (default) for dev.
4. **Correlation IDs propagate via Python `contextvars`.** The HTTP entry point is `CorrelationIdMiddleware`, which reads `X-Request-ID` (or generates a UUID), sets the contextvar, echoes the ID back as a response header. Async tasks spawned via `asyncio.create_task` inherit the contextvar automatically (this is why thread-locals don't work).
5. **Stdlib bridge via `ProcessorFormatter`.** Stdlib `logging.X(...)` calls (third-party libraries; not-yet-migrated modules) flow through the same processor chain — every log line emits the same schema regardless of which logging API the call site used.
6. **Exclusions.** `backend/core/logging.py` itself uses stdlib logging directly (it's the configurer). `backend/scripts/` (operator CLI) uses `print()` for UX — those outputs are pinned by snapshot tests under Core Rule 4.11 instead.

## Consequences

### Positive

- **Greppable production logs.** `grep correlation_id=X | jq '.event'` reconstructs a full causal chain in seconds.
- **Schema-stable downstream.** Frontend / dashboards / alert rules can key on JSON fields without parsing free-form text.
- **Async-safe by construction.** contextvars are inherited by `asyncio.create_task`; no special handling needed.
- **Backwards-compatible during migration.** The stdlib bridge means a module that hasn't been swept yet emits the same output as a swept one — no half-migrated period of unparseable logs.

### Negative

- **structlog adds ~20μs per log call** vs ~5μs stdlib. At 1000 logs/s production load that's 15ms/s of CPU — measurable but acceptable.
- **Existing log lines need rewriting** to take advantage of structured kwargs. f-string events still work but they bypass the value of structuring. The 2.3.e sweep handles 39 module-level bindings; the deeper rewrite of every event message is opportunistic.
- **Two patterns in the codebase during migration.** Once 2.3.e completes, the `log.X(f"...")` antipattern doesn't disappear — `ms-enforce check_logging_discipline` only catches `print(`, `logging.X(`, `logging.getLogger(`. F-string event messages are a soft smell that future refactors clean up.

### Neutral

- The CLI scripts (`ms-update`, `ms-test`) intentionally stay on `print()` — their output is operator UX, not telemetry. Snapshot tests (Rule 4.11) lock their format.

## Status

Accepted; in production at commit `851576a` (the 37-file sweep). Enforced by:

- `ms-enforce` Tier 2 `check_logging_discipline` — AST-walks `backend/`, MANDATORY (returns False on any finding) since the sweep completed.
- `ms-coverage` rule `structured-logging-discipline`.
- `tests/test_logging.py` covers configure/contextvar/middleware/bridge cases (14 tests).

Revisit when:

- structlog 6.x lands with breaking changes (currently pinned `>=24` which means v25+).
- A separate log shipper (Loki, Datadog) is wired up and the JSON renderer's exact field names need to align with its expectations.
- Performance overhead becomes measurable in profiles (currently it isn't).
