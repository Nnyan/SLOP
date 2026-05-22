# ADR 0005 — API Versioning via URL-path Prefix

**Status:** Accepted 2026-05-08 (step 3.2.a)
**Decided by:** OPUS during cleanup step 3.2 (API Versioning)
**Supersedes:** none — pre-3.2, all routes lived at `/api/<area>` with no version.

**See also:** [`docs/cleanup/PROJECT_CLEANUP.md`](../cleanup/PROJECT_CLEANUP.md) step 3.2, [Core Rule 4.18 (API Versioning Discipline)](../CORE_RULES.md#418-api-versioning-discipline)

---

## Context

Mediastack is at v4.0.0. The HTTP API is consumed by:

1. **The Vue SPA** at `frontend/src/` — same codebase, can be migrated in lockstep with backend.
2. **CLI tools** (`ms-update`, `ms-check`, `ms-status`, etc.) — same codebase, lockstep migration possible.
3. **Operator scripts and curl one-liners** — outside the repo. Each route rename or response-shape change risks silently breaking these.
4. **The future plugin / external-app surface** (out of scope today, but the architecture should leave room).

Pre-3.2, every route was mounted at `/api/<area>/<path>` with no version segment. Any breaking change required a coordinated rename + a redeploy of every consumer at the same time. There was no way to run an old client against a newer server without immediate breakage.

## Decision

API routes are versioned by **URL-path prefix** — `/api/v1/<area>/<path>` — with the unversioned `/api/<area>/<path>` form retained as a **deprecated alias** for one major release cycle.

### Versioning scheme: URL path, not header

Considered alternatives:

| Scheme | Pro | Con | Verdict |
|---|---|---|---|
| URL path `/api/v1/...` | Trivially debuggable in browser/curl. Cacheable per-version. Path is a first-class concept in HTTP. | Slightly more verbose. | **Chosen.** |
| Header `Accept: application/vnd.mediastack.v1+json` | More "RESTful". Same URL works across versions. | Headers are invisible without `curl -v`. Caches keyed on URL miss them by default. Adds friction to the homelab debug loop. | Rejected. |
| Query parameter `?v=1` | Same URL works across versions. | Easy to forget. Harder to grep for. | Rejected. |

URL path wins on debuggability for a single-user homelab where the operator runs `curl http://mediastack.local:8080/api/v1/health/summary` from the terminal and expects the URL to tell them what version they're hitting.

### Mount strategy: dual-mount during the transition

`backend/api/main.py` mounts each router at **both** prefixes:

```python
# Pseudocode
def _mount(module, name, tag):
    app.include_router(module.router, prefix=f"/api/v1/{name}", tags=[tag])
    app.include_router(module.router, prefix=f"/api/{name}",    tags=[tag, "deprecated"])
```

Both prefixes hit the same `APIRouter` instance, so every endpoint is reachable at both URLs with identical behaviour. The dual mount means:

- v4 frontend code continues to work unchanged (still hits `/api/...`).
- New consumers can adopt `/api/v1/...` immediately.
- Tests can verify equivalence (same request body, same response body) at both paths.

### Deprecation signaling

Requests to the unversioned `/api/<area>/<path>` paths get a response header:

```
Deprecation: true
Link: </api/v1/<area>/<path>>; rel="successor-version"
Sunset: Mon, 01 Sep 2026 00:00:00 GMT
```

Per [RFC 8594 (Sunset)](https://datatracker.ietf.org/doc/html/rfc8594) and [draft-ietf-httpapi-deprecation-header](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-deprecation-header). The `Sunset` date is a soft commitment; the actual removal happens in v5.x once frontend + CLI migrations are complete.

The non-API surface (`/`, `/assets/...`, `/{full_path:path}` SPA fallback, `/api/coverage`, `/api/ping`) is **not** versioned. Those are infrastructure routes, not the application API.

### Deprecation policy

- **/api/v1/** is supported indefinitely until /api/v2 lands.
- **/api/** (unversioned alias) is deprecated as of 3.2 (2026-05-08) — it carries a `Deprecation: true` response header today.
- **/api/** removal target: **Mediastack v5.0** (no firm date — driven by the frontend-migration work of step 3.2.e and the CLI-migration work tracked in `docs/cleanup/PROJECT_CLEANUP.md`).
- When **/api/v2/** lands (next breaking change), **/api/v1/** enters a 1-major-version deprecation window with the same `Deprecation` + `Sunset` headers.
- **No version is ever silently changed.** A breaking change to a v1 route's response shape, request shape, status codes, or error format means a new `v2/` route. Additive changes (new fields, new optional query params) stay in v1.

## Consequences

### Positive

- **Operators can curl any endpoint from a terminal and immediately see which version they're talking to.** That's the homelab debug-loop primary axis.
- **The Vue SPA can be migrated route-by-route** to /api/v1/ without coordinating a backend release. The dual mount means each frontend file's migration is its own atomic change.
- **Tests can verify version-equivalence** end-to-end. Step 3.2.f (`tests/test_api_versioning.py`) does exactly that — same request body, same response body, both prefixes.
- **External consumers get a real deprecation signal** (`Deprecation: true`) before /api/ is removed in v5. Anyone scraping the response header sees the warning months in advance.
- **Path-based versioning composes with existing tooling** — ruff, mypy, the openapi schema, test fixtures all see the route as a single string and can grep / regex it without HTTP-header awareness.

### Negative

- **Every router-mount line is duplicated** in `main.py` until the unversioned form is removed. Mitigated by the `_mount()` helper that owns the duplication in one place.
- **OpenAPI schema lists every endpoint twice.** The `tags=["...", "deprecated"]` on the legacy mount makes Swagger UI group them visibly so it's not noise.
- **Cache poisoning risk** — if a CDN/proxy caches `/api/health/summary` for 60s and a client switches to `/api/v1/health/summary`, the two are independent cache keys. For the homelab single-tenant case this is negligible; for an external deployment with a CDN it would matter.

### Neutral

- **The `_mount()` helper takes a module, name, and tag** — three args per call. The rate-limiter `@limiter.limit("...")` decorators on individual routes work unchanged because they decorate the `APIRouter` method, not the prefix.
- **`/api/quickstart` is special** — its router has `prefix="/api/quickstart"` baked in via `APIRouter(prefix=...)`. The dual-mount helper handles this case by leaving the existing mount untouched and adding a parallel `/api/v1/quickstart` mount.

## Status

- 3.2.a/b: this ADR (2026-05-08).
- 3.2.c: `_mount()` helper + dual-mount of every router in `backend/api/main.py`.
- 3.2.d: deprecation-header middleware for unversioned `/api/<...>` requests.
- 3.2.e: `frontend/src/apiClient.js` (centralized helper that prepends `/api/v1/`); existing raw `fetch('/api/...')` callers migrate incrementally.
- 3.2.f: `tests/test_api_versioning.py` verifies parity + deprecation header.
- 3.2.g: Core Rule 4.18.

---

## Future versions

When the next breaking change to the API surface arrives, the **`/api/v2/` cutover** follows a documented runbook:

[`docs/cleanup/STEP_3_2_V2_PLAYBOOK.md`](../cleanup/STEP_3_2_V2_PLAYBOOK.md)

Highlights:
- The dual-mount becomes a triple-mount during the v1 → v2 transition.
- `DeprecationHeaderMiddleware` extends to flag `/api/v1/<area>` for areas that have a v2 successor (the existing `/api/<area>` flagging stays unchanged).
- Frontend `client.ts` BASE bumps `'/api/v1'` → `'/api/v2'`.
- After 1 major version, `/api/v1/<area>` deprecation alias is removed.

The playbook also enumerates the change classes that DO require a version bump (response field removal, type change, status semantics shift, etc.) versus those that DON'T (additive fields, new optional params, new routes, internal refactors). When in doubt, err on the side of v2 — compatibility is cheap, trust is expensive.

A rehearsal procedure is documented for verifying the framework end-to-end before the first real v2 ships: a throwaway `/api/v2/ping` mount + the existing 19 contract tests, removed before merge.
