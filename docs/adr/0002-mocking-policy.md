# ADR 0002 — Mocking Policy

**Status:** Accepted 2026-05-08 (step 2.2.b)
**Decided by:** OPUS during cleanup step 2.2 (Mocking Discipline Audit)
**Supersedes:** none
**See also:** [`docs/cleanup/STEP_2_2_MOCKING_AUDIT_STRATEGY.md`](../cleanup/STEP_2_2_MOCKING_AUDIT_STRATEGY.md) (survey + worked examples), Core Rule 4.12 (Mocking Discipline) — enforced by ms-enforce

## Context

The Mediastack test suite has 729 mock-related lines across 22 files. A 2026-05-08 audit found that ~40% of these are project-internal mocks: tests patch functions defined in `backend/` to short-circuit work the test claims to verify.

Concrete example from `tests/test_executor.py::TestInstallApp::test_successful_install`:

```python
@patch("backend.manifests.executor.subprocess.run", side_effect=...)
@patch("backend.manifests.executor.docker_client.ports_in_use", ...)
@patch("backend.manifests.executor.docker_client.get_container", ...)
@patch("backend.manifests.executor.write_fragment")           # ← project internal
@patch("backend.manifests.executor.write_compose_file")       # ← project internal
@patch("backend.manifests.executor.httpx.get")
def test_successful_install(...):
    with patch("pathlib.Path.mkdir"):
        result = install_app("sonarr")
    assert result.ok
```

The test calls `install_app()` and asserts `result.ok` — but every internal helper that `install_app` invokes is mocked. The test passes whenever the install function happens to return an OK result, regardless of whether `write_fragment` or `write_compose_file` was actually called, called with correct args, or produced correct output. This is the **Q3 false-positive class**: tests that pass while production breaks.

## Decision

Tests mock at the **system boundary** — not at the **project boundary**.

**System boundary** is anything outside the project's source tree:

- subprocess (`subprocess.run`, `subprocess.Popen`, `asyncio.create_subprocess_exec`)
- network (`httpx.AsyncClient`, `httpx.Client`, `urllib.request.urlopen`, `socket.create_connection`)
- filesystem ops we can't or shouldn't perform in tests (`pathlib.Path.mkdir` when target is system-owned; `shutil.disk_usage`)
- docker SDK (`backend.core.docker_client.*` — wraps `docker-py`; the wrapper is the boundary)
- /proc readers (`backend.core.system_eval.read_meminfo`)
- third-party SDKs (`docker`, `httpx`, etc.)
- third-party CLIs (`docker compose`, `nvidia-smi`)

**Project boundary** is anything defined in `backend/`:

- `backend.manifests.executor.write_fragment`
- `backend.manifests.executor.write_compose_file`
- `backend.manifests.executor.remove_fragment`
- `backend.manifests.executor._get_active_tunnel_provider`
- `backend.health.checker._attempt_self_heal`
- `backend.health.scheduler.start_scheduler`
- `backend.core.state.StateDB`
- `backend.core.config.config`
- … and 80+ more across the suite

**Use real fakes for the project boundary instead of mocks:**

| Pattern | Replace mock with |
|---|---|
| `patch("backend.manifests.executor.write_fragment")` | A `tmp_path`-rooted compose dir (real fragment is written; assertion checks file content) |
| `patch("backend.core.state.StateDB")` | `init_db(tmp_path / "state.db")` then real `StateDB()` (the 1.5.d autouse-reset pattern) |
| `patch("backend.core.config.config")` | A fixture that creates a `Config(...)` with test-appropriate paths and patches the singleton import |
| `patch("backend.manifests.executor.load_manifest")` | Drop a real test manifest into a fixture-controlled catalog dir |
| `patch("backend.health.checker._attempt_self_heal")` | Test `_attempt_self_heal` separately as its own unit; in the orchestrator test, drive a path where it isn't called or assert on its DB-recorded outcome |

### Exception clauses

Patching a project function **is** acceptable when:

1. **The function performs I/O at the system boundary** that the alternative real-fake doesn't cover. Example: `patch("backend.manifests.executor.docker_client.get_container")` is technically a project import path but the real call hits the docker daemon which isn't running in CI. **Treat as boundary mock.**

2. **The test is specifically about a single helper's behaviour** and patching adjacent helpers is the simplest way to isolate. Example: a unit test for `_extract_diagnosis()` doesn't need real `_persist_pending_fix`; mocking it keeps the test focused. **Document the exception with a comment on the patch line.**

3. **The function is parameterised at module-import-time** and overriding it via `patch` is the only practical way to swap it. Example: a singleton like `backend.core.config.config` (until that's refactored to dependency injection — separate work).

### When in doubt: prefer the real thing

If you're considering a `patch("backend.X.Y")` decorator, ask: "Does the real Y do system I/O I can't run in CI?" If no, use the real thing — even if that means a fixture or a test DB row. Tests that exercise real code catch real regressions.

## Consequences

### Positive

- **Higher behavioural coverage.** Tests that exercise real `write_fragment` actually check that the compose YAML emitted matches the manifest — a class of regression mocks can never catch.
- **Refactor safety.** When `_install_inner` is split (as in step 1.4.d), tests using real fakes only fail when output behaviour changed, not when an internal helper got renamed.
- **Better test independence.** Real fakes scoped to `tmp_path` are by construction order-independent (step 1.5 backlog).
- **Pairs cleanly with Core Rule 4.4** (behavioural coverage > source coverage).

### Negative

- **Slower per-test run time.** Real DB init takes ~50ms vs a mocked `StateDB` at 0ms. Mitigated by module-scoped fixtures (the 1.5.d pattern) so the cost amortises.
- **Bigger fixture surface.** Replacing 5 internal mocks with one fixture is fewer lines but the fixture itself is more code than a `@patch` decorator.
- **Some legacy tests stay over-mocked.** Step 2.2.d picks the 5 highest-risk for replacement; the long tail (~85 internal-mock targets) is migrated as those tests are touched for other reasons. The `ms-enforce` `check_mock_discipline` warning surfaces them gradually.

### Neutral

- **Auto-generated tests** (`tests/test_generated_behavioral.py`) are governed by `ms-testgen`'s output policy — `ms-testgen` is updated to emit boundary-only mocks if it ever drifts (currently it produces external-only patches, so this rule is already satisfied there).
- **Snapshot tests** (step 2.1) are exempt — they don't use mocks; their isolation comes from fixture-controlled state.

## Status

Accepted. Enforced via:

- **Process:** new tests should follow the policy; reviewers cite this ADR + Rule 4.12 when flagging internal mocks in code review.
- **Tooling:** `ms-enforce` Tier 2 `check_mock_discipline` (step 2.2.e) warns when a single test stacks more than 3 internal mocks.
- **Coverage:** `ms-coverage` rule `mocking-discipline` tracks compliance.

The 5 highest-risk over-mocked tests are listed in `STEP_2_2_MOCKING_AUDIT_STRATEGY.md` Section 2 — their behavioural-equivalent rewrites land in step 2.2.d (deferred to focused session).
