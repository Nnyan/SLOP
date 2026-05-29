# S-64-AGENT-SAFE-AUTOFIX — Let the agent ACT on safe-tier diagnoses (opt-in)

## Goal
Turn the SLOP Agent from advisor into actor for the safe tier only: add an OPT-IN
health-cycle step that auto-applies high-confidence, safe-tier pending fixes through
the existing `apply_safe_fix` path — which already gates every action on S-60's
backoff (oscillation cap + exponential spacing) and post-fix health verification.
This is OFF by default; operators opt in via a settings flag. It realizes the
"act when sane/logical, recommend otherwise" requirement without adding any new
autonomy primitive — it only connects the already-built, already-guarded apply path
to the health cycle.

## Context
- Today `apply_safe_fix` runs ONLY when a human POSTs `/agent/fixes/{id}/apply`
  (`backend/agent/api.py`). The detect→classify→diagnose pipeline writes
  `pending_fixes` rows but nothing auto-applies them.
- S-60 (on main @ `084d9d8`) added the guardrails that make autonomous action safe,
  enforced INSIDE `apply_safe_fix`: `backoff.attempt_allowed` and
  `verify.verify_container_healthy`. This wave must NOT duplicate them — it relies on
  `apply_safe_fix` enforcing them.
- `backend/agent/apply.py`: `apply_safe_fix(fix_id, row)`; `get_fix_type(diagnosis_class) -> fix_type`;
  `SAFE_FIX_TYPES = {restart_container, repull_restart, env_var_format}` where
  `env_var_format` is a Phase-H stub (must be EXCLUDED from auto-apply).
- `pending_fixes` columns include `confidence REAL`, `status`, `diagnosis_class`.
- Scheduler ambient post-cycle checks live in `backend/health/scheduler.py::_scheduler_loop`
  (sibling pattern: `_check_and_restart_traefik`, `_check_disk_space` — each sync,
  each swallows its own exceptions).

## Rules to follow
- **OFF BY DEFAULT.** New settings keys: `agent_autofix_enabled` (default `False`) and
  `agent_autofix_min_confidence` (default `0.9`). Read each cycle (like other scheduler
  config) so changes take effect without a restart.
- Auto-apply ONLY when ALL hold: enabled, `status='pending'`,
  `get_fix_type(diagnosis_class)` in `SAFE_FIX_TYPES` **excluding `env_var_format`**,
  and `confidence >= threshold`. Backoff + verify are enforced by `apply_safe_fix`
  itself — do NOT re-implement.
- Never raise into the scheduler loop — best-effort, swallow + log (like sibling checks).
- `backend/agent/**` and `backend/health/**` hard cap 500 lines.
- Auditability: log an INFO line distinguishing auto-applied from manual; the existing
  apply path already does `record_attempt` + `fix_history`.

## Authorized deletions
- None expected.

## Parallelization
This batch fires under ONE orchestrator covering all waves (one-orchestrator-per-batch
rule); the assignments below govern only THIS wave's subagents. **Coordinator = opus.**
Stream A (selection module) is pure + testable and merges first; Stream B (scheduler
wiring) codes against A's signature.

| Stream | Model | Subagent type | Scope |
|---|---|---|---|
| A — autofix selection module | opus | `general-purpose` in worktree | `backend/agent/autofix.py` (new), `tests/test_agent_autofix.py` (new) |
| B — scheduler wiring | sonnet | `general-purpose` in worktree | `backend/health/scheduler.py` (edit: add `_maybe_auto_apply_safe_fixes` + call it in the post-cycle ambient block; read the two new settings), `tests/test_autofix_scheduler.py` (new) |

## Deliverables

### Stream A — `backend/agent/autofix.py` (defines the contract B codes against)
- Exact signature:
  ```python
  def select_auto_applicable(*, min_confidence: float) -> list[Any]:
      """Return pending_fixes rows eligible for autonomous safe-tier apply:
      status='pending', confidence >= min_confidence, and
      get_fix_type(diagnosis_class) in SAFE_FIX_TYPES MINUS {'env_var_format'}.
      Ordered by confidence DESC. Read-only; never raises (returns [] on error)."""
  ```
- The eligible fix_types are derived from `apply.get_fix_type` / `apply.SAFE_FIX_TYPES`
  (import them — single source of truth; do not hardcode a second copy), minus the
  `env_var_format` stub.
- Tests (temp StateDB): high-confidence safe row included; low-confidence excluded;
  non-safe diagnosis_class excluded; `env_var_format` excluded; already-applied
  excluded; DB error → `[]`.

### Stream B — scheduler wiring
- Add to `backend/health/scheduler.py`:
  ```python
  def _maybe_auto_apply_safe_fixes() -> None:
      """If agent_autofix_enabled, auto-apply eligible safe-tier pending fixes via
      apply_safe_fix (which enforces backoff + post-fix verify). Off by default.
      Never raises."""
  ```
  Reads `agent_autofix_enabled` (default False) + `agent_autofix_min_confidence`
  (default 0.9); if disabled → return immediately; else iterate
  `select_auto_applicable(...)`, call `apply_safe_fix(row['id'], row)` for each, and
  log auto vs manual. Add the call to the ambient post-cycle block in `_scheduler_loop`
  (next to `_check_and_restart_traefik`, etc.).
- Tests: enabled + safe high-confidence pending → `apply_safe_fix` invoked (mock);
  disabled (default) → no-op (assert `apply_safe_fix` NOT called); low-confidence →
  skipped; `apply_safe_fix` raising → swallowed, loop continues.

## Verification
1. `.venv/bin/pytest tests/test_agent_autofix.py tests/test_autofix_scheduler.py -v` — all pass.
2. **Default-OFF assertion:** with no settings present, the cycle does NOT auto-apply
   (an explicit test asserts this).
3. `python3 ms-enforce` — exit 0 (file-size ratchet, mypy).
4. No `frontend/` changes.

## Out of scope
- `env_var_format` auto-apply (Phase-H stub stays a stub and is excluded here).
- Any LLM/router changes (S-63).
- A frontend toggle for the flag (settings key only; UI surfacing is a later wave).
- Auto-apply of non-safe tiers (those stay human-gated via the 422 path).
- Auto-triggering on the docker-event watcher path (health-cycle scan only this wave).

## Cross-wave dependencies (EXPLICIT)
- **Depends ONLY on S-60**, which is already on main (`084d9d8`). No other dependency.
- **Independent of and file-disjoint from S-63** (this wave: `autofix.py`,
  `scheduler.py`; S-63: `router/*`, `checker.py`, `classifier.py`). **May merge to main
  in ANY order relative to S-63.**
- Adds NO migration (reuses `pending_fixes` + S-60's `fix_attempts`) — no numbering
  collision with S-63's migration `009`.

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine v4. Stream A merges to the wave branch first;
B codes against its signature. Coordinator merges all to `wave/S-64-agent-safe-autofix`,
never main. Post-wave merge to main goes through the sanctioned operator channel.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-64-AGENT-SAFE-AUTOFIX.md as orchestrator.`
