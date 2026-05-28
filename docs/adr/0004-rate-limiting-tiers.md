# ADR 0004 — Rate Limiting via slowapi with Localhost Bypass

**Status:** Accepted 2026-05-08 (step 2.4)
**Decided by:** OPUS during cleanup step 2.4.a
**Supersedes:** none (no rate limiting existed pre-2.4)
**See also:** [`docs/cleanup/STEP_2_4_RATE_LIMITING_STRATEGY.md`](../cleanup/STEP_2_4_RATE_LIMITING_STRATEGY.md), Core Rule 4.14 (Rate Limiting Discipline) — enforced by ms-enforce
**Review by:** 2026-11-08

> Enforcement: [automated — ms-coverage RULE `rate-limiting-discipline` anchored at `tests/test_rate_limiting.py::test_heavy_mutation_blocks_after_5`; six-case suite verifies the 429 path and the localhost bypass]

## Context

Pre-2.4 the FastAPI surface had zero rate limiting. The runaway-script failure mode is realistic: a misconfigured frontend retry loop, a buggy `ms-test` bisector, or an external client written without backoff can hit `/api/apps/{key}/install` hundreds of times per second. The single-process backend would queue, OOM, or deadlock on the install lock.

Constraints:

- **Mediastack is a homelab tool.** Single user, behind Traefik on a LAN. Real DDoS protection is Traefik's job; this rule's purpose is *correctness* — preventing misconfigured-client-induced self-DoS.
- **In-process backend.** Rate limit storage doesn't need to be persistent or distributed.
- **CLI tools and the in-process scheduler call the local API.** They cannot be throttled — `ms-update` would break, the health scheduler would miss cycles.
- **TestClient defaults to host `"testclient"`** — must be in the bypass list or every API integration test would 429 itself out.

## Decision

Use `slowapi` (a flask-limiter port for FastAPI) with these specifics:

1. **4 tiers**, picked by traffic shape:
   - Heavy mutation (`install`/`remove`/`replace`, `wizard/run`, `platform/reset`): **5/minute**.
   - Heavy read (LLM-triggering: `health/run`, `health/weekly-summary`, `models/*/evaluate`): **10/minute**.
   - Light mutation (settings, registry, storage, routing): **30/minute**.
   - Default (everything else, mostly GETs): **60/minute**.
2. **In-memory storage** (`memory://`) — single process, no Redis needed. Resets on restart, which is fine since the goal is runaway protection, not persistent quota.
3. **Localhost bypass via `key_func` returning `None`.** slowapi's documented behaviour: when `key_func` returns `None`, the request skips the limit entirely. The bypass list is `{"127.0.0.1", "::1", "localhost", "testclient"}`.
4. **HTTP 429 with the slowapi default body** when a limit is exceeded. `Retry-After` headers require additional middleware (deferred — limits are protective, not contractual).
5. **Per-endpoint decoration**, not blanket coverage. Each tier-deviating endpoint gets `@limiter.limit("N/minute")`. Endpoints without a decorator are unlimited (slowapi's `default_limits` kwarg requires `SlowAPIMiddleware`, which isn't registered — explicit decoration is clearer).
6. **No static enforcement (yet).** No AST pattern distinguishes "right limit" from "wrong limit." Reviewers cite Rule 4.14 + the strategy doc tier table when a new mutating endpoint lands without a decorator. A future `ms-enforce check_rate_limit_discipline` could AST-walk for `@router.post`/`put`/`delete` not paired with `@limiter.limit(...)`; deferred until needed.

## Consequences

### Positive

- **Frontend retry-storm protection.** A buggy retry loop hits 429 after 5 install attempts in a minute, instead of crashing the server.
- **Cheap to wire.** Per-decorator declaration; clear PR diffs; no separate config file.
- **CI tests pass.** TestClient bypass means rate limits don't pollute existing tests.

### Negative

- **No multi-user awareness.** Limits are per-IP. A NAT'd LAN with multiple users would share a bucket. Acceptable: Mediastack is single-user. Multi-user setups would key on auth token (out of scope).
- **Memory storage resets on restart.** A persistent attacker after a restart gets a fresh budget. Acceptable: this isn't a security boundary, just a runaway-script guard.
- **Default-unlimited for non-decorated endpoints.** Adding rate limiting to ALL endpoints would require slowapi's `SlowAPIMiddleware` + decoration discipline; we deliberately skipped the middleware to keep the surface small and the "decorate per endpoint" rule unambiguous.

### Neutral

- The bypass list including `"testclient"` is a leak of pytest internals into production code. Acceptable: it's a small allow-list with explicit names; the alternative (overriding TestClient's host string in every test) is more invasive.

## Status

Accepted; in production at commit `9973eba`. Enforced by:

- Process: reviewers cite Rule 4.14 + the tier table when a new mutating endpoint lands.
- `ms-coverage` rule `rate-limiting-discipline` — pytest anchor `tests/test_rate_limiting.py::test_heavy_mutation_blocks_after_5`.
- `tests/test_rate_limiting.py` (6 cases) verifies the 429 path AND the localhost bypass — regressions in either would silently break operations.

Revisit when:

- Mediastack grows multi-user support → switch from per-IP to per-token keying.
- A real DDoS materialises (LAN compromise, exposed instance) → register `SlowAPIMiddleware` and apply default limits across the board.
- An operator hits 429 on legitimate traffic → relax the specific endpoint's tier rather than the whole rule.
