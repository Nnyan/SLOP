# S-46-PIN-RELAX — Finish the no-pinning policy + CVE-2026-48710 defense-in-depth

## Goal
Complete the dependency-policy migration the Sonnet session started (uv.lock was
committed but requirements.txt / pyproject.toml were not relaxed), and add a
defense-in-depth middleware against the audit-log-evasion impact of the Starlette
BadHost CVE. Also bring `.gitignore` up to date with current tooling-cache
realities.

## Context
- Policy (recorded in user memory `feedback-no-version-pinning`): floor-only `>=`
  in requirements.txt; upper caps `<N+1` only with a written reason; reproducibility
  comes from `uv.lock` (committed).
- Catalyst CVE: CVE-2026-48710 ("BadHost"), Starlette < 1.0.1 reflects unvalidated
  Host header into `request.url`. SLOP's specific exposure is **audit-log evasion**
  in `AuditLogMiddleware` (uses `request.url.path in _AUDIT_PATH_BLOCKLIST`). No
  path-based auth middleware exists, so the headline auth-bypass vector does not
  apply.
- Half-step in main: f8481b6 committed `uv.lock`; 37ea3d2/d56c1d9 added + reverted
  a test-failures rule. **Do not re-add that rule** — see
  `feedback-no-fix-all-failures-rule` in user memory.
- `pyproject.toml` currently has **no `[project]` section** — only
  `[dependency-groups]` with 4 dev deps. The committed `uv.lock` therefore locks
  only the dev group; production deps from `requirements.txt` are NOT in the
  lockfile. Production reproducibility is not actually achieved yet.

## Rules to follow
- No exact `==` pins added. Floor-only (`>=`). Upper cap only with a one-line
  reason comment naming what breaks above it.
- After relaxing requirements + adding `[project]`, regenerate `uv.lock` so it
  covers production deps too. Verify with `uv lock --check` (or equivalent).
- The catalyst CVE must end with a defense-in-depth middleware shipped, even
  though the underlying fix flows through transitively on lockfile refresh. The
  audit-evasion gap is independent of Starlette version.
- Do NOT touch any wave files, CLAUDE.md rules sections, or ADRs in this wave.
  Doc updates land in `installer/DEPENDENCIES.md` only (per Stream A).
- Do not add or revive any "fix all pre-existing failures" rule under any phrasing.

## Parallelization

**Models:** coordinator = **opus**, subagents = **sonnet**. Rationale: Stream A
has a known failure mode (Sonnet already half-shipped this — committed `uv.lock`
without relaxing `requirements.txt` or adding `[project]`); Opus coordinator
catches that drift. Mechanical stream work is fine on Sonnet. Pass `model: "sonnet"`
in each `Agent` call.

**You are the coordinator agent.** Dispatch the three streams below as concurrent
`Agent` subagent calls in a single message with `isolation: "worktree"`. Do NOT
execute them yourself sequentially. After all three finish, merge the worktrees
back to main (one commit per stream where natural, can be two for stream A) and
report the merge result.

The three streams touch disjoint files:

| Stream | Subagent type | Scope |
|---|---|---|
| A — deps policy | `general-purpose` in worktree | `requirements.txt`, `pyproject.toml`, `backend/requirements.txt` (delete), `uv.lock` (regen), `installer/DEPENDENCIES.md` (policy section) |
| B — CVE defense-in-depth | `general-purpose` in worktree | `backend/api/main.py` (add TrustedHostMiddleware), `backend/core/config.py` if a new setting is needed, one test file |
| C — gitignore hygiene | `general-purpose` in worktree | `.gitignore` only |

## Deliverables

### Stream A — Dependency policy completion

#### A1. Relax `requirements.txt` to floor-only
Replace every `==` with `>=` keeping the current resolved version as the floor.
The one exception is `pydantic` — keep an upper cap of `<3` with a one-line
comment naming Pydantic v1-compat shims our validators still use.

Target shape (verify floors against current `uv.lock` first):
```
fastapi>=0.136
uvicorn[standard]>=0.32
python-multipart>=0.0.20
httpx>=0.28
docker>=7.1
pyyaml>=6.0
# Pydantic — cap at <3: v3 removes v1-compat shims used by manifest validators.
pydantic>=2.10,<3
bcrypt>=4.0.0
structlog>=24
slowapi>=0.1.9
prometheus-fastapi-instrumentator>=7.1
prometheus-client>=0.25
```

Add a header comment block citing the policy memory and pointing at
`installer/DEPENDENCIES.md` for full rationale.

#### A2. Add `[project]` section to `pyproject.toml`
Mirror `requirements.txt` into a proper `[project]` block so `uv lock` locks the
production set too. Use the same ranges as A1. Keep the existing
`[dependency-groups]`, `[tool.vulture]`, `[tool.pytest.ini_options]` sections
unchanged.

#### A3. Delete `backend/requirements.txt`
Stale fossil (pins `fastapi==0.115.6` vs live 0.136.1). Not referenced by the
installer (`installer/backend.py:109` reads root `requirements.txt`). Confirm no
other reference with `grep -rn "backend/requirements" .` before deleting.

#### A4. Regenerate `uv.lock`
Run `uv lock` (or `uv lock --upgrade` if floors changed enough to need it) so
the lockfile reflects the new `[project]` section. Verify `grep -c "^name = " uv.lock`
now lists ~30+ packages (production + dev), not just the dev 15.

#### A5. `installer/DEPENDENCIES.md` — policy section
Append a new section "Dependency-version policy" with:
- `requirements.txt` declares **intent** (ranges, supported versions)
- `uv.lock` declares **resolution** (committed, drives installs)
- Caps need a documented breakage reason; floors are the default
- Bumps land via the dependency-refresh train (forward reference: S-49)
- `pip-audit` runs against `uv.lock` and surfaces transitive CVEs

### Stream B — CVE-2026-48710 defense-in-depth

#### B1. Add `TrustedHostMiddleware` to `backend/api/main.py`
Insert after the CORS middleware, before `CorrelationIdMiddleware`. Allowed
hosts list comes from:
- `config.domain` (if set in the wizard)
- `localhost`, `127.0.0.1`, `::1`
- `*.local` (LAN access)
- Honor an env override `MS_TRUSTED_HOSTS` (comma-separated) for advanced setups

If `config.debug` is true, fall back to `allowed_hosts=["*"]` (dev convenience),
with a startup log line noting the relaxed setting.

#### B2. Test in `tests/test_trusted_host.py`
Three cases minimum:
- Request with valid Host header (matches config.domain) → 200
- Request with a malformed Host header that would trick `request.url.path` (e.g.
  `Host: /healthz?evil#`) → 400 from the middleware
- `MS_TRUSTED_HOSTS` env override is honored

#### B3. Brief note in `backend/api/main.py` near the middleware
One-line comment naming the CVE and pointing at the project memory:
```python
# TrustedHostMiddleware: closes audit-log-evasion gap from CVE-2026-48710 (Starlette
# BadHost) independent of Starlette version. See memory project-cve-2026-48710.
```

### Stream C — gitignore hygiene

Edit `.gitignore` only. Add (with one-line section comment each):
- `.mypy_cache/`
- `.ruff_cache/`
- `.claude/worktrees/` — per-agent isolation scratch, never shared

Do NOT touch the existing entries. Do NOT do the `backend/static` cleanup TODO
(that belongs to S-48). Do NOT touch `data/tailscale/*` (that belongs to S-48).

## Verification

After all three streams merge:
1. `.venv/bin/pip install -r requirements.txt` exits clean
2. `grep -c "^name = " uv.lock` shows ≥30 packages (was 15)
3. `grep -n "==" requirements.txt` returns nothing (no exact pins remain except inside the policy header comment)
4. `ls backend/requirements.txt` returns no such file
5. `.venv/bin/pytest tests/test_trusted_host.py -v` — all pass
6. `python3 ms-enforce` exits 0
7. `git status --short` shows no `.mypy_cache/` or `.ruff_cache/` entries
8. `grep -n "Dependency-version policy" installer/DEPENDENCIES.md` matches

## Out of scope
- Track-status invariant gate (S-48)
- Dependency refresh train tooling (S-49)
- `backend/static`, `data/tailscale/*`, INSTALL/MIGRATION/docker-compose dedup (S-47)
- ADR / docs/MAP / rules-to-tests audit (S-50)
- Re-adding the fix-all-failures rule under any phrasing

## Robot mode (autonomous overnight execution)

When this wave is launched with the prefix "in Robot mode" in the user's prompt,
this wave operates under `.claude/ROBOT.md` doctrine and the default decision
register at `.claude/AUTONOMOUS-DEFAULTS.md`. Both files must be read before
dispatching any subagent. Summary of binding rules (see ROBOT.md for full text):

1. NEVER call `AskUserQuestion`. Write a decision file instead and continue.
2. NEVER enter plan mode.
3. NEVER use interactive Bash (`sudo`, `-i` flags).
4. On hard blocker, write `.claude/run/blockers/S-46-<stream>.md` and halt
   only that stream — other streams continue.
5. Maintain `.claude/run/status/S-46.md` continuously.
6. Merge streams to branch `wave/S-46-pin-relax`, **NOT** `main`. The wave
   branch stays local; morning review handles the merge to main.
7. NEVER `git push`. Settings deny it.
8. Pass `model: "sonnet"` in each subagent `Agent` call (per Parallelization
   section above). Add an "in Robot mode" preamble to each subagent's prompt.
9. One try on test failures — halt the stream rather than retrying widely.
10. No scope creep — log adjacent issues to `.claude/run/observations/` and
    leave them.

Robot mode invocation: `in Robot mode: execute the wave defined in .claude/waves/S-46-PIN-RELAX.md as coordinator.`
