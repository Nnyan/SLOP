# ADR 0006 — SQLite for the State Store (not Postgres)

**Status:** Accepted (backfilled 2026-05-08; the implicit decision dates from the v3 build, ~2024)
**Decided by:** OPUS during cleanup step 2.5.b (backfill)
**Supersedes:** none
**See also:** [`docs/adr/0001-database-migrations.md`](0001-database-migrations.md), [`backend/core/state.py`](../../backend/core/state.py), Core Rule 6.1 (Migration Discipline) — enforced by ms-enforce

> Enforcement: [manual — architectural axiom; the choice is implicit in `backend/core/state.py`'s `sqlite3` imports, the absence of a Postgres driver in `requirements.txt`, and `schema.sql`'s SQLite-flavoured DDL. Switching DBs would be a coordinated rewrite, not a drift-detectable invariant — reviewers flag any new PG-driver imports during code review.]

---

## Context

Mediastack stores: app catalog records, install history, health-check rows, operations log, audit log, settings, source-availability scans. Total volume on a busy homelab: tens of thousands of rows across 10–15 tables, growing slowly.

The database choice is one of the earliest architectural decisions and constrains operational ergonomics for the lifetime of the project. The candidates evaluated:

| Option | Pro | Con |
|---|---|---|
| **SQLite** (single file, library-embedded) | No daemon. No network port. Backups are file copies. `sqlite3 state.db` from any shell. Zero ops cost. | Single-writer (concurrent writers serialise on the WAL). No native replication. |
| Postgres (separate process) | Concurrent writers, native replication, mature tooling. | A second daemon on the host. Network port. Container or systemd unit to manage. Backups need pg_dump or WAL archiving. Roles, users, permissions. |
| MySQL/MariaDB | Same con as Postgres + worse SQL standard compliance. | — |
| Embedded NoSQL (e.g. LMDB, RocksDB) | Faster per-key operations than SQLite. | No SQL → custom query layer. Schema migration story is roll-your-own. |
| Spreadsheet / JSON files | Trivially inspectable. | Concurrent-access bugs are inevitable; no transactions. Discarded immediately. |

Mediastack is single-tenant, single-host, low-write-volume. The single-writer constraint of SQLite is not a constraint for Mediastack's load profile (the highest-frequency writer is the health scheduler at one cycle per minute). The lack of native replication is irrelevant for a single-host homelab.

The deciding axis is **operational cost**. A homelab user installs Mediastack to manage *other* services; they do not want Mediastack itself to require a database administrator's attention. Postgres adds:

- A second process to monitor and restart on failure.
- Backup tooling and a recovery procedure to document.
- A network port to firewall.
- Authentication credentials to manage.
- Version-upgrade choreography (Postgres major-version upgrades are non-trivial).

SQLite has none of these. The DB is one file; backing up Mediastack means copying that file. Restoring means putting the file back. There is no daemon to run.

## Decision

Mediastack uses **SQLite** as the state store. The DB file lives at `<config.data_dir>/state.db`. WAL mode is enabled (`PRAGMA journal_mode=WAL`). The Python `sqlite3` standard-library module is the driver; no external SQL library (SQLAlchemy, etc.) is added for the state store — direct parameterised SQL is used throughout `backend/core/state.py`.

Concurrent writes from the FastAPI handlers, the health scheduler, the wizard, and CLI tools all serialise through `StateDB` (a per-call connection wrapper with `BEGIN IMMEDIATE` on writes per Core Rule 4.4). The connection pool is "one connection per `with StateDB() as db:` block" — short-lived, no connection pooling library.

Migrations are managed by the custom runner (ADR 0001) — not Alembic, not Postgres-specific tooling.

If Mediastack ever grows beyond single-host (multi-user, multi-replica), this ADR will be superseded. The schema lives in plain SQL (`backend/core/schema.sql`), and the abstraction boundary at `StateDB` keeps the SQL surface inspectable, so a Postgres migration is a real but not impossible cutover. **None of that is on the roadmap**, and accepting an upgrade cost for a hypothetical future scale would be premature optimisation.

## Consequences

### Positive

- **Zero operational surface beyond Mediastack itself.** Operators don't manage a separate database process.
- **Backup is `cp state.db state.db.bak`.** Restore is `cp state.db.bak state.db`. The migration runner takes a hot-copy backup before applying a migration (cf. ADR 0001) using exactly this mechanism.
- **DB inspection is `sqlite3 state.db`** — every operator's environment already has the SQLite CLI.
- **Test fixtures use real SQLite** (`tmp_path / "state.db"`). No mocks, no in-memory wrappers, no driver substitution. Test reality matches production reality (Core Rule 2.5).
- **Schema introspection is trivial** — `.schema` in the SQLite shell prints the entire DDL. `tools/regenerate-schema-sql.py` reads the migrations directory to keep `backend/core/schema.sql` in sync as the canonical reference.

### Negative

- **Single-writer serialisation.** Concurrent writers wait. For Mediastack's load this is invisible (the health scheduler holds the write lock for milliseconds at most). For a higher-write-rate use case it would be a real ceiling.
- **No native replication.** A failover replica means cron-rsync of the DB file, not streaming replication. Acceptable for the homelab single-host model; not acceptable for production HA.
- **No row-level locking.** Postgres can have one writer holding row 5 in `apps` while another writes row 9 in `apps`; SQLite serialises all writes. Again, acceptable for the load profile.
- **Migrations are home-grown** rather than industry-standard. We bear the maintenance cost of `tools/regenerate-schema-sql.py`, the migration runner, and the discipline (Core Rule 6.1) that goes with them.

### Neutral

- **The state surface is small enough that the choice doesn't matter for performance.** A query that's 0.5ms in SQLite is 0.3ms in Postgres; neither is the bottleneck. The bottleneck is `docker pull` and `docker compose up`, which dominate by 4+ orders of magnitude.
- **The decision is reversible.** If Mediastack moves to multi-tenant cloud at some point, the schema migrates to Postgres (or whatever fits) via a one-time data export. The `StateDB` abstraction layer keeps the surface narrow.

## Status

Accepted (backfilled). Documents a decision implicit in the v3/v4 build; ratified explicitly during cleanup step 2.5.b on 2026-05-08. No supersession in flight.
