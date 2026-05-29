# S-56-DOCTRINE-AND-AUDIT — Robot retro tooling + settings hygiene + doc audit + permanent test battery

## Goal
Four independent doctrine/infrastructure items: Robot retrospective tooling,
settings allow/deny review, expanded doc audit, and a permanent Robot test
battery + CI integration.

## Context
- After two Robot rounds the post-run retrospective is informal — read
  `.claude/run/` files, update doctrine, commit. Worth a tool that aggregates
  the run data into a structured report.
- The current `.claude/settings.local.json` has grown additive across many
  sessions. Allow list has redundant entries that became unnecessary once
  bypassPermissions silenced most categories. Deny list could be tighter
  given observations from 4 runs.
- S-48 built `tools/check_referenced_files.py` for code-level orphan
  detection. Extending it to `docs/` catches stale documentation.
- The 20-test battery + 10-test follow-up identified prompt categories.
  Making it permanent (`.claude/robot-test-battery/` + CI runner) prevents
  future regressions when settings change.

## Rules to follow
- Stream A's `tools/robot-retro.py` must read both `.claude/run/` (current
  run) AND `.claude/run-archive/<date>/` (past runs) since archived runs are
  the typical retro input.
- Stream B's settings changes only affect `.claude/settings.local.json`
  (gitignored). Don't commit it. Commit the *audit* (what changed and why)
  as a doc under `installer/DEPENDENCIES.md` or `.claude/SETTINGS-AUDIT.md`.
- Stream D's permanent battery must be runnable from a fresh session via a
  single command. CI integration is "warn on prompt detected"; binary
  pass/fail is harder because prompts are user-facing.

## Authorized deletions
- None.

## Parallelization

**Models:** coordinator = **opus**, subagents = **sonnet**. Four parallel streams.

| Stream | Subagent type | Scope |
|---|---|---|
| A — Robot retro tooling | `general-purpose` in worktree | `tools/robot-retro.py` (new), `.claude/ROBOT.md` (retro ritual section), tests |
| B — Settings hygiene | `general-purpose` in worktree | `.claude/settings.local.json` (NOT committed), `.claude/SETTINGS-AUDIT.md` (new, tracked) |
| C — Doc audit expansion | `general-purpose` in worktree | `tools/check_referenced_files.py` (extend to docs/), `tests/test_referenced_files.py` (extend), ms-enforce (already registered) |
| D — Permanent Robot test battery + CI | `general-purpose` in worktree | `.claude/robot-test-battery/` (new dir with test-instructions.md, runner script), `.github/workflows/robot-battery-validation.yml` (warn-only), ROBOT.md (link to it) |

## Deliverables

### Stream A — Robot retro tooling
1. `tools/robot-retro.py` (pure stdlib): scans a `.claude/run/` or
   `.claude/run-archive/<date>/` directory, aggregates `status/`,
   `decisions/`, `blockers/`, `observations/`, `proposed-deletions/` into
   one markdown report. Output: `RETRO-<date>.md` with structured sections.
2. ROBOT.md: add a "Retrospective ritual" section describing the post-run
   loop (run the script, read the report, propose AUTONOMOUS-DEFAULTS
   updates, commit under `robot: lessons from <date> run`).
3. Tests in `tests/test_robot_retro.py` using fixture run dirs.

### Stream B — Settings hygiene
1. Read current `.claude/settings.local.json`.
2. For each allow entry, classify: still needed under bypassPermissions, or
   redundant?
3. For each deny entry, classify: empirically tested or speculative?
4. Produce `.claude/SETTINGS-AUDIT.md` documenting:
   - Allow entries removed and why.
   - Deny entries added and why (cite Robot run that surfaced the need).
   - Final counts.
5. Apply the changes to `.claude/settings.local.json` (file is gitignored;
   change won't commit but the audit doc will).

### Stream C — Doc audit expansion
1. Extend `tools/check_referenced_files.py` to cover `docs/` tree.
2. Add detection for:
   - Tracked .md files with zero inbound references > 30 days old.
   - Markdown links pointing to non-existent files.
   - Tracked docs missing from `docs/MAP.md`.
3. Update `tests/test_referenced_files.py` with doc-tree cases.
4. Wire warning output into ms-enforce TIER_1 (warn-only).

### Stream D — Permanent Robot test battery + CI
1. Create `.claude/robot-test-battery/` containing:
   - `test-instructions.md` — the union of battery 1 (20 tests) + battery 2
     (10 tests) + any new categories discovered post-2026-05-28.
   - `runner.sh` — sets up the throwaway test repo at
     `/tmp/robot-battery-test-$(date +%s)/`, copies the test instructions
     into it, prints the prompt for the operator to paste into a fresh
     Claude session.
   - `RESULTS-TEMPLATE.md` — format the operator fills in (which test
     numbers prompted, what category).
2. `.github/workflows/robot-battery-validation.yml`:
   - Trigger: `workflow_dispatch` (manual) + `schedule` (monthly).
   - Job: spin up an ephemeral env (no actual Claude session — CI can't
     drive interactive prompts); run static analyzers against the
     test-instructions.md commands to verify they parse cleanly + don't
     match known-prompting patterns. Warn-only.
3. ROBOT.md: link to `.claude/robot-test-battery/` from the
   "Verified zero-prompt configuration" section.

## Verification
1. Stream A: `python3 -m pytest tests/test_robot_retro.py -v` — pass.
   `python3 tools/robot-retro.py .claude/run-archive/2026-05-28-round2/` produces a non-empty markdown report.
2. Stream B: `.claude/SETTINGS-AUDIT.md` exists, lists changes, has counts.
   `python3 -c "import json; print(len(json.load(open('.claude/settings.local.json'))['permissions']['allow']))"` shows reduced count.
3. Stream C: `tests/test_referenced_files.py` passes. Throwaway test: rename a tracked doc to break a link, run tool, see warning.
4. Stream D: `bash .claude/robot-test-battery/runner.sh` outputs a test env path and a paste-ready prompt. `actionlint` (if available) passes on the new workflow YAML.

## Out of scope
- bcrypt cap review, rules-to-tests, wave-file preflight — owned by S-55
- TIER_2 test failures — owned by S-57

## Robot mode (autonomous execution)

When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
doctrine v3 (orchestrator-as-coordinator, subagent preamble with venv symlink,
Bash heredoc for new files, never AskUserQuestion, never git push, merge to
`wave/S-56-doctrine-and-audit` not main).

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-56-DOCTRINE-AND-AUDIT.md as orchestrator.`
