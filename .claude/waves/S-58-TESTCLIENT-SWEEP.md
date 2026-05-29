# S-58-TESTCLIENT-SWEEP — Sweep the 441 TestClient failures from CVE-2026-48710 middleware fallout

## Goal
Apply the same TestClient `base_url="http://localhost"` fix S-57 made for 12
specific tests to the ~441 other test failures with the same root cause.
TrustedHostMiddleware (CVE-2026-48710 defense-in-depth added in S-46) rejects
TestClient's default `Host: testserver` header with HTTP 400; the fix is
either a shared conftest fixture or per-file TestClient base_url overrides.

## Context
- S-57-A's full-suite inventory found 441 test failures beyond S-57's 12-test
  scope, across ~16 test files: test_agent_api.py, test_agent_apply.py,
  test_agent_integrity.py, test_api_coverage.py, test_comprehensive_contracts.py,
  test_deploy_tooling.py, test_e2e_flows.py, test_executor.py,
  test_failure_paths.py, test_fsm_app_install.py, test_generated_behavioral.py,
  test_install_app_refactor.py, test_install_inner_refactor.py,
  test_integration.py, test_runtime_bugs.py, test_wizard_contracts.py.
- S-57 left them untouched per scope discipline. S-58 is the authorized sweep
  scope for those failures.
- Source: `.claude/run-archive/2026-05-28-batch3/observations/S-57-A-2-broad-testclient-failures.md`.

## Rules to follow
- Stream A (sequential first) must re-inventory and BUCKET BY ROOT CAUSE.
  Not all 441 may share the testserver/TrustedHostMiddleware cause — some may
  have unrelated failures. Only failures with that specific cause are in
  scope for Streams B and C.
- Prefer ONE shared conftest fixture over per-file fixes if all affected
  tests use a common TestClient pattern. Smaller diff = lower risk.
- Per-file fixes are acceptable when a shared fixture isn't appropriate.
- Stream B/C may NOT change product code (backend/). The CVE-2026-48710
  middleware behavior is correct; only test fixtures change.
- If a failure resists the `base_url="http://localhost"` fix (e.g., the test
  asserts the middleware's rejection behavior intentionally), that test is
  out of scope — leave alone and log to observations.
- The same 20-line product-code budget from S-57 applies to fix attempts that
  drift into product changes. Halt with blocker if exceeded.

## Authorized deletions
- None expected. If a stream determines a test is genuinely obsolete (e.g.,
  testing functionality that no longer exists), the deletion is queued to
  `.claude/run/proposed-deletions/` per default — not applied autonomously.

## Parallelization

**Models:** coordinator = **opus** (root-cause analysis matters), subagents = **sonnet**. Three streams: A sequential first, B + C parallel after.

| Stream | Order | Subagent type | Scope |
|---|---|---|---|
| A — bucket-by-cause inventory | sequential first | `general-purpose` in worktree | Full test suite, classify the 441 failures by root cause, identify shared fixture patterns; output `.claude/run/observations/S-58-A-inventory.md` |
| B — TestClient fixture sweep | parallel after A | `general-purpose` in worktree | Affected test files from A's inventory; preferably one conftest.py fixture fix, otherwise per-file |
| C — non-TestClient failures | parallel after A | `general-purpose` in worktree | Any failures A's inventory classifies as NOT TestClient/testserver; apply per-test fixes within the 20-line budget or halt + blocker |

## Deliverables

### Stream A — bucket-by-cause inventory
1. Run `python3 -m pytest tests/ -q --tb=no` (full suite).
2. From the failures, identify which are TestClient/testserver-related (look
   for `assert response.status_code` failing on 400, or explicit Host header
   issues in tb).
3. For each TestClient failure, identify how the TestClient is instantiated:
   - Shared conftest fixture? Note the fixture name + path.
   - Per-file fixture? Note the file + fixture name.
   - Per-test inline instantiation? Note the line.
4. For non-TestClient failures, capture `pytest --tb=short` first 30 lines
   and classify briefly.
5. Write `.claude/run/observations/S-58-A-inventory.md` with the structured
   classification. Return summary in agent final response so coordinator
   knows what to dispatch B/C with.

### Stream B — TestClient fixture sweep
For each TestClient/testserver failure cluster from A's inventory:
1. If shared conftest fixture exists: apply `base_url="http://localhost"` to
   the fixture's TestClient construction. One change, many tests fixed.
2. If per-file fixtures: apply the same change in each per-file fixture.
3. If per-test inline TestClient: change `TestClient(app)` to
   `TestClient(app, base_url="http://localhost")` per occurrence.
4. Run the affected test files to confirm they pass.
5. Commit per fixture-fix-pattern with message
   `fix(test): TestClient base_url for CVE-2026-48710 fallout — <pattern>`.

### Stream C — non-TestClient failures
For each non-TestClient failure cluster from A's inventory:
1. Read the failing test + product code it exercises.
2. Apply test-level fix if ≤20 lines and clearly correct.
3. If product change needed > 20 lines: halt + blocker per S-57 pattern.
4. Commit per fix.

## Verification
1. Stream A: `.claude/run/observations/S-58-A-inventory.md` exists with
   bucket-by-cause classification.
2. After B+C merge: `python3 -m pytest tests/ -q --tb=no` shows the
   441-failure count drops dramatically (target: 0 or only blocker-deferred).
3. `python3 ms-enforce` exits 0 (TIER_2 stays green).
4. Specific affected files all pass: spot-check 3 files from A's inventory.

## Out of scope
- The S-46 TrustedHostMiddleware itself (its CVE-2026-48710 behavior is correct).
- Adjacent test failures discovered during fix work that aren't in A's
  inventory — log as observation, do not fix.
- Refactoring TestClient usage patterns beyond the base_url fix.
- Migrating tests to a different HTTP-test framework.

## Robot mode (autonomous execution)

When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
doctrine v4. Stream A sequential before B and C dispatch. Coordinator merges
to `wave/S-58-testclient-sweep` not main.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-58-TESTCLIENT-SWEEP.md as orchestrator.`
