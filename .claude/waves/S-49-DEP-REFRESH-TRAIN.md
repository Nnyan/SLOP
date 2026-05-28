# S-49-DEP-REFRESH-TRAIN — Automated dependency refresh PR train

## Goal
Build the system that periodically bumps `uv.lock` (and only `uv.lock`),
exercises the full real-functionality test stack against the refreshed
resolution, and produces a reviewable PR with a version-diff table + per-package
CHANGELOG snippets. Manual edits to `requirements.txt` become rare;
versions move forward on a deliberate schedule.

## Context
- Depends on S-46 having merged: requires floor-only `requirements.txt` +
  `pyproject.toml [project]` + committed `uv.lock` covering production deps.
  Without that foundation, `uv lock --upgrade` has nothing meaningful to bump.
- Test stack already in place (do not re-build): `pytest` (unit, integration,
  docker, browser, slow markers), `schemathesis`, `playwright`, `keploy`,
  `hypothesis`, `mutmut`, `pip-audit`, `bandit`, `ms-enforce`, file-size
  ratchet. This wave wires them as the upgrade gate.
- Catalyst: CVE-2026-48710 (Starlette BadHost). With the refresh train running,
  the next CVE in a transitive dep flows through automatically on the next
  refresh PR rather than requiring manual diagnosis.

## Rules to follow
- The refresh PR bumps `uv.lock` ONLY. `requirements.txt` ranges stay stable
  (they declare intent, not resolution).
- If a bump introduces a new CVE (per `pip-audit` against the new lock), fail
  the PR — don't merge a refresh that worsens security.
- One refresh PR per cycle (weekly cron + CVE-triggered). Do NOT auto-split per
  package; the value is letting the resolver pick a coherent set.
- The CHANGELOG-fetch helper is best-effort. If PyPI / GitHub metadata is
  missing, the PR body just notes "no changelog found for {pkg}" — do not block.
- On test failure, the PR is auto-closed (or marked failure-needs-human) — do
  NOT merge red. Previous `uv.lock` stays authoritative.

## Parallelization

**Models:** coordinator = **opus**, subagents = **sonnet**. Rationale: most
architecturally loaded wave — workflow design, audit-regression abort semantics,
force-pushed PR branch strategy, test-stack ordering, PR-body construction.
Coordinator drives those calls; stream implementations are well-scoped mechanical
work. Pass `model: "sonnet"` in each `Agent` call.

**You are the coordinator agent.** Streams A, B, and C are fully parallel
(they build independent tools). Stream D depends on A+B+C being available (it
wires them into a workflow). Dispatch A+B+C as concurrent `Agent` subagents in
one message. Run D after they merge.

| Stream | Subagent type | Order | Scope |
|---|---|---|---|
| A — lockfile diff | `general-purpose` in worktree | parallel | `tools/ms_deps/diff.py`, tests |
| B — refresh wrapper | `general-purpose` in worktree | parallel | `tools/ms_deps/refresh.py`, tests |
| C — changelog fetcher | `general-purpose` in worktree | parallel | `tools/ms_deps/changelog.py`, tests |
| D — CI workflow | `general-purpose` in worktree | after A+B+C merge | `.github/workflows/dependency-refresh.yml` |

(Use a `tools/ms_deps/` package since the streams produce related modules.)

## Deliverables

### Stream A — `tools/ms_deps/diff.py`

Pure-Python stdlib (no extra deps; uv.lock is TOML, use `tomllib`).
- `python3 -m tools.ms_deps.diff path/to/old/uv.lock path/to/new/uv.lock` →
  markdown table to stdout:
  ```
  | Package | Old | New | Change |
  |---|---|---|---|
  | starlette | 0.52.1 | 1.0.2 | minor↑ |
  | fastapi | 0.136.1 | 0.137.0 | minor↑ |
  | docker | 7.1.0 | (unchanged) |
  ```
- Detect added / removed / unchanged / version-changed. Group unchanged at the
  bottom or hide behind `--include-unchanged`.
- `--format=json` for programmatic use by the workflow.

Tests cover: added package, removed package, version bump, no change, malformed
input.

### Stream B — `tools/ms_deps/refresh.py`

- `python3 -m tools.ms_deps.refresh` runs:
  1. Snapshot current `uv.lock` → `uv.lock.previous` (gitignored).
  2. Run `uv lock --upgrade` (or `uv lock` if no `--upgrade` flag available;
     verify the actual `uv` CLI surface).
  3. Compute version-diff via Stream A's tool.
  4. Run `pip-audit -r requirements.txt --strict` against the new lock.
  5. If the audit finds NEW CVEs (relative to the previous lock's audit),
     abort and restore the previous `uv.lock`. Exit code 2 means "regression."
- `--upgrade-package <name>` for one-off targeted bumps.
- `--dry-run` outputs the diff but does not modify `uv.lock`.
- Tests use a fixture lockfile and mock `uv lock` invocation.

### Stream C — `tools/ms_deps/changelog.py`

Best-effort metadata fetcher.
- `python3 -m tools.ms_deps.changelog --package starlette --from 0.52.1 --to 1.0.1`
  prints a markdown fragment with:
  - Release notes URL (PyPI `project_urls.Changelog` or
    `Homepage` + standard `CHANGELOG.md` paths on GitHub)
  - A short excerpt if reachable in under 200 lines
  - "No changelog found" if neither resolves
- Use `urllib.request` (stdlib). No new dependencies.
- Tests use `urllib.request` mocking; do not hit the network in CI.

### Stream D — `.github/workflows/dependency-refresh.yml` (after A+B+C merge)

Triggers:
- `schedule: cron: "0 6 * * 1"` (Mondays 06:00 UTC)
- `workflow_dispatch:` (manual)
- `repository_dispatch:` with type `cve-alert` (future hook from `pip-audit` cron)

Job steps:
1. Checkout `main`.
2. Set up `uv` + Python.
3. `python3 -m tools.ms_deps.refresh` — produces new `uv.lock` or aborts on
   audit regression.
4. If no change vs current `uv.lock`: exit 0, no PR.
5. Build PR body from version-diff + per-package changelog snippets.
6. Run full test suite in order of speed (fast unit → mypy/ruff/bandit → docker
   integration → schemathesis → browser → keploy → pip-audit).
7. If any test fails, output a PR-body-friendly summary of the failure (job
   link, last 50 lines of failing log). Open PR titled "deps: refresh {date} —
   N bumps, M CVE fixes (FAILED tests)" with a `do-not-merge` label.
8. If all pass: open PR titled "deps: refresh {date} — N bumps, M CVE fixes"
   with body = version-diff table + changelog snippets. No label.
9. Auto-comment on the previous open refresh PR (if any): "Superseded by #N."

Use a single PR branch name `deps/refresh` that gets force-pushed each cycle —
keeps PR list clean.

## Verification

After all four streams merge:
1. `.venv/bin/pytest tests/test_ms_deps_*.py -v` — all pass.
2. `python3 -m tools.ms_deps.diff uv.lock uv.lock` (same file) → "no changes" output.
3. `python3 -m tools.ms_deps.refresh --dry-run` → shows the diff that *would* happen.
4. Workflow lints clean via `actionlint` (if available) or YAML parse.
5. Manual dispatch of the workflow on a test branch opens a PR with the expected shape.
6. `python3 ms-enforce` exits 0.

## Out of scope
- Auto-bisect on failure (record as candidate for a future S-52 wave)
- Multi-PR-per-cycle (one bump per package) — explicitly rejected per Rules
- Editing `requirements.txt` — ranges are intent, untouched by this train
- ADR / docs/MAP / rules-to-tests migration (S-50)

## Robot mode (autonomous overnight execution)

When this wave is launched with the prefix "in Robot mode" in the user's prompt,
this wave operates under `.claude/ROBOT.md` doctrine and the default decision
register at `.claude/AUTONOMOUS-DEFAULTS.md`. Both files must be read before
dispatching any subagent. Summary of binding rules (see ROBOT.md for full text):

1. NEVER call `AskUserQuestion`. Write a decision file instead and continue.
2. NEVER enter plan mode.
3. NEVER use interactive Bash (`sudo`, `-i` flags).
4. On hard blocker, write `.claude/run/blockers/S-49-<stream>.md` and halt
   only that stream — other streams continue.
5. Maintain `.claude/run/status/S-49.md` continuously.
6. Merge streams to branch `wave/S-49-dep-refresh-train`, **NOT** `main`. The
   wave branch stays local; morning review handles the merge to main.
7. NEVER `git push`. Settings deny it.
8. Pass `model: "sonnet"` in each subagent `Agent` call (per Parallelization
   section above). Add an "in Robot mode" preamble to each subagent's prompt.
9. This wave BUILDS the refresh train but does NOT execute a refresh.
   Specifically: do not run `uv lock --upgrade` against the real lockfile; use
   fixture lockfiles for tests only. The workflow file is created but not
   triggered.
10. No scope creep — log adjacent issues to `.claude/run/observations/`.

Robot mode invocation: `in Robot mode: execute the wave defined in .claude/waves/S-49-DEP-REFRESH-TRAIN.md as coordinator. S-46 must be on main first.`
