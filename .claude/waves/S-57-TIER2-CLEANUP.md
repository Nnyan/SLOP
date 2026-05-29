# S-57-TIER2-CLEANUP — Fix pre-existing TIER_2 test failures

## Goal
Clear the 9 FSM + 3 snapshot test failures that have been carried on main as
"pre-existing, unrelated to wave work." They predate Round 1; both Round 1
and Round 2 orchestrators correctly left them alone per scope-discipline
doctrine. Time to fix them deliberately.

## Context
- The "fix all pre-existing failures" rule was tried and walked back twice
  (memory: feedback-no-fix-all-failures-rule). That doctrine still holds —
  Robot mode does NOT fix pre-existing failures inside a wave doing other
  work.
- This wave's ONLY purpose is to fix those specific failures. It IS the
  authorized fix-all-failures scope.
- Failures identified by Round 2 orchestrator status: 9 FSM tests + 3
  snapshot tests. Stream A first determines which specific tests + root
  causes by running the suite. Stream B fixes FSM tests, Stream C fixes
  snapshot tests.

## Rules to follow
- Do NOT scope-creep into adjacent test failures. If a fix surfaces a new
  unrelated failure, write an observation and skip.
- For snapshot updates: use `pytest --snapshot-update` and commit the
  regenerated snapshots; investigate WHY they drifted before just
  regenerating.
- If a fix would require non-trivial product changes (>20 lines outside
  tests/), halt that test and write a blocker. The wave is for
  test-level fixes only, not product refactoring.

## Authorized deletions
- None expected. If a stream determines a test is genuinely obsolete (e.g.,
  testing removed functionality), the deletion goes in this section in a
  follow-up commit, NOT as a free-form deletion.

## Parallelization

**Models:** coordinator = **opus** (judgment-heavy on root causes), subagents = **sonnet**. Three streams: A is sequential-first, B and C run in parallel after A delivers the inventory.

| Stream | Order | Subagent type | Scope |
|---|---|---|---|
| A — failure inventory | sequential first | `general-purpose` in worktree | Run full test suite, identify the 12 failing tests by name, group by type (FSM vs snapshot), capture failure output, produce `.claude/run/observations/S-57-A-inventory.md` |
| B — FSM fixes | parallel after A | `general-purpose` in worktree | 9 FSM test files (paths from Stream A's inventory), corresponding product code if needed (≤20 lines) |
| C — snapshot fixes | parallel after A | `general-purpose` in worktree | 3 snapshot test files (paths from Stream A's inventory), regenerated snapshot files |

## Deliverables

### Stream A — failure inventory
1. Run `python3 -m pytest tests/ -q --tb=no` (no -k filter; full suite).
2. From output, identify the 9 FSM + 3 snapshot failures by file::test path.
3. For each failure, capture `pytest --tb=short` output (first 30 lines).
4. Write `.claude/run/observations/S-57-A-inventory.md` with structured list:
   ```
   ## FSM failures (9)
   - tests/test_fsm_X.py::TestY::test_z — <one-line failure summary>
     <tb excerpt>
   ## Snapshot failures (3)
   - ...
   ```
5. Return the inventory in the agent's final response so the coordinator
   knows what to dispatch B and C with.

### Stream B — FSM fixes
For each of the 9 FSM failures from Stream A's inventory:
1. Read the failing test + the product code it exercises.
2. Determine if the failure is in the test (incorrect assertion, stale
   fixture) or in the product (regression).
3. Apply the smaller fix:
   - Test-level fix: update assertion or fixture in the test file.
   - Product-level fix: only if ≤20 lines AND clearly the right answer.
4. Commit per fix with message `fix(fsm): <test name> — <one-line cause>`.
5. If a fix exceeds the 20-line budget, halt that test and write a
   blocker `.claude/run/blockers/S-57-B-<test-id>.md`.

### Stream C — snapshot fixes
For each of the 3 snapshot failures:
1. Read the test + the snapshot file.
2. Run the test with `--tb=short` to see the diff.
3. Determine WHY the snapshot drifted (legitimate change vs unintended).
4. If legitimate: `pytest --snapshot-update tests/<file>::<test>` and commit
   the regenerated snapshot with message `chore(snapshot): regenerate
   <test> — drift cause: <one-line>`.
5. If unintended (drift indicates a real regression): write a blocker; do
   NOT regenerate.

## Verification
1. Stream A: inventory exists at `.claude/run/observations/S-57-A-inventory.md`.
2. After B+C merge: `python3 -m pytest tests/ -q --tb=no` exits 0 (or shows
   only blocker-deferred failures, documented).
3. `python3 ms-enforce` exits 0.
4. Number of FSM + snapshot failures on main drops from 12 to 0 (or to the
   blocker count).

## Out of scope
- Adjacent test failures discovered during fix work — log as observation, do not fix.
- TIER_1 test infrastructure changes (those go in S-56).
- Migrating tests to new patterns (that's a future cleanup wave).

## Robot mode (autonomous execution)

When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
doctrine v3. Stream A is sequential before B and C dispatch (B and C need A's
inventory). Coordinator merges to `wave/S-57-tier2-cleanup` not main.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-57-TIER2-CLEANUP.md as orchestrator.`
