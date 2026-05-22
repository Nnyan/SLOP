# Known Test Flakes

Pre-existing test failures observed across multiple sessions. Each entry documents what is expected to fail and why, so future pre-flight runs can distinguish expected-pre-existing-failures from genuine regressions.

**Pre-flight contract:** Any test failure that does NOT appear in this register is a regression and tag-blocking. Update this register only when the underlying issue is fixed (remove the entry) or when a new known issue is consciously deferred (add an entry with TODO reference and explicit acceptance).

---

## Flake 1: test_compose_failure_with_fragment_leaves_status_failed

- **File:** tests/test_fsm_app_install.py
- **Test class:** TestT2AbsentToFailed
- **Observed since:** v4.2 hardening sessions (2026-05-09 onward)
- **Symptom:** PermissionError during fixture teardown
- **Cause:** Test reaches real Docker via backend.health.checker._container_* subprocess calls despite mocks; Docker runs as root and leaves root-owned scratch files
- **TODO reference:** docs/TODO_2026_05_10_root_owned_test_files.md
- **Expected fix milestone:** v4.3
- **Mitigation:** Scoped sudoers entry permits `sudo rm -rf /tmp/pytest-base/*` to clear scratch between runs

## Flake 2: test_no_orphaned_records_after_failed_install_no_fragment

- **File:** tests/test_fsm_app_install.py
- **Test class:** TestInvariants
- **Observed since:** v4.2 hardening sessions (2026-05-09 onward)
- **Symptom:** Same as Flake 1
- **Cause:** Same as Flake 1 (test in same family)
- **TODO reference:** docs/TODO_2026_05_10_root_owned_test_files.md
- **Expected fix milestone:** v4.3
- **Mitigation:** Same as Flake 1

## Flake 3: test_route_GET__api_platform_wizard_stack_app_keys_responds

- **File:** tests/test_generated_behavioral.py
- **Symptom:** sqlite3.OperationalError: no such table: operation_steps
- **Cause:** Suspected test-ordering or state-leak issue — passes in isolation, fails in full-suite run under certain seeds
- **Observed since:** v4.2 Tier 1 sessions (~2026-05-10)
- **TODO reference:** TBD — this flake has not been formally investigated yet
- **Expected fix milestone:** v4.3 (file TODO during v4.3 planning)
- **Mitigation:** None; sporadic in nature

## Flake 4: 104-test PermissionError cascade (installer/tests/)

- **Observed since:** v5.0 Tier 3 close (2026-05-17); documented at v5.0.0 audit gate 2026-05-19
- **Symptom:** 104 tests in installer/tests/ receive ERROR at setup with:
  `PermissionError: [Errno 13] Permission denied: '/tmp/pytest-base/test_failed_is_reachable0/config/sonarr'`
- **Affected files and error counts (as of audit-run HEAD afa43b1, 2026-05-19):**
  - installer/tests/test_check_readiness.py — 39 errors
  - installer/tests/test_state.py — 38 errors
  - installer/tests/test_frontend.py — 8 errors
  - installer/tests/test_post_install.py — 7 errors
  - installer/tests/test_smoke.py — 5 errors
  - installer/tests/test_prereq.py — 3 errors
  - installer/tests/test_fetch.py — 3 errors
  - installer/tests/test_detect.py — 1 error
- **Cause:** The root-owned directory `/tmp/pytest-base/test_failed_is_reachable0/config/sonarr`
  was left behind by a previous test run that invoked real Docker (without `fake_docker`).
  pytest cannot clean up the shared basetemp directory before creating fixtures for new tests,
  so all tests that request tmpdir-based fixtures fail at setup with PermissionError.
  This is the same root cause as Flakes 1 and 2, but affecting the installer/ test suite
  rather than backend FSM tests, due to a different root-owned directory path.
- **Summary line (audit-run HEAD):** 641 passed, 2 warnings, 104 errors in 0.97s
- **TODO reference:** docs/TODO_2026_05_10_root_owned_test_files.md
- **Acceptance rationale (v5.0.0):** Pre-existing infrastructure issue. The tests themselves
  are correct; the cascade is caused by operator environment state (root-owned scratch files).
  Not a v5.0 code regression. Accepted for v5.0.0; deferred to v4.3 backlog for structural fix.
- **Expected fix milestone:** v4.3
- **Mitigation:** `sudo rm -rf /tmp/pytest-base/` before test runs clears root-owned
  scratch and restores normal test operation.

## Flake 5: test_tailscale_deploy_fails_gracefully (StateDB drift)

- **File:** tests/test_step7.py
- **Test class:** TestNewProviders
- **Test:** test_tailscale_deploy_fails_gracefully
- **Observed since:** v5.0.0 audit gate 2026-05-19 (F-08-NEW-4)
- **Symptom:** `backend.core.state.StateError: Database path not configured. Call state.configure(path) at startup before using StateDB.`
- **Cause:** `backend/infra/providers/tunnel_tailscale.py` was modified at commit `18b0ce0`
  (pre-v5.0) introducing a StateDB dependency in the `deploy()` method. The test in
  `tests/test_step7.py` was last modified at commit `5a33300` (also pre-v5.0) and never
  received the corresponding `state.configure(path)` call at setup. This is pre-v5.0
  test/production drift — NOT a Tier 4 regression introduced during the v5.0 installer arc.
- **Affected tests:** 1 (test_tailscale_deploy_fails_gracefully)
- **TODO reference:** Step 7 backlog (no dedicated TODO file yet)
- **Acceptance rationale (v5.0.0):** Pre-v5.0 origin; not a Tier 4 regression. Accepted for
  v5.0.0 per F-08-NEW-4 disposition.
- **Resolution path (deferred):** Patch test to call `state.configure(path)` at setup with a
  temp DB, OR mock `StateDB` so the test runs without a real configured database.
- **Expected fix milestone:** v5.0.1 or later

---

## Maintenance

Add an entry to this register when:
- A test failure is consciously deferred (with TODO reference and acceptance rationale)
- A flake is observed across 2+ sessions and has been classified as pre-existing rather than a regression

Remove an entry from this register when:
- The underlying issue is fixed (record the closing commit in the entry history before removal, then remove)

Audit cross-reference: docs/RELEASE_PROCESS.md §3.2 (pre-flight verification step) checks all test failures against this register. Any undocumented failure is tag-blocking.
