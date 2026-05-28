# ADR 0011 — Single-Tenant, Single-Operator Assumption

**Status:** Accepted (backfilled 2026-05-08; the implicit decision dates from the v3 build, ~2024)
**Decided by:** OPUS during cleanup step 2.5.b (backfill)
**Supersedes:** none
**See also:** [ADR 0006 (SQLite for the state store)](0006-sqlite-vs-postgres.md), [ADR 0010 (No plugin system)](0010-no-plugin-system.md), Core Rule 4.21 (Audit Trail Discipline) — enforced by ms-enforce
**Review by:** 2028-05-08

> Enforcement: [manual — architectural assumption that pervades many design choices (no auth on admin UI, `audit_log.actor='local'`, settings as global key/value, no tenant column on tables). It is not one drift-detectable property; introducing auth, RBAC, or per-tenant data isolation would be its supersession via a new ADR, not a check-detectable regression.]

---

## Context

Mediastack manages a homelab Docker stack on a single host. The user model: ONE operator (typically the host's admin). One person installs apps, configures the wizard, monitors health, runs ms-update. There is no notion of:

- Multiple users with distinct credentials.
- Role-based access control (admin vs viewer vs operator).
- Per-user audit trails (who installed sonarr? — the operator).
- Multi-tenant data isolation (one Mediastack manages one homelab).

This assumption is an architectural axis. Many design choices ripple from it:

- **No auth on the Mediastack API itself.** The user reaches it over LAN; they're trusted. Tinyauth/authelia (which Mediastack DOES support) gates the *managed apps*, not Mediastack's own admin UI.
- **Audit log records `actor='local'` for every entry** (Core Rule 4.21). The schema reserves the column for future multi-user mode.
- **Settings are global, not per-user.** Wizard choices, LLM agent config, ntfy URL — all single-valued.
- **The catalog is a single curated set** (plus the custom-manifest community/) with no per-user views.
- **State lives in one SQLite file** (ADR 0006) — not partitioned by tenant.
- **The frontend has no login screen.** Loading `https://mediastack.local:8080/` drops the operator straight into the dashboard.

Two paths were considered for the multi-tenant question:

1. **Defer multi-tenancy.** Build for the single-tenant case; preserve seams that allow future multi-tenancy without a full rewrite.
2. **Build multi-tenancy from day one.** Accept the up-front cost; have it ready when needed.

Path 2 has a textbook problem: building the wrong abstraction. Multi-tenancy designed without a real second tenant ships features that don't fit when the second tenant arrives. Path 1 keeps the seams clean (one connection per StateDB call, audit_log has an `actor` column, etc.) but doesn't pay multi-tenancy's design tax up front.

## Decision

Mediastack is **single-tenant, single-operator**. Multi-tenancy is **explicitly out of scope** for v4 and v5. The architecture preserves seams that would allow future multi-tenancy without a full rewrite, but does not implement it:

- `audit_log.actor` exists as a column with a default of `'local'`. When multi-user mode ships, the column is already there; only the value source changes.
- `StateDB` connections are per-call (no shared session state across users). Adding a tenant filter would mean adding a `WHERE tenant_id=?` clause to existing queries — a real cost, but a focused one.
- The settings store has a key/value structure that could grow a `(scope, key)` shape without breaking existing keys.
- The audit middleware records the `correlation_id` separately from the `actor` — telemetry is identity-aware in shape if not in current value.
- Tier 4 work (metrics, probes, audit) was explicitly designed not to assume single-tenant. The metrics labels are bounded; the audit schema is identity-aware. Activating Tier 4 in a multi-tenant deployment would require sourcing actor identity from a real auth layer, but the data model is ready.

If single-host single-tenant ever stops being the right model — Mediastack moves to multi-user, or scales to a hosted service — this ADR is superseded by an explicit multi-tenancy ADR that documents what changes (auth front door, tenant column on every table, settings scope, frontend route guards, etc.).

## Consequences

### Positive

- **Operational simplicity.** No auth provisioning at install time. The wizard's first screen is Stage 0 (system evaluation) — not "create an admin account".
- **Test reality.** Unit + integration tests don't carry "as user X" boilerplate. Every test is the operator. Step 2.6's always-fail cleanup did not have to wrestle with auth fixtures because there is no auth.
- **The audit log is a record, not a permission tool.** Rule 4.21's discipline is "what happened?", not "is this user allowed?". The latter is a category we deferred.
- **The threat model is small.** Internal homelab LAN access; trusted operator. We don't ship CSRF tokens, JWT secrets, password reset flows, or session timeouts. Each absence is a class of bug we don't have.
- **Tier 4 audit logging is honest.** `actor='local'` with a single operator is not a useless audit trail — it's a correct one. A pretend "user_id" populated from a fake auth layer would be worse.

### Negative

- **Cannot share a Mediastack across multiple operators.** A household where two people both want to install / remove apps must coordinate manually. Some users want this; we don't serve them.
- **Cannot host Mediastack as a service** without a substantial multi-tenancy retrofit. We are not pursuing that, but if the project ever needed to, it's a real cost.
- **No "view-only" mode for guests.** Showing the dashboard to a non-operator means trusting them with full mutate access (or putting Tinyauth in front and calling it done). For a homelab this is fine; for a small-business deployment it's a ceiling.
- **Some Tier 4 features have shadow value.** Audit logging is most valuable in multi-user contexts where actor identity matters. In single-tenant mode the trail is "what did I do at 02:14 last Wednesday?" — useful but not critical. We accept this; the schema cost is small.

### Neutral

- **The decision is reversible**, and several Tier 4 / Tier 3 design decisions were explicitly made with reversibility in mind (audit schema, metrics labels, API versioning).
- **Single-host doesn't mean single-machine forever.** Mediastack could run on a multi-node Docker Swarm or K3s cluster while still being single-tenant — many operators, one stack. The ADR's "single tenant" axis is independent of "single host" and the K8s probe support (ADR/Core Rule 4.20 from step 4.2) reflects this.
- **The decision rules out certain integrations.** OAuth login flows, LDAP/SAML, multi-org tenant management — none ship. Users who need those run a different tool or pair Mediastack with one.

## Status

Accepted (backfilled). Documents a decision implicit in the v3/v4 build; ratified explicitly during cleanup step 2.5.b on 2026-05-08. No supersession in flight.
