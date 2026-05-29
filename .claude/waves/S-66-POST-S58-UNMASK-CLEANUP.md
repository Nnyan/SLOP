# S-66-POST-S58-UNMASK-CLEANUP — Fix the 12 unmasked + 30 A-bucket pre-existing failures from S-58

## Goal
Drain the carried-over pre-existing test failures from S-58's residual-43:
12 failures UNMASKED by the host-header fix (testserver→localhost) that were
previously hidden behind HTTP 400s, plus 30 A-bucket failures that pre-dated
S-58 and were correctly left alone per scope discipline. This wave IS the
authorized fix-all-failures scope for those specific items — the no-fix-all-
failures rule still applies to OTHER waves.

## Context
- S-58 (commit `d13daf5` on main) fixed 417 TestClient `Host: testserver`→400
  failures via `base_url="http://localhost"` fixture changes. Test suite went
  450 failures → 43.
- The residual 43 break down as:
  - **30 = A-bucket pre-existing** (predate S-58; cataloged in
    `.claude/run-archive/2026-05-29-batch4/observations/S-58-A-inventory.md`)
  - **12 = newly visible** (requests now reach handlers and hit real bugs:
    `/srv/mediastack` PermissionError + cross-test DB pollution)
  - **1 = validate-wave-file false-positive on S-59 wave file** — owned by S-67
- Batch-5 (S-59 + S-63 + S-64) is between this wave's design and execution.
  This wave MUST be drafted against post-batch-5 main, not pre. Stream A
  re-inventories first to confirm which failures are still present after
  batch-5's code changes (some may incidentally resolve; others may shift).

## Rules to follow
- This wave IS the authorized fix-all-failures scope for these specific 42
  failures (12 + 30). The no-fix-all-failures doctrine still applies to
  OTHER waves — they observe pre-existing, they don't fix.
- Per-fix product-code budget: ≤20 lines outside `tests/`. If a fix requires
  more, halt that stream and write a blocker (same S-57 pattern).
- Stream A must re-inventory against current main at wave-start. Don't trust
  the S-58 inventory blindly; batch-5 may have shifted what's failing.
- For test-fixture fixes (most expected fixes): use shared conftest fixtures
  when multiple tests share the root cause (e.g., the `/srv/mediastack` path
  issue probably needs ONE fixture change, not 12 per-test fixes).
- For snapshot drift: verify in real checkout per AUTONOMOUS-DEFAULTS
  "worktree-artifact trap" doctrine.

## Authorized deletions
- Tests whose product code no longer exists (genuinely obsolete) may be
  deleted with rationale in commit message. List each in Stream A's
  inventory output; coordinator confirms before any deletion.

## Parallelization

**Models:** coordinator = **opus** (judgment-heavy root-cause attribution),
subagents = **sonnet**. Four streams: A sequential first, then B/C/D parallel.

| Stream | Order | Subagent type | Scope |
|---|---|---|---|
| A — re-inventory + bucket | sequential first | `general-purpose` in worktree | Full test suite vs current main; classify still-failing tests into "unmasked" / "A-bucket migration+db" / "A-bucket fixture+config" / "A-bucket misc"; output `.claude/run/observations/S-66-A-inventory.md` |
| B — unmasked fixes | parallel after A | `general-purpose` in worktree | `/srv/mediastack` PermissionError (likely shared conftest fixture for tmp-path); cross-test DB pollution (review StateDB fixture scoping + teardown); related test isolation issues from A's inventory |
| C — migration + db + missing-script | parallel after A | `general-purpose` in worktree | Migration 005 idempotency (`IF NOT EXISTS` guards / schema-check), missing `tools/check_cleanup_ledger.py` (implement or remove refs), ollama_url default mismatch (align test vs code) |
| D — config + signature + misc | parallel after A | `general-purpose` in worktree | Traefik signature drift, `health try/except` gaps, remaining A-bucket items per Stream A's classification |

## Deliverables

### Stream A — re-inventory
1. `python3 -m pytest tests/ -q --tb=no` on current main (post-batch-5).
2. For each still-failing test, capture `pytest --tb=short` first 30 lines.
3. Bucket each failure into one of: `unmasked-permission`, `unmasked-db-pollution`,
   `migration-idempotency`, `missing-script`, `config-default-mismatch`,
   `signature-drift`, `exception-handling`, `misc` (with one-line note for each
   misc entry).
4. Write `.claude/run/observations/S-66-A-inventory.md` with the structured
   classification + the count per bucket. Return summary so coordinator knows
   what B/C/D need to address.

### Stream B — unmasked-12 fixes
- For PermissionError on `/srv/mediastack`: identify the shared conftest fixture
  (likely `tests/conftest.py` or similar). Add a fixture that creates a tmp
  `MS_DATA_DIR` and overrides the env var. Tests now write to tmp instead of
  `/srv/mediastack`. ONE fixture change, many tests fixed.
- For cross-test DB pollution: review `StateDB` fixture scope. Confirm per-test
  isolation OR add explicit teardown. Likely 1-3 conftest changes.
- Commit per root-cause-cluster with message `fix(test): <cluster> — unmask-12 fallout from S-58`.

### Stream C — migration + db + missing-script
- Migration 005: add `IF NOT EXISTS` guards or check schema state before
  applying. Verify with `check_py_migration_api` ms-enforce.
- Missing `tools/check_cleanup_ledger.py`: investigate whether the work was
  ever done (git log, grep for the function name). Either implement OR remove
  the references from tests/ms-enforce. Commit per decision.
- `ollama_url` default mismatch: identify the source-of-truth default
  (`backend/core/config.py`?) and align tests to it.

### Stream D — config + signature + misc
- Traefik signature drift: identify what the test asserts vs what's emitted.
  Update test to match current signature (or revert signature if it changed
  inadvertently — investigate first).
- `health try/except`: locate the gap; add missing exception handler matching
  the pattern in sibling code paths.
- Misc A-bucket items per Stream A's inventory: per-item, fix or escalate.

## Verification
1. `python3 -m pytest tests/ -q --tb=no` exits 0 (or close to it; document any
   blocker-deferred residuals).
2. `python3 ms-enforce` exits 0.
3. `tests/test_validate_wave_file.py` not changed by this wave (owned by S-67).
4. Failure count: from S-58's residual 43 → ≤2 (the 1 validate-wave-file
   false-positive owned by S-67 plus any blocker-deferred).

## Out of scope
- The 1 validate-wave-file false-positive — owned by S-67.
- Doc-hygiene cleanup (88 broken links, etc.) — owned by S-67.
- Building new features or refactoring beyond what's needed to fix the failures.
- Migration to a different test framework.
- Tooling improvements that slipped from S-56 — owned by S-67.

## Cross-wave dependencies (EXPLICIT)
- Depends on batch-5 being fully merged to main first (batch-5 may shift what
  fails; we need stable ground to inventory against).
- File-disjoint and parallel-safe with S-67 (this wave: test fixtures +
  backend product code where needed; S-67: docs, tools/, CLAUDE.md/CONTRIBUTING).
  May merge to main in any order with S-67.

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine v4. Stream A sequential first;
B/C/D parallel after. Coordinator merges all to `wave/S-66-post-s58-unmask-cleanup`,
never main. Post-wave merge to main goes through the sanctioned operator channel
(or `tools/merge_wave_to_main.py` once S-59 Stream D ships).

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-66-POST-S58-UNMASK-CLEANUP.md as orchestrator.`
