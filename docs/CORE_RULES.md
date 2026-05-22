# Mediastack Core Development Rules

**Status:** Active — updated with lessons learned after every significant session  
**Authority:** All modifications to Mediastack (or any related project) MUST review and apply these rules before implementation. Exceptions require explicit notation and approval.  
**Update trigger:** After every session where a new class of bug is found, after significant refactoring, and before entering a new feature area.

> **"core rules"** → return this document as-is  
> **"review against core rules"** → audit current state against every rule below as a checklist

---

## How to Use This Document

**Verifiable rules** (Sections 1–5) can be checked against code or test output. Violations are bugs.  
**Guidelines** (Section 6) are directional — violations require judgment, not automatic action.  
**Lessons learned** (Section 7) maps each rule to the bug that motivated it.

A rule you cannot check is not a rule — it is guidance and belongs in Section 6.

---

## Section 1 — Architecture & Design

### 1.1 Unified, Full-Visibility System
The codebase, testing framework, and application are one unified system — not separate concerns. All components are visible to all other components. No hidden state, no private side-channels, no undocumented behavior. Every architectural decision is discoverable from the codebase itself.

### 1.2 Minimize Redundancy — Clear, Concise, Consistent
One way to do each thing. Shared logic lives in one function or module — never duplicated across call sites. When two code paths have identical bug histories, they must be consolidated (not "could be"). Multiple paths are acceptable only when they serve genuinely distinct use cases with different data models. Every exception is documented with the reason.

### 1.3 Unified Endpoints with Logical Registers
APIs expose one endpoint per operation. Multiple endpoints for the same operation must be consolidated or one deprecated. Shared logic is extracted to a single callable so bugs are fixed once. Deferred unifications are tracked in `docs/TODO_*.md` files.

### 1.4 Zero Gaps
No untested behavior, no undocumented invariant, no unchecked assumption. A gap is any behavior the system relies on that cannot be verified automatically. Gaps are tracked in `data/coverage_map.json` and surfaced in every `ms-check` run. Coverage is not closed until a behavioral test (not a static check) confirms correctness.

### 1.5 Fail Loud, Fail Fast
Every failure must be:
- **Observable**: correct HTTP status code for the type of failure (404 for not-found, 409 for conflict, 422 for validation, 503 for unavailable — never 500 for known failure conditions)
- **Contextual**: error message states what failed and why
- **Actionable**: error message states what the user should do next

Silent success on failure is prohibited. `result.add("deploy", "error", msg)` returning `ok=True` is a bug. Generic 500 on a known condition (resource not found, platform not ready) is a bug.

### 1.6 Idempotency by Design
Any operation that is semantically repeatable (GET, health cycle, install retry on healthy container) must be tested for idempotency. Repeated calls must not produce different state or duplicate records. Self-heal operations can only move state in one direction — a health check that demotes `ready→pending` must never promote `pending→ready`.

### 1.7 Resource Conflict Prevention
Any operation that allocates a shared resource (port number, app key, infra slot, compose fragment path) must validate availability before attempting the allocation. The availability guard must be tested with an explicit conflict scenario that proves the guard fires before any side effects occur.

---

## Section 2 — Testing Philosophy

### 2.1 Full E2E Testing
Every user-facing flow has at least one test running the full stack: HTTP request → business logic → DB write → DB read → response shape verification. TestClient + real SQLite + controlled mocks. E2E tests catch integration bugs that unit tests cannot: components that work individually but fail when connected.

### 2.2 Test Correctness, Not Presence
Tests execute real code and assert on real outcomes. "The function exists" is never sufficient. "The function does the right thing" is required.

❌ `assert "traefik" in source_file`  
✅ `assert saved_manifest["traefik"]["enabled"] is True`

### 2.3 Test Behavior, Not Structure
Assert on what code *does*, not what it *looks like*:
- DB state after a call — not return values alone
- Response body field values — not status codes alone
- Fragment content — not fragment existence
- Actual provider cfg keys — not that provider.deploy() was called

### 2.4 Proactive, Not Reactive
- Tests exist before bugs, not after
- After every bug found in production or testing, a new rule is added to `ms-coverage RULES` within the same commit that fixes the bug
- `ms-coverage` runs on every deploy and surfaces gaps immediately
- `ms-testgen` auto-generates tests for uncovered nodes
- `ms-audit --improve` generates tests for uncovered architectural rules
- The same bug must never be discovered manually twice

### 2.5 Regression Test Mandatory for Every Bug Fix
Before a fix is merged, a test that:
1. Fails on the pre-fix code
2. Passes after the fix

...must exist and must be in the same commit as the fix. This is not optional. There are no exceptions. A fix without a regression test is incomplete.

### 2.6 Test Fixtures Must Be Self-Contained
Each fixture creates its own isolated state, never depends on another fixture's side effects, and always cleans up — even on test failure. Specifically:
- `app_client` must never depend on `test_db` or any other conftest fixture
- Every fixture that calls `state_mod.configure(path)` must call `state_mod.configure(None)` in a `finally` block or fixture teardown
- Fixture isolation failures cause intermittent failures only visible in full suite runs — the hardest bugs to diagnose

### 2.7 Verify Against Implementation, Not Intention
Before writing a test, verify what the code actually does — not what it should do. Run the code path manually if needed. A test asserting `step_persist_settings → p.domain` when the step writes to a KV table gives false confidence. Tests written against the wrong behavior are worse than no tests.

---

## Section 3 — Coverage & Semantic Rules

### 3.1 Semantic Checks, Not Just Syntax
YAML valid ≠ YAML correct. Syntactic validity is the floor, not the ceiling. Every YAML manifest must be checked for: required fields, valid category enum value, `traefik:` block presence (if `web_port`), `health.checks` presence (if `web_port`), correct port value types. Python files must be checked for behavioral correctness, not only `ast.parse()` success.

### 3.2 All Blocks Validated
Presence of a block is not the same as the block being correct:
- `traefik:` exists ≠ `traefik.enabled = true` with correct subdomain
- `health:` exists ≠ `health.checks` is a non-empty list with valid check types
- `ports:` exists ≠ all values are integers

Every block is validated for internal consistency, not just existence.

### 3.3 Validate Content Contracts
- API responses match the shape Vue components expect to read
- Settings written via PUT appear unchanged in subsequent GET (round-trip verified)
- DB writes survive a read-back cycle with identical values
- Frontend field names match backend field names — verified in tests, not assumed

### 3.4 Validate Schema and Semantic Rules
Two levels, both required:
- **Schema validation**: does this value match its type and enum?
- **Semantic validation**: does this value make sense in context?

Example: `status='ready'` + `domain=None` passes schema check but violates the semantic invariant "ready implies domain set." Both levels must be tested.

### 3.5 No Pure Static Analysis
Static analysis (grepping source, checking strings) may supplement but never replace runtime verification. Every static check must have a behavioral companion that executes the code and verifies the outcome. Tracking: `test_kinds` in coverage nodes — a node covered only by `static` tests is a behavioral gap.

### 3.6 Confirm All Rule Matching — No Overly-Narrow Patterns
Every audit rule must be verified against at least one known instance in the actual codebase before being declared active. A rule with zero matches is either wrong or its target doesn't exist — both are bugs in the audit system.

Specific failure mode: `db.commit()` pattern missed `db._c.commit()`. One character difference, zero matches, the bug shipped. After writing any pattern-based rule, grep the actual codebase to confirm it catches what it claims to catch.

### 3.7 Zero-Data State Must Not Return 500
Every API endpoint must handle the fresh-install, zero-data, platform-not-configured state gracefully. 500 on a known failure condition (no platform row, no running apps, no pending fixes) is always a bug. Correct responses: 404 (resource not found), 503 (dependency unavailable), 200 with empty collection, or 409 (precondition not met). Tests must include the zero-data scenario.


### 3.9 Test Infrastructure Must Use the Same Path Sources as Production Code
Every path checked or read in a test must be derived from the same source that production code uses to write it. A test that checks a different location than where the code writes gives false confidence and is worse than no test.

**The specific failure:** `ms-test.py` Q3 checked `REPO / "data" / "compose"` for 62 consecutive runs while infra providers wrote fragments to `config.data_dir / "compose"`. The test always passed. The mismatch was only discovered when a real failure occurred on the server.

**The enforcement mechanism:**
- `COMPOSE_DIR`, `DB_PATH`, `DATA_DIR` constants in `ms-test.py` derived from `config.data_dir` — same source as production code
- Semgrep rule `test-hardcodes-data-path` blocks `REPO / "data" / ...` in tests
- `TestPathContractAlignment` in `test_comprehensive_contracts.py` verifies alignment

### 3.8 Security: Sanitize All User-Supplied Identifiers
Any string from user input used as a filename, DB key, URL path segment, subprocess argument, or shell command must be sanitized before use. Required sanitization:
- Filenames/keys: `re.sub(r'[^a-z0-9_]', '_', value.lower())[:64]`
- Size limits on all fetched external content (64 KB default for manifests)
- Tested with adversarial inputs: path traversal (`../../etc/passwd`), oversized input, SQL metacharacters, null bytes

---

## Section 4 — Architectural Rules as Code

### 4.1 Compliance Rules Must Be Codified
Every architectural constraint that has ever caused a bug lives in `ms-coverage RULES` as a machine-checkable entry with:
- `id`: slug identifier
- `label`: the invariant as a statement
- `rationale`: why it matters + which bug motivated it
- `risk`: critical | high | medium
- `test_fn`: the specific test function that proves the rule
- `test_file`: which file contains that test

A rule with no `test_fn` match in the test corpus = high/critical gap in the coverage report.

### 4.2 Architectural Knowledge Must Have a Machine-Checkable Rule
If a developer must "just know" something, it is not safe — it must be a rule. Tribal knowledge that has never caused a bug is still a candidate for codification if the consequence of violating it is critical.

### 4.3 Analyze Both Source Code and Behavioral Coverage
Source coverage (which functions are called) is necessary but not sufficient. Behavioral coverage (which outcomes are verified) is the actual goal. `ms-coverage` tracks both: node coverage by kind (route/table/provider/step/rule) and test kind (e2e/runtime/static). A node covered only by `static` tests is treated as a behavioral gap for gap-reporting purposes.

### 4.4 Transaction Atomicity
Multiple DB operations that must succeed or fail together must execute in a single `StateDB` context. This is the design rule — `no-bare-db-commit` (rule 4.1 entry) is the enforcement check for violations. Never write to two tables in separate `with StateDB()` blocks when those writes must be atomic.

### 4.5 Code Generators Must Be Tested
Any tool that generates code (ms-testgen, ms-coverage scanner) must have tests verifying:
- Output is syntactically valid (`ast.parse()` on generated Python)
- Output contains expected content for known inputs
- REPO path resolves correctly when the tool is invoked via symlink (`Path(__file__).resolve().parent`)
- Generated tests actually collect and run without errors

Silent failures in code generators (producing `generation_error` skips instead of real tests) are high-risk bugs.

### 4.11 Snapshot Discipline
Outputs that downstream tools or operators depend on visually or programmatically — CLI banners, machine-readable JSON, stable API response shapes — must be covered by `syrupy` snapshot tests in `tests/test_snapshots.py`. Snapshot tests assert the SHAPE of the output (sorted keys, structural invariants), not transient values like timestamps and IDs.

When the output legitimately changes:
1. Run `pytest tests/test_snapshots.py --snapshot-update` to regenerate.
2. Review the diff in `tests/__snapshots__/test_snapshots.ambr` (committed to git).
3. Commit the snapshot update **in the same commit** as the source change so reviewers see both halves of the contract together.

Snapshot mismatches are surfaced by `ms-enforce` Tier 2 (`check_snapshots`) — a warning, not a pre-commit block, because the developer may need to regenerate intentionally. Bypassing this check via `--no-verify` AND failing to regenerate is the failure mode that ships a silent regression to the frontend / LLM context / operator banner. See step 2.1; rule introduced 2026-05-08.

### 4.12 Mocking Discipline
Tests mock at the **system boundary** — not at the **project boundary**. System boundary is anything outside `backend/`: subprocess, network (`httpx`, `urllib`, `socket`), filesystem ops outside `tmp_path`, the docker SDK wrapper (`backend.core.docker_client.*` — wraps `docker-py`; the wrapper itself is the boundary), and /proc readers. Project boundary is anything defined in `backend/`: `write_fragment`, `_attempt_self_heal`, `install_app`, `StateDB`, etc.

Mocking project-internal helpers turns behavioural tests into mock-call-graph assertions: the test passes when a mock is invoked with expected args, while production behaviour can drift silently — the **Q3 false-positive class**. Use real fakes instead:

| Replace | With |
|---|---|
| `patch("backend.manifests.executor.write_fragment")` | a `tmp_path`-rooted compose dir + assert on the actual file content |
| `patch("backend.core.state.StateDB")` | `init_db(tmp_path / "state.db")` + real `StateDB()` (the 1.5.d autouse-reset pattern) |
| `patch("backend.core.config.config")` | a fixture-managed `Config(...)` with test paths |
| `patch("backend.manifests.executor.load_manifest")` | a real test manifest in a fixture-controlled catalog dir |

**Exception:** patching a project function is acceptable when (a) it performs system-boundary I/O the alternative real-fake doesn't cover (e.g. `backend.manifests.executor.docker_client.get_container` resolves through a project import path but hits the docker daemon — treat as boundary), OR (b) the test is specifically about a single helper's behaviour and patching adjacent helpers is the simplest way to isolate. Document the exception with a comment on the patch line.

Enforced by: `ms-enforce` Tier 2 `check_mock_discipline` — warns when a single test stacks > 3 `@patch("backend.X")` decorators. Warning, not block: 4+ internal mocks is sometimes legitimately the simplest way. Codified during step 2.2; ADR at `docs/adr/0002-mocking-policy.md` documents the full policy with worked examples. Rule introduced 2026-05-08.

### 4.13 Structured Logging Discipline
Backend code logs via `from backend.core.logging import get_logger` — not `import logging` directly. Every log event is structured: `log.info("event name", key=value, key=value)`, never `log.info(f"event name with {key}")`. Plain `print(...)` is forbidden in `backend/` (always wrong — bypasses every log processor).

Schema (always present): `timestamp`, `level`, `logger`, `event`, `correlation_id`, `subsystem` plus event-specific kwargs. Output format is JSON in production (`MEDIASTACK_LOG_FORMAT=json`), human-readable key-value in dev. Correlation IDs flow via Python `contextvars` (thread-and-asyncio safe; inherited by `asyncio.create_task`) so every line of work spawned from a single HTTP request, scheduler tick, or CLI invocation shares a `correlation_id`.

The HTTP entry point is `backend.api.middleware.CorrelationIdMiddleware` — reads incoming `X-Request-ID` (or generates a UUID), sets the contextvar, echoes the ID back as a response header. Non-HTTP entry points (scheduler tick, CLI script) call `set_correlation_id(...)` themselves at their root.

Exception clause: `backend/core/logging.py` itself uses stdlib `logging` to bridge — that's the single configured exception.

Enforced by: `ms-enforce` Tier 2 `check_logging_discipline` — AST-walks `backend/` and reports `print(`, `logging.X(`, and `logging.getLogger(` call-sites. Warning, not block, while step 2.3.e's sweep is in progress; flips to mandatory once the count reaches zero. Codified during step 2.3; strategy doc at `docs/cleanup/STEP_2_3_STRUCTURED_LOGGING_STRATEGY.md` has the schema, level guidance per subsystem, and correlation-flow diagrams. Rule introduced 2026-05-08.

### 4.14 Rate Limiting Discipline
All mutating endpoints (`POST` / `PUT` / `DELETE` / `PATCH`) in `backend/api/` carry a `@limiter.limit(...)` decorator from `backend.api.rate_limit`. Tier defaults:

  - **Heavy mutation** (install / remove / replace, wizard run, platform reset) — **5/minute**
  - **Heavy read** (LLM-triggering endpoints) — **10/minute**
  - **Light mutation** (settings / registry / storage / routing) — **30/minute**
  - **Default** (other GETs) — **60/minute**

Localhost (`127.0.0.1`, `::1`, `testclient`) is bypassed via `_key_func` returning None — Mediastack's CLI tools (`ms-update`, `ms-test`) and the in-process health scheduler hit the local API and shouldn't be throttled. The limit exists as a runaway-script safeguard (frontend retry loop, misconfigured client) — Traefik handles external attackers.

Storage is in-memory (single-process backend; no Redis needed). Resets on every restart, which is acceptable since the limit is a correctness safeguard rather than a persistent quota.

Enforcement is by review (no AST pattern distinguishes "right limit" from "wrong limit"). When a new mutating endpoint lands, reviewers cite this rule + the strategy doc's tier table. A future check could AST-walk for `@router.post`/`put`/`delete` decorators not paired with `@limiter.limit(...)`; deferred until needed.

Codified during step 2.4; strategy doc at `docs/cleanup/STEP_2_4_RATE_LIMITING_STRATEGY.md` has tier definitions, slowapi setup, and test patterns. Rule introduced 2026-05-08.

### 4.15 Architecture Decision Records
Architectural decisions that constrain code structure (library choice, threshold numbers, exception clauses, enforcement mechanisms) are documented as ADRs in `docs/adr/`. Each ADR follows the Context / Decision / Consequences / Status format defined in `docs/adr/template.md`:

- **Context** — what problem are we solving? What constraints apply? Cite specific evidence (past incidents, audit findings) so future readers understand the *why* without needing to ask.
- **Decision** — what we will do, in plain language. Specific enough that a reader can implement from this section alone. Include exception clauses and the enforcement mechanism.
- **Consequences** — positive / negative / neutral. What gets better, what gets worse, what stays the same that someone might assume changes.
- **Status** — Proposed / Accepted / Superseded / Deprecated. How this is enforced going forward; when to revisit.

ADRs are numbered sequentially and immutable once accepted — superseded ADRs stay in the directory for git-blame archaeology, with a "Supersedes:" link to the replacement. New code that needs an architectural decision lands the ADR in the same PR.

When an ADR codifies a Core Rule, the Core Rule entry links to the ADR. Strategy docs (`docs/cleanup/STEP_*_STRATEGY.md`) describe HOW to implement; ADRs describe WHY this approach was chosen. The two are complementary — one informs sequencing, the other informs durability.

Codified during step 2.5; convention documented in `CONTRIBUTING.md`. Rule introduced 2026-05-08.

### 4.16 Test Independence Discipline
Tests pass under arbitrary order. The CI workflow `.github/workflows/test-randomly.yml` runs an order-stable subset under three distinct random seeds (`1`, `2`, `${GITHUB_RUN_ID}`) on every push and PR — any new ordering bug in the listed files blocks merge.

The "order-stable subset" is the explicit list of files that have been audited and made ordering-clean. As tests join the subset (when their underlying always-fail or fixture-coverage bugs are fixed), they must stay clean. The CI workflow's file list IS the registry; updating it requires explicit review.

Common ordering-bug patterns and their fixes:

- **Module-level singleton mutation** — when a test imports a singleton (`from backend.core.config import config`) and a previous test set an env var that affected the singleton's first-load values, downstream tests see the polluted state. **Fix:** pre-import the singleton BEFORE setting the env var, so the global captures the un-patched env. Or use `Config.from_env()` locally without touching the global.
- **Frozen-dataclass mutation** — `backend.core.config.config` is `@dataclass(frozen=True)`. Setting attributes via `_cfg.attr = value` raises `FrozenInstanceError`. Use `object.__setattr__(_cfg, "attr", value)` and restore the original on teardown.
- **Module-scoped DB fixture mutation** — when one test writes a setting and another reads its default, switch to a per-function autouse fixture that resets the mutated keys (see `tests/test_llm_diagnose_refactor.py::_reset_module_state`).

Also: `pytest-randomly` and `pytest-timeout` are pinned in `requirements-dev.txt`. The 30-second per-test timeout surfaces hangs (e.g., `socket.create_connection` reaching out to a real port) — when triggered, replace the network call with a fixture-mocked equivalent.

The full backend test suite is also run under random order as a separate informational job (`continue-on-error: true`). Its purpose is tripwire — when its failure count *delta* changes between CI runs, a new ordering bug has surfaced somewhere outside the order-stable subset. Treat the diff, not the absolute count.

Codified during step 1.5; backlog file at `docs/TODO_2026_05_08_test_independence_backlog.md` (mostly resolved at the time of Rule 4.16 introduction). Rule introduced 2026-05-08.

### 4.17 No Dead Code

Functions, classes, and module-level variables that are never referenced are removed. Dead code lies — it suggests the system supports something it doesn't, makes refactors harder by hiding what's actually live, and hides production bugs (a parameter that nothing reads is also a parameter no caller is using correctly).

`vulture` runs in `ms-enforce` Tier 2 (`check_dead_code`, warning-only) and surfaces likely-dead items at ≥ 80% confidence. The whitelist (`pyproject.toml` `[tool.vulture]`) covers dynamic-dispatch patterns vulture cannot see — decorator-registered handlers (`@app.*`, `@router.*`, `@limiter.*`, `@register`, `@pytest.fixture`), pytest collection (`test_*` / `Test*`), ms-coverage check registry (`check_*`), and well-known signatures (FastAPI `full_path` SPA arg, dunder positional-only `exc_*`, Pydantic `__context`). Anything else surfacing at 80% confidence is real.

`vulture` is heuristic — false positives happen, especially with reflection-heavy frameworks. The check is therefore a warning, not a block: it tells the team "review this", and the disposition is one of:

1. **Remove** — confirmed dead. Pair the removal with a regression test asserting the removed surface stays gone (Core Rule 2.5).
2. **Whitelist** — false positive (dynamically dispatched). Add to `[tool.vulture].ignore_names` or extend `ignore_decorators`.
3. **Wire it up** — parameter or class that *should* be used but isn't yet. The dead-code finding documents an unfinished feature; close it by completing the wiring.

Generated test files (`tests/test_generated_*.py`) are excluded from the scan — they're written by `ms-testgen` and may temporarily contain unreferenced helpers during regeneration.

Codified during step 3.1. Rule introduced 2026-05-08.

### 4.18 API Versioning Discipline

The HTTP API is versioned by URL-path prefix: every application route lives at `/api/v1/<area>/<path>`. Breaking changes ship as a new major version (`/api/v2/`); additive changes (new fields, new optional query params) stay in the current version.

`backend/api/main.py` dual-mounts every router at both `/api/v1/<area>` (canonical) and `/api/<area>` (deprecated alias). The `_mount(module, name, tag)` helper owns the dual registration in one place. The legacy mount carries a `deprecated` tag so Swagger UI groups the two prefixes distinctly.

`DeprecationHeaderMiddleware` (in `backend/api/middleware.py`) adds a tripod of response headers to unversioned `/api/<area>/...` requests:

- `Deprecation: true` — RFC 8594 / draft-ietf-httpapi-deprecation-header
- `Link: </api/v1/<area>/<path>>; rel="successor-version"` — the migration target
- `Sunset: Mon, 01 Sep 2026 00:00:00 GMT` — soft removal target

Infrastructure routes (`/api/ping`, `/api/health`, `/api/coverage`) and non-API routes (`/`, `/assets/...`, the SPA fallback) are NOT versioned and carry no deprecation header — they're framework plumbing, not the application API.

The frontend's centralized client (`frontend/src/api/client.ts`) hits `/api/v1/...` exclusively. Raw `fetch('/api/...')` calls in individual `.vue` files continue to work via the dual-mount and migrate incrementally as those files are touched.

`tests/test_api_versioning.py` enforces:

- Every dual-mounted area has both prefixes in the OpenAPI schema (parametrized over the 9 router areas).
- Versioned and legacy responses are byte-identical for read-only GETs.
- Legacy responses carry the deprecation tripod; versioned responses don't.
- Legacy mount's OpenAPI tags include `deprecated` so Swagger UI groups them.

A breaking change to a v1 route (response shape, status codes, error format) means a new `/api/v2/` route — never a silent change to `/api/v1/`. The `DeprecationHeaderMiddleware` is also where the `/api/v1/` → `/api/v2/` deprecation will be wired when v2 lands.

Codified during step 3.2. Rule introduced 2026-05-08. See [ADR 0005](adr/0005-api-versioning.md) for the full versioning policy.

### 4.19 Metrics Discipline

The `/metrics` endpoint exposes Prometheus-format metrics for every FastAPI route via `prometheus-fastapi-instrumentator`, plus the Mediastack-specific custom metrics defined in `backend/core/metrics.py`. The endpoint sits OUTSIDE the `/api/v1/` versioning umbrella (it's operational infrastructure, not the application API) and follows its own change-management discipline.

Cardinality is bounded. Every label dimension on a metric must come from a finite, slowly-changing set:

- HTTP `handler` labels use route templates (`/api/v1/apps/{key}`), never literal URLs with IDs in them.
- `app_key` labels come from the catalog (~50 entries today, growing slowly).
- `error_class` labels are Python exception class names (bounded by the exception hierarchy).
- `verb` labels (in `mediastack_db_query_duration_seconds`) are SQL verbs from a fixed enum (`SELECT/INSERT/UPDATE/DELETE/DDL/OTHER`).

Adding a metric label that COULD explode (UUIDs, raw URLs, free-form strings, timestamps) without a written cardinality argument is a Rule 4.19 violation. Prometheus stores one time-series per unique label-set combination; a single high-cardinality label can push memory usage from MB into GB.

The custom metrics are defined at module import time in `backend/core/metrics.py` (no I/O, no side effects). They join the default `prometheus_client` registry, which is what the FastAPI instrumentator scrapes. New metrics added to that file appear in `/metrics` automatically — no separate registration step.

Metric name + label changes are breaking changes for downstream Prometheus queries / dashboards / alerts. They follow the same discipline as API version changes:

- Adding a new metric is additive (safe).
- Adding a new label dimension to an existing metric is a breaking change for series-based queries.
- Renaming a metric is a breaking change.
- Changing bucket boundaries on a histogram is a soft-breaking change (existing dashboards still work; percentile values shift).

`tests/test_metrics_endpoint.py` enforces the contract with parametrized `# HELP`-line presence checks for each named custom metric.

Codified during step 4.1. Rule introduced 2026-05-08. See [`docs/observability.md`](observability.md) for the full operator runbook.

### 4.20 Health Probes Discipline

Three Kubernetes-style probes — `/healthz` (liveness), `/readyz` (readiness), `/startupz` (startup) — sit OUTSIDE the `/api/v1/` versioning umbrella and follow distinct semantic contracts:

- **`/healthz`** answers "is the Python process alive?" It MUST NOT touch any dependency. A transient DB hiccup must not cause the pod to be killed by the orchestrator. Always returns `200 {"status": "ok", "ts": <epoch>}`. The defining property of liveness is dependency-free reachability — if `/healthz` ever blocks on a query or external call, that's a Rule 4.20 violation.

- **`/readyz`** answers "should the load balancer route traffic to me?" It checks `state.configure()` is set + a `SELECT 1` ping returns within 1s. Returns `200` when ready or `503` with a diagnostic `checks` map listing what failed. The endpoint MAY surface real failure information in the response body — operators (and the orchestrator's logging) need to see why the pod isn't ready.

- **`/startupz`** answers "have I finished my one-time initialization?" Returns `503` until `backend.api.probes.mark_startup_complete()` runs (called from `init_db()` after migrations apply). Once true, stays true for the life of the process. Used by Kubernetes startup probes to delay liveness checking until the cold-start window is past.

The three endpoints are registered with `include_in_schema=False` — they're operational, not part of the application API, and shouldn't pollute the OpenAPI / Swagger UI surface that the application API contract lives on. The `DeprecationHeaderMiddleware` (Rule 4.18) explicitly skips these paths because they're not subject to API versioning.

`tests/test_probes.py` enforces:

- `/healthz` returns 200 even when state is unconfigured — that's the dependency-free contract.
- `/readyz` returns 503 when state unconfigured, 200 when state ready, with `checks` map populated.
- `/startupz` flips on after `init_db()` runs, stays on for the process lifetime.
- None of the probe paths carry the deprecation tripod (Deprecation/Link/Sunset).
- None appear in `/openapi.json`.

Codified during step 4.2. Rule introduced 2026-05-08. See [`docs/observability.md`](observability.md) for the K8s probe configuration.

### 4.21 Audit Trail Discipline

Every mutating HTTP request (POST/PUT/DELETE/PATCH) writes one row to the `audit_log` table. Read-only requests (GET, HEAD, OPTIONS) DO NOT write to the audit log — that's by design (the table would balloon with no operational value). Operational-infrastructure paths (`/metrics`, `/healthz`, `/readyz`, `/startupz`) are explicitly blocklisted in `AuditLogMiddleware._AUDIT_PATH_BLOCKLIST` for the same reason.

Schema is append-only by convention. The backend NEVER issues `UPDATE` or `DELETE` against `audit_log`; entries are written once and queried thereafter. The enforcement is by inspection — adding a non-`SELECT`/`INSERT` statement against `audit_log` is a Rule 4.21 violation.

The recorded fields preserve enough non-repudiation signal without storing PII:

- `actor` is currently always `"local"` (single-tenant homelab). Schema reserves the column for future multi-user mode; no migration needed when that ships.
- `action` is `<METHOD> <route_template>` (e.g. `POST /api/v1/apps/{key}/install`). Bounded cardinality — route templates, never literal URLs with IDs in them. Same discipline as Rule 4.19.
- `resource_id` is the path-parameter values that identify the mutated resource. Concatenated with `/` if multiple. NULL when the request doesn't operate on a specific resource.
- `request_body_hash` is `sha256(body)` in hex. The full body is **NOT** stored — bodies often contain secrets (passkeys, tokens, API credentials), and the hash supports non-repudiation (verifying a saved body matches the recorded action) without the storage / PII risk.
- `response_status` is the HTTP code returned. Failed mutations (4xx, 5xx) are audited too — operators need to see attempted-but-failed mutations, not just successful ones.
- `correlation_id` matches the `X-Request-ID` response header set by `CorrelationIdMiddleware`. Cross-correlates audit rows with structured-log entries from the same request.

The middleware MUST NEVER break a request. On any audit-write failure (DB unavailable, transient I/O error), it logs at WARNING and lets the response flow through unchanged. Audit going dark is a critical operational signal that surfaces in `/metrics` (the auto-instrumentated request flow continues) AND in the structured logs (the WARNING line is searchable). It is NOT an availability event.

Reading the trail: `GET /api/v1/audit?since=<unix_ts>&actor=<a>&action=<route>&limit=<n>` returns rows reverse-chronologically (newest first). `limit` is capped at 1000 to keep the API responsive — paginate via `since=<oldest_ts_seen>` for deeper history.

`tests/test_audit_log.py` enforces:
- Migration 004 installs the table (the `SELECT` query on a fresh DB returns empty list, not 500).
- GET requests do NOT write rows; POST/PUT/DELETE/PATCH do.
- `action` uses route template, not literal URL.
- `request_body_hash` is sha256 hex (64 chars, hex alphabet).
- Query endpoint filters apply correctly + ordering is reverse-chronological.
- Audit endpoint dual-mounted per ADR 0005 + carries deprecation tripod on the legacy alias.
- `/metrics` scrapes do NOT write audit rows.

Codified during step 4.3. Rule introduced 2026-05-08. See [`docs/observability.md`](observability.md) and `migrations/004_audit_log.sql` for full schema rationale.

---

## Section 5 — Process & Tooling

### 5.1 Incorporate Best Practices and Tools as Needed
Tools and practices are adopted because they solve real, observed problems — not because they are traditional. New tools are added when they close a gap that existing tools cannot. Tools are consolidated when they overlap. Every tool in the toolchain has a documented purpose and is exercised on every deploy.

### 5.2 The ms-*** Toolchain Is the Enforcement Layer
The toolchain runs the rules — not humans:

| Tool | When | Enforces |
|---|---|---|
| `ms-coverage` | Every deploy | Node + rule coverage, gap surfacing |
| `ms-testgen` | After coverage gaps found | Behavioral test generation |
| `ms-audit` | Every deploy | Contract audit, AI gap generation |
| `ms-check` | Every deploy | Health + coverage summary |
| `ms-test-all` | On demand / CI | Full pipeline: coverage → FSM → pytest → integration → audit → sync |
| Pre-commit hook | Every commit | Contract tests + wizard contracts |

### 5.3 FSM Testing for All State Machines
Every component with states must have formal FSM tests proving:
- All states are reachable from the initial state
- Every valid transition is tested (happy path and failure path)
- All guards block invalid transitions with the correct error
- All invariants hold after every transition (DB + filesystem consistent)

Current FSMs: App Install (`test_fsm_app_install.py`), Platform (`test_fsm_platform.py`), Health Check (`test_fsm_health_check.py`). New state machines require an FSM test file before first merge.

### 5.4 FakeDockerClient for Docker-Dependent Tests
Tests never depend on a real Docker socket unless explicitly marked `@pytest.mark.docker`. `FakeContainer.set_health()` drives FSM transitions deterministically. The `fake_docker` fixture patches all four Docker call sites simultaneously (executor, runtime_state, started_at, in_startup_grace). The broader principle: any external dependency producing non-deterministic output (Docker state, network calls, current time, filesystem state) must have a controllable test double.

### 5.5 Catalog Compliance Is a Merge Gate
New catalog apps (`catalog/apps/*.yaml`) must pass `TestCatalogCompliance` before the YAML is committed. The gate checks: required fields present, category in `VALID_CATEGORIES`, `traefik:` block present if `web_port` exists, `health.checks` non-empty if `web_port` exists, all port values are integers. This is verified by running `python3 -m pytest tests/test_non_catalog_installs.py::TestCatalogCompliance` before committing new manifests.

### 5.6 TODOs Are First-Class Artifacts
Every deferred item has a file in `docs/TODO_*.md` containing:
- Problem statement (what gap exists)
- Proposed solution (specific implementation plan)
- Reason for deferral (why not now)
- Trigger condition (what event should prompt implementation)
- Files to update when implemented

A deferred item without a TODO file is a forgotten item.

### 5.7 Distinguish Verifiable Rules from Guidance
Rules (Sections 1–5) are checkable against code or test output. Violations are bugs. Guidance (Section 6) is directional — violations require judgment. Any rule that cannot be checked belongs in Section 6. This document is audited against this principle on every update.

### 5.8 Core Rules Update Process
Core Rules are reviewed and updated:
- After every session where a new class of bug is found
- After every significant refactoring that reveals a missing principle
- Before entering a new feature area
- The version history table (Section 8) is maintained with every change
- The rule that triggered the update is linked to the bug in Section 7


### 5.9 Mutation Kill Rate Thresholds
Critical modules must maintain minimum mutation kill rates, verified by `ms-mutmut`:
- `executor.py`, `state.py`: ≥ 80% kill rate (highest historical bug density)
- `wizard.py`, `checker.py`: ≥ 70% kill rate
- `compose.py`, `apps.py`: ≥ 60% kill rate

A test that passes while code is wrong is not a test — it is noise. Mutation score is the real behavioral coverage metric; line coverage is not. Surviving mutants are auto-fed to `ms-audit --improve` for AI-generated killing tests.

### 5.10 Schemathesis Zero-500 Guarantee
Every API endpoint must handle adversarial inputs without returning 500. `ms-schemathesis --quick` runs against `/openapi.json` on every standard deploy. Zero 500s is the pass condition. Failures auto-feed to `ms-audit --improve`. FastAPI auto-generates the spec — no manual spec maintenance needed.

### 5.11 Playwright Coverage of All Vue Views
Every named Vue view must have a Playwright smoke test in `tests/browser/`. At minimum: the view loads without JS console errors, the sidebar status indicator reflects actual DB state, and any API-dependent data section renders correctly. Browser tests auto-skip when the server is unreachable — they never block the unit test pipeline.

### 5.12 Keploy Session Capture for Key Flows
Real user sessions (wizard completion, app install, health cycle, platform reset) must be recorded via `ms-keploy record` and replayed via `ms-keploy replay` as regression tests. Sessions are stored in `data/keploy/` and exported to `tests/test_keploy_regression.py`. Replay failures indicate a regression in a flow that real users actually execute.

### 5.13 LLM AI Context Is Automatically Assembled
`ms-audit --improve` automatically ingests all available findings before calling the LLM:
1. Core Rules (`docs/CORE_RULES.md`) — architectural invariants the LLM must respect
2. mutmut survivors (`data/mutmut_survivors.json`) — if < 24h old
3. Schemathesis failures (`data/schemathesis_report.json`) — if < 24h old
4. Keploy replay failures (`data/keploy/session_*.json`) — if < 24h old

No manual `--context` flag required. Every LLM call gets the full picture automatically.


### 5.14 Static Analysis on Every Commit (Ruff + Bandit + Gitleaks + ESLint)
The pre-commit hook runs four fast (<15s total) analysis tools before every commit:
- **Ruff** — Python: undefined names, unreachable code, bugbear patterns (`F`, `B` prefix rules)
- **Bandit** — Python security: `subprocess(shell=True)`, `eval()`, `pickle.loads()` patterns
- **Gitleaks** — Secret detection: API keys, tokens, Cloudflare credentials in staged files
- **ESLint** — Vue 3 frontend: `no-unused-vars`, `vue/no-mutating-props`, `no-eval`

All four write findings to `data/{tool}_findings.json` for automatic LLM ingestion.

### 5.15 Semgrep Custom Architectural Rules at Commit Time
`.semgrep/rules/core-rules.yml` contains pattern-based rules that enforce Core Rules directly in code, before tests run:
- `bare-db-commit` → blocks `db._c.commit()` (Core Rule 4.4)
- `unsanitized-user-key-as-path` → blocks unsanitized key as filesystem path (Core Rule 3.8)
- `result-add-not-fail` → catches `result.add('error')` instead of `result.fail()` (Core Rule 1.5)

New architectural rules are added to `.semgrep/rules/` when a new class of bug is found. Each rule is verified against at least one known instance from the Lessons Learned table before activation (Core Rule 3.6).

### 5.16 Weekly CVE Scanning (Trivy + pip-audit)
`ms-trivy` scans `requirements.txt` (Python CVEs) and catalog Docker images weekly. `pip-audit` provides complementary PyPA advisory database coverage. Critical CVEs surface to `ms-audit --improve` for remediation guidance. Scan results cached in `data/trivy_findings.json`.

### 5.17 Property-Based Testing for Security-Critical Functions
`hypothesis` tests in `tests/test_fsm_app_install.py` (and other key files) prove security properties hold for ALL inputs, not just the ones the developer thought of:
- Key sanitization never produces path traversal for any 200-char string
- Port handling never raises for any integer value
- Manifest normalization produces valid output for any dict

New hypothesis tests are added alongside each sanitization or allocation function.

### 5.18 CodeQL Inter-Procedural Taint Analysis (GitHub Actions)
`.github/workflows/codeql.yml` runs weekly taint analysis. Catches path traversal that spans multiple function calls — invisible to Bandit and Semgrep (single-function analysis only). Free for public repos. Scheduled weekly (Sunday 4am) to avoid blocking fast CI.

### 5.19 Migration Discipline (Core Rule 6.1)

Every schema change to the live state DB is delivered as a numbered file
under `migrations/`. Direct edits to `backend/core/schema.sql` without a
corresponding migration are prohibited; `test_schema_sql_in_sync_with_migrations`
in `tests/test_migrations.py` enforces this in CI.

Migration files are immutable after merge. The SHA256 checksum recorded in
`schema_migrations` at apply time is verified on every subsequent startup;
a checksum mismatch is a startup failure (Core Rule 1.5 — Fail Loud, Fail Fast).

Schema changes that are not safely backward-compatible — column drops,
CHECK constraint tightenings, NOT NULL additions on populated columns — require
an explicit two-migration sequence: one migration to widen the schema, one to
migrate the data, plus operator confirmation that the first has propagated to
all deployments before the cleanup migration is committed.

`ms-enforce --rule migration-sequence` and `ms-enforce --rule schema-sql-sync`
are the machine-checkable enforcement points. Run `ms-enforce --fast` before
every commit.

(ms-coverage rule slug: `migration-discipline` — risk: critical — test
function: `test_schema_sql_in_sync_with_migrations` in `tests/test_migrations.py`.)

### 5.20 Type Discipline (mypy strict on backend/)

All `backend/` modules pass `mypy --strict` against the project `mypy.ini`
(Pydantic plugin enabled, third-party stubs declared explicitly). Strict
mode enforces parameterized generics, no untyped defs, no implicit Optional,
and unused-ignore detection.

The check runs in `ms-enforce` Tier 1 on every commit (see `check_mypy()`
added in step 1.2.g, commit `b94e9fe`). A regression test
`tests/test_mypy_clean.py::test_mypy_strict_clean` (1.2.h, commit `8784cc1`)
confirms the strict pass on every test run, with a paired
`test_mypy_catches_real_error` negative test (Core Rule 2.2) that verifies
mypy actually catches deliberate errors so a misconfigured `mypy.ini` can
never silently pass.

New `# type: ignore` comments require an explicit error code (`[code]`)
and a comment stating the underlying constraint. Accepted ignores are
bounded:

- Third-party libraries without stubs (`docker.*`, `chromadb.*`) are
  globally allowed via per-module `ignore_missing_imports = True` in
  `mypy.ini`.
- Verified-runtime-checked union narrowings: `sqlite3.lastrowid` (always
  populated post-INSERT), `importlib loader` (always set after
  `find_spec`); these use `# type: ignore[union-attr]` with an explicit
  comment stating the runtime invariant.
- Localized `# type: ignore[arg-type]` for casts at the boundary of
  third-party dicts mypy can't narrow (e.g., `RECOMMENDED_MODELS` in
  `backend/core/gguf_validator.py:351` whose values are mixed str/float).

The four backfill steps that brought `backend/` to mypy-strict-clean:
- 1.2.c (commit chain `ea64a39`...`47c1ecb`): `backend/core/`
- 1.2.d (`8abddbd`...`d9fb920`): `backend/infra/` + `backend/manifests/`
- 1.2.e (`8e50bdc`...`0455c51`): `backend/health/` + `backend/platform/`
- 1.2.f (`338cd3f`...`7a1ee1d`): `backend/api/`

Cumulatively, mypy strict surfaced ~50 real bugs across these scopes
(see Section 7 for the catalog). All shipped to main; none caught by
unit tests, integration tests, or production smoke until mypy was wired.

(ms-coverage rule slug: `type-discipline` — risk: high — test function:
`test_mypy_strict_clean` in `tests/test_mypy_clean.py`.)

### 5.21 Commit Discipline (Core Rule 7.1)

All commits to `main` from `4e4c9cb` (step 1.3.c) forward follow Conventional
Commits 1.0 with the project-specific type taxonomy and scope conventions
defined in `docs/cleanup/STEP_1_3_COMMIT_DISCIPLINE_STRATEGY.md`. The
commit-msg hook (`tools/commit_msg_hook.py`, symlinked to
`.git/hooks/commit-msg` by `ms-setup-tools`) rejects non-conforming subjects
at commit time.

Required types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`.
Scopes are optional and use module names or workflow categories. Subject ≤
100 characters, no trailing period. Breaking changes use the CC 1.0 `!`
suffix or `BREAKING CHANGE:` footer.

`tests/test_commit_format.py::test_commit_subjects_post_cutoff_match_convention`
validates the entire post-cutoff range (`4e4c9cb~1..HEAD` inclusive) on
every test run, catching any commits that bypassed the hook (e.g.
`--no-verify`, manual rebase). The hook + test pair gives two layers of
defense; `ms-changelog --check` adds a third (CI-runnable parse check).

`CHANGELOG.md` is auto-generated by `ms-changelog --init` from the
post-cutoff commit log. Pre-cutoff commits are documented as a single
"Pre-policy" section (no categorization, no rewriting). Manual edits are
restricted to release-notes prose and the "Unreleased" section header.

(ms-coverage rule slug: `commit-discipline` — risk: medium — test function:
`test_commit_subjects_post_cutoff_match_convention` in
`tests/test_commit_format.py`.)

### 5.22 Complexity Discipline (Core Rule 8.1)

All `backend/` modules pass `ruff check --select C901` against the configured
mccabe threshold. The configuration lives in `ruff.toml`:
`[lint.mccabe] max-complexity = 15` (Phase 1 transitional from ruff's
default of 10); intent is to drop to 12 once the post-1.4 refactor backlog
is below 5 violations.

`ruff.toml [lint.per-file-ignores]` carries the bounded C901 exemption
list, partitioned in two categories per strategy §2.2:
- **Intrinsic** (permanent — surface-area complexity): FastAPI route
  handlers (`api/platform.py`, `api/health.py`, `api/apps.py`,
  `api/models.py`), the LLM-prompt template (`health/context_assembler.py`),
  and one-shot CLI entry points (`scripts/update_recommendations.py`).
- **Transitional** (revisit on backlog trigger): files whose currently-over-
  threshold functions are slated for refactor or backlogged in
  `docs/TODO_2026_05_07_complexity_backlog.md`.

`tests/test_complexity_thresholds.py::test_no_new_c901_violations` validates
the threshold on every test run, catching new code that bypasses the
pre-commit ruff check (`--no-verify`, manual rebase, etc.). The pre-commit
gate is the existing `ms-enforce` Tier 1 `check_ruff()` call (1.4.e
extended its `--select` to include C901).

Three-layer defense matches Core Rule 7.1's pattern: (1) ms-enforce Tier 1
ruff invocation, (2) pytest test, (3) operator-driven manual ruff or
test runs.

(ms-coverage rule slug: `complexity-discipline` — risk: medium — test
function: `test_no_new_c901_violations` in
`tests/test_complexity_thresholds.py`.)

---


### 5.23 Repository Structure Discipline

Canonical documents must live at one location only. Duplicate copies at
repo root or in unexpected directories cause confusion during audits and
searches; the stray copy silently diverges over time.

**Canonical paths enforced:**
- `CORE_RULES.md` → `docs/CORE_RULES.md` only
- `PROJECT_CLEANUP.md` → `docs/cleanup/PROJECT_CLEANUP.md` only
- ADR files (`NNNN-*.md`) → `docs/adr/NNNN-*.md` only (not loose in `docs/`)

**Gitignore data/ discipline:** Every tracked subdirectory under `data/`
must have an explicit `!data/<dir>/` exception in `.gitignore`. The pattern
`data/*/` already ignores all runtime data; exceptions make the tracked
content intentional and visible in the ignore file.

**Enforcement layers (three-layer pattern per Core Rule 7.1):**
1. `tests/test_repository_structure.py` — pytest checks at every test run
2. `ms-enforce` Tier 1 `check_repository_structure()` — runs at every commit
3. `tools/check_structural_antipatterns.py --staged` — pre-commit hook
   (added in Rule 5.24) catches violations at commit time

(ms-coverage rule slug: `repository-structure-discipline` — risk: medium —
test function: `TestGitignoreDataPattern`, `TestCanonicalDocumentPaths` in
`tests/test_repository_structure.py`.)

---


### 5.24 Structural Anti-Pattern Discipline

When a new structural drift pattern is identified during a release audit or
routine work, the response is to **encode it as a rule**, not to rely on
human memory.

**The rule registry** lives in `tools/check_structural_antipatterns.py`.
Each rule is a tuple of `(id, description, check_fn, remedy)`. Adding rule
N+1 requires: one check function, one RULES tuple entry, one test
(positive + negative cases), and one doc entry in `docs/STRUCTURAL_RULES.md`.
All four land in the same commit.

**Enforcement layers (three-layer pattern per Core Rule 7.1):**
1. `.git/hooks/pre-commit` runs `--staged` mode: hard-blocks on any finding
   (rules are specific enough that a staged violation is always real)
2. `ms-update` post-deploy block runs `--audit` mode: one-line result
   appears in the health banner; details on demand
3. Release-tag-gate checklist requires `--audit` clean as a pre-flight item
   (see `docs/RELEASE_PROCESS.md` section 3.2)

**Scope:** structural checks only — specific known-bad patterns with zero
noise. General "new file detected" warnings are explicitly not in scope
(false-positive-prone, disruptive to development).

(ms-coverage rule slug: `structural-antipattern-discipline` — risk: medium —
test function: `TestRunChecksAuditClean` in
`tests/test_structural_antipatterns.py`.)

---

### 5.25 Rule-Addition Contract Discipline

When a numeric Core Rule (`N.NN` format) is added, five companion changes must
land in the same commit:

- **C1** — `### N.NN Title` heading in `docs/CORE_RULES.md` and a matching RULES
  entry in `ms-coverage` with an identical title. No heading without an entry;
  no entry without a heading.
- **C2** — Section 8 version history row in `docs/CORE_RULES.md` dated today
  and referencing the rule id.
- **C3** — `data/coverage_map.json` node `rule:N.NN` regenerated via
  `python3 ms-coverage`.
- **C4** — `tests/__snapshots__/test_cli_snapshots.ambr` rule count and label
  updated via `python3 -m pytest tests/test_cli_snapshots.py --snapshot-update`.
- **C5** — `test_fn` and `test_file` fields in the RULES entry point to an
  existing test function (warning at commit time; hard failure at release-gate
  audit once the plan-then-implement window has closed).

**Enforcement layers:**
1. `.git/hooks/pre-commit` runs `ms-rule-contract --check` (C1–C4 hard-block,
   C5 warning).
2. CI `enforce.yml` runs `ms-rule-contract --audit` (5 invariants, every push
   to `main` and every PR).
3. `ms-enforce` Tier 1 `check_rule_contract()` runs `--audit` as part of the
   standard `ms-enforce --fast` gate.

**Design:** ADR 0012 (`docs/adr/0012-rule-addition-contract.md`).

(ms-coverage rule id: `5.25` — risk: high — test function:
`test_passes_with_all_companions` in `tests/test_rule_contract.py`.)

---

### 5.26 Installer Layout Discipline

The installer never hardcodes the literal strings `/opt/mediastack` or
`/var/lib/mediastack` in `installer/` source files, except in a single
canonical default-value location (added to `_INSTALLER_PATH_ALLOWLIST` in
`tools/check_structural_antipatterns.py` when it exists). All other code reads
paths from CLI arguments (`--install-dir`, `--data-dir`), env vars
(`MEDIASTACK_INSTALL_DIR`, `MEDIASTACK_DATA_DIR`), or the state file. Test
fixtures under `installer/tests/` are automatically excluded.

**Rationale:** hardcoded install paths in the wrong location defeat
`--install-dir` and `--data-dir` customization, break idempotency on
operator-customized hosts, and conflict with the uninstaller's
path-reading strategy. The invariant is INV-1 in ADR 0013.

**Enforcement layers:**
1. `.git/hooks/pre-commit` runs `tools/check_structural_antipatterns.py
   --staged` (rule-005): hard-blocks any staged `installer/` file containing
   the literal path strings outside the allowlist.
2. Release-tag-gate checklist requires `tools/check_structural_antipatterns.py
   --audit` clean (V5_INSTALLER_PLAN.md Step 4.5.a findings 6 and 7).

**Allowlist:** `installer/tests/` is automatically excluded. If a single
canonical default-value module (`installer/config.py` or equivalent) is
added in Tier 2, add its relative path to `_INSTALLER_PATH_ALLOWLIST` in
`tools/check_structural_antipatterns.py`.

**Design:** ADR 0013 (`docs/adr/0013-installer-layout-contract.md`) §1
Configurability and Layout Invariants (INV-1).

(ms-coverage rule id: `5.26` — risk: high — test function:
`test_detects_hardcoded_opt_mediastack` in
`tests/test_structural_antipatterns.py`.)

---

### 5.27 Installer Two-Track Test Coverage

Every I/O helper in `installer/` that calls an external binary (via
`installer._run.run_required()`) must have **two test tracks**:

**Track 1 — Orchestration tests** (DI-Callable injection): the module's
public entry point (`ensure_user`, `ensure_docker`, `setup_backend`, etc.)
is called with keyword-only I/O arguments that replace the real subprocess
calls with lambda stubs or no-ops. These tests verify control flow: which
helpers are called, in what order, and what exceptions propagate.

**Track 2 — Boundary tests** (subprocess patched at `installer._run`):
each I/O helper is called directly with `installer._run.subprocess.run`
patched via `unittest.mock.patch` with `side_effect=FileNotFoundError(binary)`.
These tests verify that a missing binary surfaces as `MissingBinaryError`
(from `installer._run`) rather than propagating as a raw Python exception.

**Rationale:** minimal Ubuntu 24.04 cloud images and Docker base images
may omit binaries (systemctl, useradd, git, npm) that full desktop images
include. Without boundary tests, the missing-binary path is only reachable
by running on a stripped host — a failure mode that reaches production.
The boundary tests are the only unit-testable substitute for a real minimal
container. (CLASS_A_AUDIT_2026_05_15.md §6 C2/C3.)

**Patch target:** always `installer._run.subprocess.run`, never
`installer.<module>.subprocess.run`. After migration to `run_required()`,
individual modules no longer import `subprocess` directly; patching the
wrong location silently misses.

**Enforcement layers:**
1. `tools/check_structural_antipatterns.py --staged` (rule-006): hard-blocks
   any staged `installer/` source file (outside `installer/_run.py` and
   `installer/tests/`) that contains a bare `subprocess.run(` call. All
   subprocess calls must go through `run_required()`.
2. Code-review: every new I/O helper must be accompanied by a boundary test
   in the module's `TestXxxBoundaryProbe` class.

**Design:** `installer/_run.py::run_required()` is the single subprocess
wrapper. `MissingBinaryError`, `RunTimeoutError` are defined there.

(ms-coverage rule id: `5.27` — risk: high — test function:
`test_no_bare_subprocess_run_in_installer` in
`tests/test_structural_antipatterns.py`.)

---

## Section 6 — Guidelines (Directional, Not Verifiable)

These guide judgment but are not mechanically checkable. Violations require discussion, not automatic action.

**Design clarity over cleverness** — code that is obvious is preferable to code that is elegant but requires explanation. If a reviewer needs to ask why, the code needs a comment or a refactor.

**Error messages are user interfaces** — every error message is read by a person under stress. Plain language, specific cause, actionable next step. "Database error" is not a message. "App 'sonarr' is not installed — use POST /api/apps/sonarr/install to deploy it" is.

**Minimize surface area of change** — prefer changes that touch the fewest files. Broad refactors that touch 20 files are high-risk. Extract a shared function and change 2 files. The `_save_community_manifest()` consolidation is the model.

**Defer API-breaking changes** — the API surface is a contract. Breaking it requires frontend updates, deprecation, and versioning overhead. Extract shared logic first (closes the gap immediately). Add unified endpoints as v2 candidates with a TODO.

**Test names document intent** — test function names are the executable specification. `test_vpn_secrets_passed_to_gluetun_provider` tells a reader exactly what the system guarantees. `test_install_3` tells nothing.

---

## Section 7 — Lessons Learned

Every rule maps to the bug that motivated it. New bugs add rows. No row is ever deleted.

| Bug | Rule Motivated | Commit |
|---|---|---|
| `db.commit()` → AttributeError → 500 on maintenance window | 4.1 `no-bare-db-commit`, 1.5 Fail Loud | fe4ecc3 |
| `result.add()` doesn't set `ok=False` → compose failure silent | 1.5 Fail Loud, 4.1 `compose-failure-sets-result-failed` | ce4b2df |
| 4 providers: `result.stderr` on `(rc, str)` tuple → NameError | 2.1 E2E, 4.1 `provider-failure-returns-result` | 15c288e |
| VPN secrets never passed to Gluetun cfg | 2.3 Test Behavior, 4.1 `install-custom-complete-manifest` | a364ba2 |
| `pending_fixes` not in schema.sql → `approve_fix` always 500 | 3.7 Zero-Data, 4.1 `pending-fixes-in-schema` | ce4b2df |
| else-block set `status=failed` on all non-Ollama successes | 2.3 Test Behavior, 4.1 `no-stuck-installing-status` | ce4b2df |
| `ms-audit` checked `db.commit()` but bug was `db._c.commit()` | 3.6 Overly-Narrow Patterns | 508da84 |
| localai had raw Traefik labels, not `traefik:` block | 3.2 All Blocks Validated, 4.1 `catalog-web-port-requires-traefik` | c28e4ec |
| seerr/sabnzbd had `web_port` but no `health.checks` | 3.1 Semantic Checks, 4.1 `catalog-web-port-requires-health` | c28e4ec |
| `key='../../etc/passwd'` used as filename directly | 3.8 Security Sanitization, 4.1 `install-github-key-sanitization` | c28e4ec |
| No YAML size limit → OOM risk on large manifests | 3.8 Security Sanitization, 4.1 `install-github-size-limit` | c28e4ec |
| `install_instance` never checked `host_port_override` conflicts | 1.7 Resource Conflict, 4.1 `install-instance-port-conflict` | c28e4ec |
| `app_client(test_db)` → intermittent 500 on full suite run | 2.6 Fixture Isolation | c0cff15 |
| `step_persist_settings` test asserted `p.domain` (wrong field) | 2.7 Verify Against Implementation | ce4b2df |
| `ms-testgen` generated `label_esc` undefined → 145 skips | 4.5 Code Generators Must Be Tested | 508da84 |
| `ms-coverage` REPO = symlink location, not repo root | 4.5 Code Generators Must Be Tested | 3e8c97e |
| `GET /api/apps/system/profile` → 500 on fresh install | 3.7 Zero-Data State Must Not 500 | 7bcab94 |
| Two install paths → same compliance bug in two places | 1.2 Minimize Redundancy, 1.3 Unified Endpoints | c28e4ec |
| Static coverage (manifest present) ≠ behavioral coverage | 3.5 No Pure Static, 4.3 Behavioral Coverage | 3e8c97e |
| `init_db()` ran `CREATE TABLE IF NOT EXISTS` on every startup — schema changes to CHECK constraints, column additions, column drops silently no-op on live DBs. Three bugs shipped without applying. | 5.19 Migration Discipline (Core Rule 6.1), 1.6 Idempotency, 1.5 Fail Loud | 68199f1 |
| `tunnel_providers` vs `infra_tunnel_providers` drift — inline migration in `init_db()` ran every startup, no version tracking, no audit trail | 5.19 Migration Discipline | 68199f1 |
| `bare-db-commit` Semgrep rule matched `self._c.commit()` inside `StateDB` itself (the implementation), inflating violations from 26 to 45. Rule was too broad in the opposite direction of the original `db.commit()` miss. | 3.6 Confirm All Rule Matching — No Overly-Narrow Patterns, 4.1 Compliance Rules Must Be Codified | a62e34c |
| `generated-code-no-ast-verify` Semgrep rule fired on `ms-testgen:581` even though `ast.parse(content)` was called immediately above. The original `pattern-not` used sequential `...` matching, which only bridges siblings in the same lexical block — ms-testgen wraps the verification in `try: … except SyntaxError`, putting ast.parse inside the try-suite. Fix uses `pattern-not-inside` (scope-based matching) to require ast.parse appear anywhere in the enclosing function. Same failure class as the bare-db-commit row — overly-narrow pattern. | 3.6 Confirm All Rule Matching — No Overly-Narrow Patterns | 966b2fd |
| `log` referenced but never imported in 4 provider files (latent NameError on the actual log call when an error path was hit) | 5.20 Type Discipline | 8abddbd, aed1068 (1.2.d) |
| `IMAGE` / `CONTAINER_NAME` undefined in management/auth/tunnel providers — NameError silently swallowed by `except Exception: pass`, so `upsert_app` was never actually called (silent data-integrity bug; only mypy surfaced it) | 5.20 Type Discipline | b404a11, bafb6c6, 5242874 (1.2.d) |
| `_register_app_hostname` called missing required `platform` arg (TypeError at runtime; broad except masked it in production) | 5.20 Type Discipline | 77ab4fe (1.2.c) |
| Lowercase `any` used as type annotation in `apps.py`, `settings.py` — collides with `builtins.any` and cascades 12+ `[attr-defined]` errors per site | 5.20 Type Discipline | 338cd3f, b8861a5 (1.2.f) |
| `cloud_llm.cascade_completion` / `wizard.reset_platform` / `ExecutionResult.message` referenced but absent (renames/removals not propagated; broad except masked the ImportError/AttributeError so cloud LLM cascade was permanently dead, wizard reset path was a no-op, and Ollama install errors lost their original message) | 5.20 Type Discipline | a3919d6, 3d650e8, 1639788 (1.2.f) |
| `Connection \| None.commit()` and `App \| None.id` unguarded — would AttributeError on the None branch | 5.20 Type Discipline | ea64a39, 494cadf, e7afef9, 3367aa5 (1.2.c, 1.2.d, 1.2.f) |
| `files` undefined in `models.get_registry()` — `for f in files` NameError'd every `GET /api/registry` call (500 in production, silently shipping for who knows how long) | 5.20 Type Discipline | fe20989 (1.2.f) |

---

## Section 8 — Version History

| Date | Change |
|---|---|
| 2026-05-04 | v1.0 — initial codification from Mediastack v4 lessons learned |
| 2026-05-04 | v1.1 — added rules 1.5–1.7, 2.5–2.7, 3.7–3.8, 4.4–4.5, 5.5–5.8; separated guidelines; added lessons learned table; strengthened 2.4 and 3.6 |
| 2026-05-04 | v1.2 — added rules 5.9–5.13 (Tier 1+2 tools: mutmut, Schemathesis, Playwright, Keploy, LLM context assembly) |
| 2026-05-04 | v1.3 — added rules 5.14–5.18 (Tier 1-3 tools: Ruff, Bandit, Gitleaks, ESLint, Semgrep, Trivy, Hypothesis, CodeQL, mutate schedule) |
| 2026-05-04 | v1.2 — added rules 5.9–5.13: Playwright, mutmut, Schemathesis, Keploy, LLM context-awareness. 30 architectural rules. |
| 2026-05-04 | Added to Lessons Learned: _extra_context NameError in ms-audit (LLM never received Core Rules), Playwright/mutmut/Schemathesis/Keploy not wired to audit pipeline |
| 2026-05-04 | v1.4 — added rule 3.9 (test path alignment); fixed ms-test Q3 path mismatch (62 false passes) |
| 2026-05-05 | v1.5 — added rule 5.19 / Core Rule 6.1 (Migration Discipline); wired ms-enforce Tier 1 checks; two Lessons Learned rows for init_db schema drift |
| 2026-05-05 | v1.6 — fixed `bare-db-commit` rule false positives (added `pattern-not: self._c.commit()`); 26 real 4.4 violations remain (tracked as cleanup step 1.1.5) |
| 2026-05-05 | v1.7 — fixed `generated-code-no-ast-verify` false positive (added `pattern-not-inside` for ast.parse anywhere in enclosing function); ms-testgen verification was already correct, original sequential `pattern-not` couldn't bridge across try/except (Rule 3.6) |
| 2026-05-07 | v1.8 — added Rule 5.20 (Type Discipline / mypy strict on backend/) per step 1.2.i; 7 Lessons Learned rows from 1.2.c-1.2.f bug fixes; wired ms-enforce Tier 1 (1.2.g `check_mypy()`) and pytest (1.2.h `test_mypy_clean.py`) layers |
| 2026-05-07 | v1.9 — added Rule 5.21 / Core Rule 7.1 (Commit Discipline / Conventional Commits 1.0) per step 1.3.i; commit-msg hook (`tools/commit_msg_hook.py`) + `tests/test_commit_format.py` + `ms-changelog` tool + CHANGELOG.md; cutoff SHA `4e4c9cb` |
| 2026-05-08 | v1.10 — added Rule 5.22 / Core Rule 8.1 (Complexity Discipline / mccabe ≤ 15) per step 1.4.g; ruff.toml `[lint.mccabe]` + 15 per-file-ignores + `tests/test_complexity_thresholds.py` + check_ruff extended; 1.4.d refactor backlog deferred (5 functions ≥ 25) |
| 2026-05-08 | v1.11 — added Rule 4.11 (Snapshot Discipline) per step 2.1.g; syrupy 5.1.0 in requirements-dev.txt + `tests/test_snapshots.py` + `tests/__snapshots__/test_snapshots.ambr` + ms-enforce Tier 2 `check_snapshots`; 1.4.d closed (5 production refactors landed at d58b4dd…2b9c401); 1.5 partial (a–e landed at 3f589c2; f/g deferred); 2.1 partial (a–g landed; 3 of 5 strategy targets snapshotted, ms-update / ms-test / ms-enforce-json deferred to follow-up) |
| 2026-05-08 | v1.12 — added Rule 4.12 (Mocking Discipline) per step 2.2.f; ADR 0002 (`docs/adr/0002-mocking-policy.md`) formalises boundary-vs-internal; ms-enforce Tier 2 `check_mock_discipline` AST-walks tests and warns on > 3 internal `@patch("backend.*")` decorators per test; survey identifies 4 over-mocked tests as initial 2.2.d targets (deferred to focused session) |
| 2026-05-08 | v1.13 — added Rule 4.13 (Structured Logging Discipline) per step 2.3.h; structlog 25.5.0 + `backend/core/logging.py` (configure_logging + get_logger + correlation_id contextvar) + `backend/api/middleware.CorrelationIdMiddleware` + `tests/test_logging.py` (12 cases) + ms-enforce Tier 2 `check_logging_discipline` AST walker; strategy doc at `docs/cleanup/STEP_2_3_STRUCTURED_LOGGING_STRATEGY.md`; 2.3.e sweep of ~153 backend/ logging call-sites deferred to focused session (warning is informational until the count reaches zero) |
| 2026-05-08 | v1.14 — added Rule 4.14 (Rate Limiting Discipline) per step 2.4.e; slowapi 0.1.9 + `backend/api/rate_limit.py` (limiter + _key_func + localhost bypass via key_func returning None) + `backend/api/main.py` wiring + `@limiter.limit("5/minute")` on install/remove/replace + `@limiter.limit("10/minute")` on /health/run + `tests/test_rate_limiting.py` (6 cases); strategy doc at `docs/cleanup/STEP_2_4_RATE_LIMITING_STRATEGY.md`. Number is 4.14 not the planned 9.1 — same correction pattern as 1.4.g (5.17→5.22), 2.3.h (8.1→4.13) |
| 2026-05-08 | v1.15 — added Rule 4.15 (Architecture Decision Records) per step 2.5.d; `docs/adr/template.md` + retroactive ADR 0001 (database migrations, decided in 1.1.b) + ADR 0003 (structured logging, from 2.3) + ADR 0004 (rate limiting tiers, from 2.4); ADR 0002 (mocking policy) was already created in 2.2.b. CONTRIBUTING.md gets the ADR section. Number is 4.15 not the planned 5.18 — Section 4 stays the durable home for new rules until renumbering |
| 2026-05-08 | v1.16 — added Rule 4.16 (Test Independence Discipline) per step 1.5.g (closing 1.5 backlog); `.github/workflows/test-randomly.yml` split into two jobs: `order-stable-mandatory` (lists 14 audited files; runs under 3 distinct seeds) and `random-full-suite-informational` (`continue-on-error: true`; tripwire for new ordering bugs outside the subset); 11 broken tests in test_fsm_app_install.py + 3 in test_runtime_bugs.py + 2 in test_deploy_tooling.py fixed in commits dfef971 and 65b069d. Number is 4.16 not the planned 4.10 — same renumbering pattern as 1.4.g (5.17→5.22), 2.3.h (8.1→4.13), 2.4.e (9.1→4.14), 2.5.d (5.18→4.15) |
| 2026-05-08 | v1.17 — added Rule 4.17 (No Dead Code) per step 3.1.e (commit `5903259`); `vulture>=2.16` in `requirements-dev.txt` + `[tool.vulture]` whitelist in `pyproject.toml` covering FastAPI/router/limiter/pytest decorator dispatch + ms-enforce Tier 2 `check_dead_code` (warning-only at 80% confidence). 3-way disposition: remove + paired regression test, whitelist as false positive, or wire it up. Phase-2 sweep at `fceefd2` removed `COMPOSE_VERSION` + `ActionType` Literal alias; `tests/test_dead_code_removals.py` asserts they stay gone. |
| 2026-05-08 | v1.18 — added Rule 4.18 (API Versioning Discipline) per step 3.2.g (commit `399722f`); URL-path versioning (`/api/v1/<area>`) with `_mount()` helper in `backend/api/main.py` dual-registering each router at canonical + legacy `/api/<area>`; `DeprecationHeaderMiddleware` adds `Deprecation: true` / `Link: rel=successor-version` / `Sunset: 2026-09-01` to legacy responses; infrastructure routes (`/api/ping`, `/api/health`, `/api/coverage`) exempt; `tests/test_api_versioning.py` (19 tests) verifies dual-mount reachability, body parity, deprecation tripod, Swagger UI tag grouping. ADR 0005 documents the policy. |
| 2026-05-08 | v1.19 — added Rule 4.19 (Metrics Discipline) per step 4.1.f (commit `6d46788`); `prometheus-fastapi-instrumentator>=7.1` + `prometheus-client>=0.25` auto-instrument every FastAPI route with request count + duration histograms; 4 custom metrics in `backend/core/metrics.py` (`install_duration_seconds`, `health_check_duration_seconds`, `db_query_duration_seconds`, `errors_total`) all with bounded-cardinality labels (app_key from catalog, error_class from exception hierarchy, verb from SQL-verb enum); `/metrics` sits OUTSIDE `/api/v1/` (operational infrastructure, not API); `tests/test_metrics_endpoint.py` (11 contracts) pins endpoint reachability + content-type + exposition-format markers + custom-metric definitions + counter increments. |
| 2026-05-08 | v1.20 — added Rule 4.20 (Health Probes Discipline) per step 4.2.d (commit `78297ca`); three K8s-style probes in `backend/api/probes.py` with distinct semantics — `/healthz` = liveness (dependency-free, always 200), `/readyz` = readiness (`state.configure()` + 1s `SELECT 1` ping; 503 with diagnostic checks map when not ready), `/startupz` = startup (503 until `mark_startup_complete()` runs from `init_db()` after migrations apply, then 200 for process lifetime); all three `include_in_schema=False` and exempt from `DeprecationHeaderMiddleware`; `tests/test_probes.py` (8 contracts) enforces the dependency-free invariant + the readiness checks-map + the startup state machine + deprecation-header exemption + OpenAPI exclusion. |
| 2026-05-08 | v1.21 — added Rule 4.21 (Audit Trail Discipline) per step 4.3.g (commit `59c2e34`, fixup `bcd5c45`); `migrations/004_audit_log.sql` adds `audit_log` table (`id, ts, actor, action, resource_id, request_body_hash, response_status, correlation_id`) — bodies sha256-hashed, never stored (PII safety); `AuditLogMiddleware` records POST/PUT/DELETE/PATCH only (GET/HEAD/OPTIONS skipped by design); operational-infrastructure paths (`/metrics`, `/healthz`, `/readyz`, `/startupz`) blocklisted; on audit-write failure middleware logs at WARNING and lets request through (auditing must never break a request); `GET /api/v1/audit` query endpoint with filter combinations + reverse-chronological ordering + 1000-row cap; `tests/test_audit_log.py` (10 contracts) verifies table existence + GET-skip + POST-write + route-template format + sha256 body hash + filter combinations + ordering + dual-mount + /metrics-not-audited. |
| 2026-05-15 | v1.29 — added Rule 5.27 (Installer Two-Track Test Coverage) per CLASS_A_AUDIT_2026_05_15.md §6 C2/C3; enforced by `tools/check_structural_antipatterns.py` rule-006 (`_check_bare_subprocess_run_in_installer`): hard-blocks bare `subprocess.run(` in `installer/` outside `_run.py` and `tests/`; `tests/test_structural_antipatterns.py` gains `TestRule006InstallerBareSubprocess` boundary tests. |
| 2026-05-13 | v1.28 — added Rule 5.26 (Installer Layout Discipline) per v5.0 Step 1.2.b; `tools/check_structural_antipatterns.py` rule-005 (`_check_installer_hardcoded_paths`): staged and audit modes grep `installer/` (excluding `installer/tests/`) for literal `/opt/mediastack` and `/var/lib/mediastack` strings; ADR 0013 INV-1. `tests/test_structural_antipatterns.py` gains `TestRule005InstallerHardcodedPaths` (5 tests: detects opt path, detects var path, ignores test fixtures, clean when no hardcoded paths, clean when no installer dir). |
| 2026-05-12 | v1.27 — retroactive companion bookkeeping for Rules 5.23 and 5.24 per F3 audit finding: RULES list entries added to `ms-coverage` (coverage now 75/75); contract check C1–C5 satisfied for both rules. |
| 2026-05-11 | v1.25 — added Rule 5.25 (Rule-Addition Contract Discipline) per step 2.4.d; `ms-rule-contract` enforces C1–C5 companion checks at commit time (`--check`) and CI/release-gate audit (`--audit`, 5 invariants); `tests/test_rule_contract.py` (14 tests) |
| 2026-05-10 | v1.24 — added Rule 5.24 (Structural Anti-Pattern Discipline) per step 1.4.g; `tools/check_structural_antipatterns.py` (3 rules, --staged + --audit modes) + pre-commit hook + `tests/test_structural_antipatterns.py` (9 tests) + `docs/STRUCTURAL_RULES.md` + ms-update audit banner |
| 2026-05-10 | v1.23 — added Rule 5.23 (Repository Structure Discipline) per step 1.3.d; `tests/test_repository_structure.py` (4 tests) + ms-enforce Tier 1 `check_repository_structure()` |
| 2026-05-09 | v1.22 — bookkeeping closure: 5 rule entries (4.17–4.21) added to `ms-coverage` RULES list (closing audit Finding 1; coverage now 72/72 = 100% with all new rules counted); duplicate `rule:schemathesis-zero-500s` deduplicated. No rule semantics changed. |
