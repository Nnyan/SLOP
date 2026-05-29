# S-60-AGENT-FIX-SAFETY — Verify fixes worked + guard against restart oscillation

## Goal
Pay the safety debt that must precede letting the SLOP Agent *act* (auto-apply)
instead of only recommend: (1) confirm a fix actually made the container healthy
before recording success, and (2) cap/space out repeated auto-fixes so a flapping
container cannot trigger an infinite restart loop.

## Context
- `backend/agent/apply.py::apply_safe_fix()` marks a fix `success` purely on the
  docker subprocess returncode (`_restart_container`/`_repull_restart` return
  `ok=True` on returncode 0; `_mark_applied` then writes fix_history outcome
  'success'). It NEVER confirms the container became healthy afterward.
- `backend/agent/listener.py::_write_pending_fix()` uses `ON CONFLICT ... DO UPDATE
  SET status='pending'` — every new failure re-opens the same row. There is no
  attempt counter or backoff, so a flapping app can be re-fixed indefinitely.
- Today apply is human-triggered via `POST /agent/fixes/{id}/apply`, so the risk
  is latent. This wave builds the primitives so a FUTURE wave can safely
  auto-trigger the safe tier from the health cycle.
- Highest existing migration is `007` (`migrations/007_phase_e_apply_metadata.sql`).
  This wave adds `008`. `ms-enforce::check_migration_sequence` must stay green.

## Rules to follow
- `backend/agent/**` hard cap 500 lines (soft 400). New modules stay well under.
- `verify.py` and `backoff.py` are PURE, unit-testable modules; `apply.py` remains
  the only integrator. No new API routes, no view changes.
- Migration must be the next sequential number; confirm with `ls migrations/` at
  pre-flight before naming it.

## Authorized deletions
- None.

## Parallelization
**Models:** coordinator = **opus**. Streams A∥B concurrent; C integrates after A+B
merge to the wave branch (imports their modules).

| Stream | Model | Subagent type | Scope |
|---|---|---|---|
| A — verify module | sonnet | `general-purpose` in worktree | `backend/agent/verify.py` (new), `tests/test_agent_verify.py` (new) |
| B — backoff module + migration | sonnet | `general-purpose` in worktree | `backend/agent/backoff.py` (new), `migrations/008_fix_attempt_tracking.sql` (new), `tests/test_agent_backoff.py` (new) |
| C — apply integration | sonnet | `general-purpose` in worktree | `backend/agent/apply.py` (edit), `tests/test_agent_apply_safety.py` (new) |

## Deliverables

### Stream A — `backend/agent/verify.py`
Exact public signature (Stream C codes against this):
```python
def verify_container_healthy(
    app_key: str, *, attempts: int = 5, interval_s: float = 3.0
) -> tuple[bool, str]:
    """Poll docker state after a fix. Returns (healthy, summary).
    healthy=True iff container status == 'running' AND
    (no healthcheck defined OR health == 'healthy').
    Never raises; on docker error returns (False, <reason>)."""
```
Use `backend.core.docker_client` for state. Tests mock the docker client and
cover: healthy, still-restarting, unhealthy-healthcheck, docker-error.

### Stream B — `backend/agent/backoff.py` + migration 008
Exact public signatures:
```python
def attempt_allowed(
    app_key: str, fix_type: str, *,
    max_attempts: int = 3, window_s: int = 3600, backoff_base_s: int = 60
) -> tuple[bool, str]:
    """Returns (allowed, reason). Deny if >= max_attempts within window_s, or if
    the last attempt was less than backoff_base_s * 2**(n-1) seconds ago."""

def record_attempt(app_key: str, fix_type: str, outcome: str) -> None:
    """Append a row to fix_attempts (best-effort; never raises)."""
```
`migrations/008_fix_attempt_tracking.sql`: create `fix_attempts`
(`id`, `app_key`, `fix_type`, `outcome`, `created_at` default unixepoch()) +
index on (`app_key`, `fix_type`, `created_at`). Tests use a temp StateDB.

### Stream C — `backend/agent/apply.py` integration
- BEFORE executing any action: `allowed, reason = attempt_allowed(app_key, fix_type)`.
  If not allowed → return `{"ok": False, "message": reason, "fix_type": fix_type}`
  WITHOUT acting.
- AFTER a returncode-0 action: `healthy, summary = verify_container_healthy(app_key)`.
  Only call `_mark_applied` (outcome 'success') when `healthy`. Otherwise add a
  new `_mark_failed` helper (fix_history outcome 'failed_verification', do NOT
  mark the pending_fix applied) and return `{"ok": False, ...}`.
- Call `record_attempt(...)` after every action with the resolved outcome.
- Integration tests mock verify + backoff + subprocess; cover allow→success,
  allow→verify-fail, deny-by-backoff.

## Verification
1. `.venv/bin/pytest tests/test_agent_verify.py tests/test_agent_backoff.py tests/test_agent_apply_safety.py -v` — all pass.
2. `python3 ms-enforce` — exit 0 (esp. `check_migration_sequence`, `check_py_migration_api`).
3. No `frontend/` changes.

## Out of scope
- Auto-triggering the safe tier from the health cycle (future wave — this only
  builds the guardrails).
- `env_var_format` auto-apply (Phase H stub stays a stub).

## Robot mode (autonomous execution)
When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
doctrine v4. Streams A and B parallel; Stream C dispatched after A+B merge to
`wave/S-60-agent-fix-safety` (C imports verify.py and backoff.py). Coordinator
merges all to `wave/S-60-agent-fix-safety`, never main.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-60-AGENT-FIX-SAFETY.md as orchestrator.`
