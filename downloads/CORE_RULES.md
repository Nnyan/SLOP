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

### 5.9 Mutation Testing Enforces Behavioral Test Quality
All critical modules (executor.py, state.py) must maintain a mutation kill rate ≥80%. High-priority modules (wizard.py, checker.py) must maintain ≥70%. Run: `ms-mutmut`. Surviving mutants are piped to `ms-audit --improve` automatically for AI-generated killing tests. A test that passes while the code is wrong is not a test.

### 5.10 API Fuzzing on Every Deploy Path
`ms-schemathesis` runs against the live server's OpenAPI spec. Zero 500 responses on adversarial inputs is required. Any 500 found by schemathesis is a Core Rule 3.7 violation. Findings automatically feed `ms-audit --improve`. Run: `ms-schemathesis --quick`.

### 5.11 Browser Tests Cover Every Named Vue View
Playwright tests in `tests/browser/` verify every Vue view renders in real Chromium without JS errors. Catch frontend-only bugs invisible to all backend tests. Run: `ms-test-all --browser`. Auto-skips when server is unreachable.

### 5.12 Session Regression Capture (Keploy)
Real API sessions are recorded via `ms-keploy record` and replayed as regression tests. Captures multi-step flows (wizard, install → status, health cycle) that are hard to synthesize. Run: `ms-test-all --keploy`. Exported to `tests/test_keploy_regression.py`.

### 5.13 LLM Test Generation Is Context-Aware
`ms-audit --improve` automatically incorporates:
- Mutation survivors from `data/mutmut_survivors.json` (< 24h old)
- Schemathesis failures from `data/schemathesis_report.json` (< 24h old)
- Explicit context via `--context <file>`
The LLM generates targeted killing tests for the specific mutations and failures found. This closes the loop: tool finds gap → LLM writes test → gap closed.

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
