# ADR 0001 — Database Migrations: Custom Numbered Files (not Alembic)

**Status:** Accepted 2026-05-05 (step 1.1.b — implemented at the same time)
**Decided by:** OPUS during cleanup step 1.1
**Supersedes:** none
**See also:** [`docs/cleanup/STEP_1_1_DB_MIGRATIONS_STRATEGY.md`](../cleanup/STEP_1_1_DB_MIGRATIONS_STRATEGY.md), Core Rule 6.1 (Migration Discipline) — enforced by ms-enforce
**Review by:** 2028-05-05

> Enforcement: [automated — ms-enforce checks `check_migration_sequence`, `check_py_migration_api`, `check_schema_sql_sync`, `check_no_adhoc_create`; `tests/test_migrations.py` exercises the runner]

## Context

Pre-1.1, `init_db()` was called on every startup and ran `CREATE TABLE IF NOT EXISTS` plus a sequence of inline `ALTER TABLE` patches. Three production bugs shipped because of this pattern:

1. A `CHECK` constraint update was a no-op against existing tables — schema "applied" silently differed from declared.
2. A column rename via `ALTER` was followed by code that referenced the old name; tests passed because they used freshly-created DBs.
3. An infra-tunnel-providers table drift — the inline migration ran every startup, no version tracking, no audit trail.

Constraints:

- **SQLite, not Postgres.** Many migration tools assume PG (`Alembic` works with both, but its SQLite story has known limitations around DDL transaction semantics).
- **Single deploy unit, no split between dev/staging/prod.** The migration system needs to handle: fresh-install (no DB), upgrade-existing (apply pending), and the homelab restore-from-backup scenario.
- **Operator-facing.** Mediastack is run by single individuals, not DBA teams. The migration pipeline must be readable: any human cloning the repo should be able to look at `migrations/` and understand schema history.

## Decision

Use a **custom numbered-file migration system** rather than Alembic.

- Migration files live in `migrations/` at repo root, numbered `001_baseline.sql`, `002_normalize_apps_status_check.sql`, etc.
- Both `.sql` and `.py` migrations supported. `.py` files implement an `apply(conn: sqlite3.Connection)` function — used when DDL alone can't express the change (e.g., copy data + drop column).
- A `schema_migrations` table tracks applied migrations by number. `init_db(db_path)` runs `run_migrations(db_path)` which:
  1. Detects fresh-install (no `schema_migrations`) vs upgrade-existing.
  2. For existing databases without the table, *stamps* at the v3 baseline (the last pre-migration-system state).
  3. Applies all pending migrations in numeric order.
  4. Takes a hot-copy backup before each migration (so a partial failure can be rolled back via filesystem restore).
- Migrations are idempotent at the file level (the same numbered file is never re-applied) but NOT at the SQL level (a migration may use `CREATE TABLE` not `CREATE TABLE IF NOT EXISTS`).

## Consequences

### Positive

- **Auditable history.** `migrations/` is the schema's git log. Reviewers can see exactly what changed in every release.
- **Fail loud, fail fast.** Migration errors abort `init_db()` and the FastAPI lifespan never serves a request — the operator MUST address the failure before the service comes back up.
- **Hot-copy backup per migration.** Worst-case recovery is a filesystem restore, not data loss.
- **No new dependency.** Avoids Alembic's transitive deps and SQLite-specific quirks.

### Negative

- **No declarative schema.** Reviewers can't see "the current schema" without applying every migration mentally. Mitigation: `schema.sql` mirrors the post-migration state and is enforced to match by `ms-enforce check_schema_sql_sync`.
- **No auto-generation of migration files.** Operators write the SQL by hand. Acceptable because the schema doesn't churn — most weeks zero migrations, occasional bursts when a feature lands.
- **Custom code to maintain.** The migration runner (`backend/core/migrations.py`) is ~150 LOC; less than Alembic but it's ours.

### Neutral

- The choice doesn't preclude switching to Alembic later if the team / tooling needs grow. The numbered-file convention maps onto Alembic's revision IDs cleanly.

## Status

Accepted; in production. Enforced by:

- `ms-enforce` Tier 1: `check_migration_sequence`, `check_py_migration_api`, `check_schema_sql_sync`, `check_no_adhoc_create`. Each is a Core Rule 6.1 derivative.
- `ms-coverage` rule `migration-discipline` (added in 1.1.g).
- `tests/test_migrations.py` exercises the runner on a temp DB.

Revisit when:

- Schema churn exceeds ~1 migration per week for several months (then auto-generation matters).
- A multi-environment deploy story emerges (then Alembic's branching becomes worth the cost).
- An operator reports the migration UX is too rough.
