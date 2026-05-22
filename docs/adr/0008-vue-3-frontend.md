# ADR 0008 — Vue 3 (Composition API) for the Frontend

**Status:** Accepted (backfilled 2026-05-08; the implicit decision dates from the v3 build, ~2024)
**Decided by:** OPUS during cleanup step 2.5.b (backfill)
**Supersedes:** none
**See also:** `frontend/`, `frontend/src/api/client.ts`, [ADR 0005 (API versioning)](0005-api-versioning.md)

---

## Context

Mediastack's frontend is a single-page application (SPA) that talks to the FastAPI backend over the `/api/v1/...` surface. The app surfaces:

- A multi-step setup wizard (~10 steps; each step has its own validation + side effects).
- Per-app dashboards (apps catalog, install/uninstall, health).
- Settings (DNS, VPN, tunnel, auth, dashboard, container management providers).
- Operations history (install log, audit log).
- The topology view (coverage map data feed at `/api/coverage`).
- A model registry + LLM agent UI.

The framework choice constrains:

- The component model (template-based vs JSX-based; reactive primitives).
- The build pipeline (Vite vs webpack vs Rollup vs nothing).
- The state management story (Pinia vs Vuex vs Redux vs Zustand).
- The TypeScript ergonomics (Vue 3's TS support is good in Composition API; mediocre in Options API).
- The hiring / contribution surface (what does "knowing the frontend" mean for new contributors?).

The candidates considered (in roughly decreasing fit order):

| Framework | Fit |
|---|---|
| **Vue 3** (Composition API) | Single-File-Component ergonomics, tight Vite integration, TS support via `<script setup lang="ts">`, light learning curve for HTMLish thinkers. |
| React | Largest ecosystem, JSX flexibility, but: hooks lifecycle quirks, no first-class SFC, more boilerplate for small components. |
| Svelte | Smallest bundle, compile-time reactivity, but: smaller ecosystem, harder to find contributors, Svelte 4 → 5 migrations are non-trivial. |
| Solid | Fast, fine-grained reactivity, but: small community, treat-as-experimental at the time of decision. |
| HTMX + server-rendered Jinja | Simplest possible, but: forces every interaction to round-trip the server. The wizard's per-step validation + the install-progress polling are friction-heavy with HTMX. |

## Decision

The frontend is **Vue 3 with the Composition API**, built with **Vite**, written in **TypeScript** via `<script setup lang="ts">`. Pinia handles cross-component state (no Vuex).

Routing is `vue-router` v4. HTTP requests go through a centralised typed client at `frontend/src/api/client.ts` (Step 3.2.e moved its `BASE` from `/api` to `/api/v1` per ADR 0005). Raw `fetch('/api/...')` calls in individual `.vue` files are tolerated as legacy — they migrate to the typed client when a file is touched, not in a big-bang.

Styling is component-scoped CSS via SFC `<style scoped>`. No CSS-in-JS, no styled-components. A small `frontend/src/style.css` carries app-wide design tokens.

Build output lands in `frontend/dist/`. The FastAPI backend mounts that directory as static + SPA fallback (`/{full_path:path}` → `index.html`). No separate frontend server, no CDN. Operators run one process.

## Consequences

### Positive

- **SFC ergonomics fit the wizard well.** Each wizard step is a single component file with template + script + scoped style; reading one step's behaviour means reading one file.
- **`<script setup lang="ts">` gives strong TS ergonomics** — props, emits, and refs all type-check cleanly. Refactors are cheap.
- **Vite's dev server is fast.** HMR is ~50ms for SFC edits; the dev loop is tight.
- **The build is simple.** `npm run build` produces a static `dist/` directory; the backend serves it. No SSR, no edge functions, no runtime config injection.
- **Smaller learning curve than React for new contributors.** SFCs read top-down like HTML pages with a script tag. The Composition API is the modern style without being React-specific.
- **Pinia is small.** State stores are plain JS objects with TypeScript types; no reducers, no actions/mutations distinction, no middleware machinery.

### Negative

- **The ecosystem is smaller than React's.** Component libraries are fewer; fewer Stack Overflow hits per esoteric question. We mostly use first-party Vue libraries (vue-router, Pinia) which mitigates this.
- **The composition vs options API dichotomy** still surfaces in the docs and ecosystem. We standardise on Composition; older tutorials sometimes show Options. Contributors are warned in the README.
- **No SSR.** Every page reload re-runs the SPA bundle. For Mediastack's single-tenant homelab use case this is fine — page reloads are rare. For a public web app it would be a real con.
- **Bundle size** is bigger than Svelte/Solid. ~150KB gzipped at the time of writing. Acceptable for a homelab management UI; would matter on mobile-network deployments.

### Neutral

- **TypeScript discipline is uneven across the file tree.** Newer files use strict types; older files have `any` leftovers. Step-by-step migration as files are touched.
- **The frontend test surface is mostly missing** — Playwright covers a thin slice (a few core navigation tests). Vue Test Utils + Vitest for component-level tests is on the deferred backlog. Mitigated by the contract tests in `tests/test_routes.py` + the snapshot tests of the `client.ts` JSON shapes (step 2.1).
- **The decision is reversible** but expensive. Migrating off Vue would mean rewriting every SFC; rewriting Pinia stores; redoing the routing config. Not on the roadmap.

## Status

Accepted (backfilled). Documents a decision implicit in the v3/v4 build; ratified explicitly during cleanup step 2.5.b on 2026-05-08. No supersession in flight.
