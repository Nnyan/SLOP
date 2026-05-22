# Project Cleanup — Software Engineering Improvement Plan

**Source:** `docs/IMPROVEMENT_PLAN.md` (77 principles audited, 36 gaps, 19 partials)
**Process:** Each step completes fully (all sub-tasks ✓) before moving to the next.
**Update protocol:** After each step finishes with `ms-enforce --fast` clean and tests passing, mark the task ✓ DONE with completion timestamp and commit hash.

**Model assignments:**
- **[OPUS]** = design, diagnosis, judgment calls, anything where past mistakes happened
- **[SONNET]** = mechanical implementation, pattern application, well-documented patterns

---

## STATUS

- **Current Tier:** 1
- **Current Step:** 1.2 (Static Type Checking)
- **Last completed:** 1.1 — Database Migrations (2026-05-05)
- **Next action:** Opus designs mypy strategy (1.2.a)

---

## TIER 1 — Foundational (target: ~3 days)

### Step 1.1 — Database Migrations ✓ DONE 2026-05-05 [pending commit]
- [x] **1.1.a [OPUS]** Design migration system: rollback model, v3→v4 upgrade path, schema.sql role
- [x] **1.1.b [OPUS]** Decide on Alembic vs custom (SQLite-friendly), document in `docs/adr/0001-database-migrations.md`
- [x] **1.1.c [SONNET]** Scaffold `migrations/` directory; old `001_add_failed_status.sql` moved to `migrations/_legacy/`; no new dependency (custom runner per ADR)
- [x] **1.1.d [SONNET]** `migrations/001_baseline.sql` = header + schema.sql byte-copy; `tools/regenerate-schema-sql.py` added; CI test `test_schema_sql_in_sync_with_migrations` added
- [x] **1.1.e [OPUS]** `state.py:init_db()` calls `run_migrations()`, inline tunnel-sync block removed (lifted to migration 003)
- [x] **1.1.f [SONNET]** `tests/test_migrations.py` — 12 tests covering all 10 §6 scenarios (12 passed, 0 failed)
- [x] **1.1.g [SONNET]** `tools/ms-enforce.py` created with Tier 1 migration checks: sequence, py-api, schema-sync, no-adhoc-create
- [x] **1.1.h [SONNET]** Core Rule 5.19 / 6.1 (Migration Discipline) added to `docs/CORE_RULES.md` v1.5
- [x] **1.1.i [OPUS]** Verified on v3 DB copy — v3 stamping, drift normalization, tunnel migration all pass

### Step 1.2 — Static Type Checking with mypy [OPUS strategy + SONNET backfill]
- [ ] **1.2.a [OPUS]** Decide strictness (strict vs gradual), which modules first, accepted exclusions
- [ ] **1.2.b [SONNET]** Add `mypy` to requirements; create `mypy.ini` with config from 1.2.a
- [ ] **1.2.c [SONNET]** Backfill type hints: `backend/core/` first (config, state, compose, docker_client)
- [ ] **1.2.d [SONNET]** Backfill `backend/manifests/` next (executor, loader)
- [ ] **1.2.e [SONNET]** Backfill `backend/api/` (apps, health, platform, settings)
- [ ] **1.2.f [SONNET]** Backfill `backend/infra/providers/` and `backend/health/` and `backend/platform/`
- [ ] **1.2.g [SONNET]** Add `check_mypy()` to ms-enforce Tier 1; add to pre-commit hook
- [ ] **1.2.h [SONNET]** Tests: `test_mypy_clean.py` confirms strict pass on configured modules
- [ ] **1.2.i [SONNET]** Add Core Rule 5.16 (Type Discipline) + ms-coverage rule

### Step 1.3 — Conventional Commits + auto-CHANGELOG [OPUS policy + SONNET tooling]
- [ ] **1.3.a [OPUS]** Define commit type taxonomy: feat, fix, refactor, test, docs, chore, perf
- [ ] **1.3.b [SONNET]** Install commitizen or write custom commit-msg hook
- [ ] **1.3.c [SONNET]** Add commit-msg hook to `.git/hooks/` and to ms-setup-tools
- [ ] **1.3.d [SONNET]** Generate initial `CHANGELOG.md` from existing v4 history
- [ ] **1.3.e [SONNET]** Add `make changelog` target or `ms-changelog` tool
- [ ] **1.3.f [SONNET]** Tests: `test_commit_format.py` validates last 10 commits match format
- [ ] **1.3.g [SONNET]** Add Core Rule 7.1 (Commit Discipline)

### Step 1.4 — Cyclomatic Complexity Limits [OPUS judgment + SONNET enforcement]
- [ ] **1.4.a [OPUS]** Audit current backend/ for functions exceeding complexity 10; identify legitimate exceptions
- [ ] **1.4.b [OPUS]** Set max-complexity threshold per module (wizard.py may need higher initially)
- [ ] **1.4.c [SONNET]** Update `ruff.toml` to enable C901 with per-file overrides from 1.4.b
- [ ] **1.4.d [OPUS]** Refactor highest-complexity functions in wizard.py (step_traefik_deploy, step_deploy_infra)
- [ ] **1.4.e [SONNET]** Add `check_complexity()` to ms-enforce Tier 1
- [ ] **1.4.f [SONNET]** Tests: `test_complexity_thresholds.py` proves no regression
- [ ] **1.4.g [SONNET]** Add Core Rule 5.17 (Complexity Discipline)

### Step 1.5 — Test Independence Verifier [SONNET — well-documented pattern]
- [ ] **1.5.a [SONNET]** `pip install pytest-randomly`; add to requirements
- [ ] **1.5.b [SONNET]** Run with `--randomly-seed=1` and `--randomly-seed=2`; identify failures
- [ ] **1.5.c [OPUS]** Diagnose order-dependent failures; design correct fixture scoping
- [ ] **1.5.d [SONNET]** Fix each order-dependent test (proper fixture scope, isolation)
- [ ] **1.5.e [SONNET]** Add to GitHub Actions: run with random seed in CI
- [ ] **1.5.f [SONNET]** Add `check_test_independence()` to ms-enforce
- [ ] **1.5.g [SONNET]** Add Core Rule 4.10 (Test Independence)

---

## TIER 2 — High-Value Quality (target: ~5 days)

### Step 2.1 — Snapshot Testing for Stable Outputs [OPUS scope + SONNET implementation]
- [ ] **2.1.a [OPUS]** Decide what should have snapshot tests: ms-update banner, ms-test summary, ms-enforce output, /api/platform/status response shape
- [ ] **2.1.b [SONNET]** `pip install syrupy`; add to requirements
- [ ] **2.1.c [SONNET]** `tests/test_snapshots.py` with snapshot fixtures for items in 2.1.a
- [ ] **2.1.d [SONNET]** Generate initial snapshots; commit `__snapshots__/`
- [ ] **2.1.e [SONNET]** Document `--snapshot-update` workflow in CONTRIBUTING.md
- [ ] **2.1.f [SONNET]** Add to ms-enforce Tier 2
- [ ] **2.1.g [SONNET]** Add Core Rule 4.11 (Snapshot Discipline)

### Step 2.2 — Mocking Discipline Audit [OPUS — judgment-heavy]
- [ ] **2.2.a [OPUS]** Survey every mock in `tests/`; classify boundary (correct) vs internal (smell)
- [ ] **2.2.b [OPUS]** Write `docs/adr/0002-mocking-policy.md` documenting what should/shouldn't be mocked
- [ ] **2.2.c [OPUS]** Identify highest-risk over-mocked tests (Q3 false-positive class)
- [ ] **2.2.d [OPUS]** Replace top 5 over-mocked tests with behavioral equivalents
- [ ] **2.2.e [SONNET]** Add `check_mock_discipline()` to ms-enforce (warn if test has >3 mocks)
- [ ] **2.2.f [SONNET]** Add Core Rule 4.12 (Mocking Discipline)

### Step 2.3 — Structured Logging + Correlation IDs [OPUS architecture + SONNET wiring]
- [ ] **2.3.a [OPUS]** Decide log schema: which fields, JSON vs key-value, log levels per subsystem
- [ ] **2.3.b [SONNET]** `pip install structlog`; configure in `backend/core/logging.py`
- [ ] **2.3.c [OPUS]** Define correlation ID flow: request → wizard step → infra provider → DB op
- [ ] **2.3.d [SONNET]** FastAPI middleware to inject `X-Request-ID`, propagate to context
- [ ] **2.3.e [SONNET]** Replace print() and logging.info() across backend/ with structured equivalents
- [ ] **2.3.f [SONNET]** Tests: `test_logging.py` verifies every operation logs structured event with correlation ID
- [ ] **2.3.g [SONNET]** Add `check_logging_discipline()` to ms-enforce
- [ ] **2.3.h [SONNET]** Add Core Rule 8.1 (Structured Logging)

### Step 2.4 — Rate Limiting [SONNET — well-documented pattern]
- [ ] **2.4.a [OPUS]** Decide rate limits per endpoint (install: 5/min, status: 60/min, etc.)
- [ ] **2.4.b [SONNET]** `pip install slowapi`; configure with limits from 2.4.a
- [ ] **2.4.c [SONNET]** Apply decorators to mutating endpoints in `backend/api/`
- [ ] **2.4.d [SONNET]** Tests: `test_rate_limiting.py` verifies 429 returned past limits
- [ ] **2.4.e [SONNET]** Add Core Rule 9.1 (Rate Limiting)

### Step 2.5 — Architecture Decision Records [OPUS — pure judgment work]
- [ ] **2.5.a [OPUS]** Create `docs/adr/` with template (Context/Decision/Consequences/Status)
- [ ] **2.5.b [OPUS]** Backfill ADR-0001 through ADR-0010 covering: SQLite choice, ms-test.py vs pytest, Vue 3 choice, infra slot abstraction, no-Kubernetes decision, manifest YAML format, plugin system rejection, FastAPI choice, single-tenant assumption, traefik as reverse proxy
- [ ] **2.5.c [OPUS]** Cross-reference ADRs from CORE_RULES.md where relevant
- [ ] **2.5.d [SONNET]** Add `check_adr_present_for_breaking_change()` (advisory) to ms-enforce
- [ ] **2.5.e [SONNET]** Add Core Rule 7.2 (Decisions Documented)

---

## TIER 3 — Operational Maturity (target: ~2 days)

### Step 3.1 — API Versioning [OPUS strategy + SONNET refactor]
- [ ] **3.1.a [OPUS]** Decide versioning scheme: URL path /api/v1/ vs header; deprecation policy
- [ ] **3.1.b [OPUS]** Plan migration path: keep /api/* as alias initially, deprecate in v5
- [ ] **3.1.c [SONNET]** Refactor all `APIRouter()` to `APIRouter(prefix="/api/v1")`
- [ ] **3.1.d [SONNET]** Add /api/* compatibility layer (redirects with deprecation header)
- [ ] **3.1.e [SONNET]** Update frontend `apiClient.js` to use /api/v1/
- [ ] **3.1.f [SONNET]** Tests: `test_api_versioning.py` verifies both old and new paths work
- [ ] **3.1.g [SONNET]** Add Core Rule 9.2 (API Versioning)

### Step 3.2 — Dead Code Detection [SONNET — mechanical]
- [ ] **3.2.a [SONNET]** `pip install vulture`; configure with whitelist for dynamic uses
- [ ] **3.2.b [OPUS]** Review vulture's first report; remove confirmed dead code
- [ ] **3.2.c [SONNET]** Add `check_dead_code()` to ms-enforce as warning (not block)
- [ ] **3.2.d [SONNET]** Add Core Rule 5.18 (No Dead Code)

---

## TIER 4 — Production Operations (target: ~4 days, optional for solo use)

### Step 4.1 — Metrics Endpoint (Prometheus format) [OPUS metrics design + SONNET wiring]
- [ ] **4.1.a [OPUS]** Decide which metrics to expose: install duration, health check duration, DB query time, errors by endpoint
- [ ] **4.1.b [SONNET]** `pip install prometheus-fastapi-instrumentator`
- [ ] **4.1.c [SONNET]** Add `/metrics` endpoint
- [ ] **4.1.d [SONNET]** Tests: verify /metrics returns valid Prometheus format
- [ ] **4.1.e [SONNET]** Document scrape config in `docs/observability.md`
- [ ] **4.1.f [SONNET]** Add Core Rule 8.2 (Metrics)

### Step 4.2 — Health Probes (K8s-style) [SONNET — well-documented pattern]
- [ ] **4.2.a [OPUS]** Decide semantics: /healthz (liveness), /readyz (readiness), /startupz (startup)
- [ ] **4.2.b [SONNET]** Implement three endpoints with distinct logic per 4.2.a
- [ ] **4.2.c [SONNET]** Tests: each probe behaves correctly during startup, ready, and degraded states
- [ ] **4.2.d [SONNET]** Add Core Rule 9.3 (Health Probes)

### Step 4.3 — Audit Logging (immutable trail) [OPUS schema + SONNET wiring]
- [ ] **4.3.a [OPUS]** Define audit event schema: actor, action, resource, before/after, timestamp
- [ ] **4.3.b [OPUS]** Decide what to audit: all POST/PUT/DELETE; what NOT to audit (GETs)
- [ ] **4.3.c [SONNET]** FastAPI middleware to record events in `audit_log` table
- [ ] **4.3.d [SONNET]** Migration to add `audit_log` table (depends on 1.1 complete)
- [ ] **4.3.e [SONNET]** /api/v1/audit endpoint to query audit log (admin only)
- [ ] **4.3.f [SONNET]** Tests: every mutating endpoint produces audit event
- [ ] **4.3.g [SONNET]** Add Core Rule 9.4 (Audit Trail)

---

## COMPLETION RULES

After completing each step:
1. Run `ms-enforce --fast` — must be clean
2. Run pytest — must be clean
3. `sudo ms-update --full` on server (where applicable)
4. Mark task ✓ DONE in this file with date + commit hash
5. Commit task list update separately from feature commits
6. Update STATUS section at top with next step

A step is only complete when ALL its sub-tasks are checked. Partial completion stays as in-progress.

If a step reveals it should be split or reordered, update this document with rationale.

---

## RECORD OF COMPLETIONS

**Step 1.1 — Database Migrations** — 2026-05-05 [pending commit to main]
- `ms-enforce --fast`: PASS (4 Tier 1 checks clean)
- `pytest tests/test_migrations.py`: 12 passed, 0 failed
- Files changed: `backend/core/migrations.py` (new), `backend/core/state.py` (init_db wired), `backend/core/schema.sql` (regenerated/header updated), `migrations/001_baseline.sql` (new), `migrations/002_normalize_apps_status_check.sql` (new), `migrations/003_sync_legacy_tunnel_slot.py` (new), `migrations/_legacy/` (old file moved), `migrations/README.md` (new), `tests/test_migrations.py` (new), `tools/ms-enforce.py` (new), `tools/regenerate-schema-sql.py` (new), `docs/CORE_RULES.md` (Rule 5.19/6.1 added)
- `sudo ms-update --full`: pending server deploy

---

*This plan is a living document. Update it when reality diverges from plan, and when new principles are identified that should be added.*
