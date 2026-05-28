# ADR 0014 — Frontend Build and Release Policy

- **Date:** 2026-05-15
- **Accepted:** 2026-05-19 (Step 4.5 audit gate — Option C confirmed)
- **Deciders:** Opus + operator (Step 4.5 disposition)
- **See also:** V5_INSTALLER_PLAN.md Step 2.5.a (design TBD note), TIER_4_HANDOFF.md §O1

> Enforcement: [manual — release-process discipline; the release-tag commit pre-builds `backend/static/` and commits the artifact, and `installer/frontend.py`'s idempotency guard short-circuits the npm pipeline when the pre-built output is present. Staleness is caught at the release-checklist level, not via static check.]

## Status

**Status:** Accepted — 2026-05-19

## Context

`installer/frontend.py::build_frontend()` currently runs `npm ci && npm run build` at
install time (Step 2.5.a).  The vite output lands in `backend/static/`.  After the
build, `node_modules/` is left in place — the Step 2.5.a note deferred the removal
decision to Step 2.8 dev-VM evidence.

Step 2.8 surfaces this as an intentional open question (O1) with four design options.
The decision has two downstream consequences that make it worth an ADR:

1. **Disk footprint.** A full `npm ci` leaves ~250–400 MiB of `node_modules/` on the
   host.  Most of that is build-tool-only (vite, rollup, esbuild, plugins); the runtime
   needs only the compiled `backend/static/` output.

2. **Install time and network dependency.** Running `npm ci` at install time requires
   internet access to the npm registry, adds 60–120 s to the install on a typical
   home-lab connection, and introduces a failure mode (npm registry unavailable) that
   pre-baked artifacts would eliminate.

This ADR was Proposed at authoring time; the four options below were ready for
operator + Opus decision at v5.0 release planning (V5_INSTALLER_PLAN.md Step 4.5).
Option C was selected at Step 4.5 — see §Decision.
The install-smoke divergence note in `tools/install-smoke` reflects the pre-decision state.

## Options

### Option A — Keep `node_modules/` after build (current behaviour)

`build_frontend()` runs `npm ci && npm run build` and returns.  `node_modules/` stays.

**Pros:** Simplest implementation; operator can re-run `npm run build` from the install
dir without fetching deps again; no post-build cleanup step to maintain.

**Cons:** ~250–400 MiB persistent on host; network required at install time; npm
registry is a failure surface; install duration is longer.

### Option B — Remove `node_modules/` after successful build

`build_frontend()` runs `npm ci && npm run build`, then removes `frontend/node_modules/`.

**Pros:** Recovers ~250–400 MiB immediately; install dir is smaller and more auditable.

**Cons:** Re-building after an upgrade requires a fresh `npm ci`; operator loses the
"re-run build in place" escape hatch; removal adds a real-but-small failure surface
(permission errors on cleanup).

### Option C — Pre-build during CI/release; ship only build artifacts

The release tag process pre-builds `backend/static/` and commits it to the repo.
`installer/frontend.py` is a no-op for tagged releases (detects pre-built output).

**Pros:** Eliminates npm and network from the install path entirely; fastest install;
artifacts are auditable from git history.

**Cons:** Largest repo size increase (compiled assets committed); build-artifact
staleness is a new failure mode if the CI step is skipped; requires CI infrastructure
(GitHub Actions or equivalent) to be wired before v5.0.0 ships.

### Option D — Deferred: document as v5.1 scope, freeze at Option A for v5.0

Accept Option A for v5.0.0 to not block the release.  File a concrete v5.1 task to
evaluate Options B or C with real VM disk-usage data from Tier 3 testing.

**Pros:** Unblocks v5.0 release; real data informs the v5.1 decision.

**Cons:** The disk and network costs ship in v5.0 with no mitigation.

## Decision

Option C selected. `backend/static/` pre-built artifacts are committed to the
repository; `installer/frontend.py`'s idempotency guard (lines 125–126)
implements Option C by detecting pre-built output and short-circuiting the
npm pipeline. This formalizes behavior in place since pre-v5.0 work; the
v5.0.0 audit gate (V5_INSTALLER_PLAN.md Step 4.5) confirms current state
matches Option C and accepts the ADR accordingly.

For source-based installs (git clone of a development branch without
pre-built artifacts), `build_frontend()` runs the full npm pipeline as
before. Option C applies specifically to tagged-release installs where
`backend/static/index.html` is already present in the checkout.

Tier 3 VM disk-usage data is moot under Option C since npm never runs on
tagged installs. The network-dependency and disk-footprint costs named in
the Context section do not apply to the v5.0.0 release path.

## Consequences

### Positive

- The decision space is documented; future Opus/Sonnet sessions have the tradeoffs
  in one place rather than rediscovering them.
- npm, node_modules, and network registry access are eliminated from the tagged-release
  install path. Install time and disk footprint are minimized for operators.

### Negative

- Build-artifact staleness is a new failure mode if the CI/release step that refreshes
  `backend/static/` is skipped before tagging. Mitigation: make the refresh step part
  of the release checklist (RELEASE_PROCESS.md).

### Neutral

- `installer/frontend.py` source is unchanged by this ADR; the idempotency guard that
  implements Option C was already present.
- Source-based installs (development branches) continue to run the full npm pipeline.
