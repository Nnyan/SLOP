# S-59-ACCESS-REQUESTS-PROCESSOR — Automate the access-requests queue

## Goal
Build the processor + automation that consumes `docs/ACCESS-REQUESTS.md`
entries and applies them: installs packages, edits settings.local.json,
files upgrade-train requests. Today the queue exists and is processed
manually; this wave makes it a first-class CI-integrated mechanism.

## Context
- `docs/ACCESS-REQUESTS.md` (committed 2026-05-29 — wave S-58 follow-on) holds
  pending requests in four categories: `[install]`, `[upgrade]`, `[allow]`,
  `[deny]`. Format is markdown-list + status markers (`[ ]` / `[x]` / `[—]`).
- Manual processing pattern established with `/tmp/access-requests-setup.py`
  bootstrap (2026-05-29). pip-audit install + 9 settings allow re-adds done
  via that script + retroactively logged in the queue.
- Integration points: settings.local.json (for `[allow]`/`[deny]`),
  requirements*.txt + uv.lock (for `[install]`/`[upgrade]`), the S-49
  refresh-train workflow (for `[upgrade]` PRs).

## Rules to follow
- Processor must be IDEMPOTENT — running twice on the same queue state is a
  no-op for entries already `[x]`.
- Processor must NEVER skip ahead: read queue top-to-bottom in each section;
  apply pending entries in order; halt on the first failure with a clear log.
- `[deny]` category entries require explicit `--allow-deny-additions` flag
  to apply — they're rare and dangerous (tighten restrictions).
- Output should mirror the queue file with status flips, never silently
  reorder or reformat entries that weren't touched.

## Authorized deletions
- None.

## Parallelization

**Models:** coordinator = **opus**, subagents = **sonnet**. Three parallel streams.

| Stream | Subagent type | Scope |
|---|---|---|
| A — processor tool | `general-purpose` in worktree | `tools/process_access_requests.py` (new), `tests/test_access_requests_processor.py` (new) |
| B — settings/install integration | `general-purpose` in worktree | Helper modules for the four category appliers, integration with `uv pip install`, `requirements*.txt` edits, settings.local.json edits via the helper-script pattern |
| C — CI workflow + S-49 train integration | `general-purpose` in worktree | `.github/workflows/access-requests-processor.yml` (new — cron + manual trigger), integration hook into `.github/workflows/dependency-refresh.yml` so `[upgrade]` entries feed the same PR train |

## Deliverables

### Stream A — `tools/process_access_requests.py`
Pure stdlib. Subcommands:
- `python3 tools/process_access_requests.py list` — show pending entries grouped by category.
- `python3 tools/process_access_requests.py process [--category install|upgrade|allow|deny] [--dry-run]` — apply pending entries; flip statuses; commit changes per-entry with provenance.
- `python3 tools/process_access_requests.py archive [--older-than 60d]` — prune applied entries older than N days to keep the file scannable.
- `--allow-deny-additions` flag required for processing any `[deny]` entries.

Parser handles the four categories, status markers, and the established
entry format. Validates each entry has required fields (subject, source,
date). Outputs to stdout in a structured form the CI workflow can parse.

### Stream B — Category appliers
For each category:
- `[install]`: invoke `uv pip install <pkg>` against project venv; if the
  package is in `requirements*.txt`, ensure version constraint is satisfied;
  if not, append to appropriate file (requirements-dev.txt for dev tools).
- `[upgrade]`: file an `--upgrade-package <name>` request into the S-49
  refresh-train workflow (don't execute upgrade directly — let the train
  handle it with its test gate).
- `[allow]`: edit `.claude/settings.local.json` via helper-script pattern
  (lift the self-edit deny → edit → restore). Add entry, no duplicates.
- `[deny]`: same as allow but inverted; requires explicit flag per Rules.

### Stream C — CI workflow + S-49 integration
- `.github/workflows/access-requests-processor.yml`:
  - Trigger: `workflow_dispatch` (manual) + `schedule` (weekly).
  - Job: run processor in `--dry-run` mode, report pending count + estimated
    actions; for now do NOT auto-apply in CI (require operator review).
- Modify `.github/workflows/dependency-refresh.yml` (from S-49) to also
  read `[upgrade]` entries from `docs/ACCESS-REQUESTS.md` and include them
  in the refresh-PR scope.
- ms-enforce TIER_1 warn-only check `check_access_requests_stale`: warn
  when any pending entry is >30 days old or pending count exceeds threshold
  (default 20).

## Verification
1. `python3 tools/process_access_requests.py list` shows the current pending
   entries from the live `docs/ACCESS-REQUESTS.md`.
2. `python3 -m pytest tests/test_access_requests_processor.py -v` passes.
3. Throwaway: add a fake `[allow]` entry to a fixture queue file, run
   `--dry-run`, see the proposed settings change without it being applied.
4. `python3 ms-enforce` exits 0 (warn-only stale check passes).
5. The CI workflow YAML parses (use `actionlint` if available).

## Out of scope
- Pre-existing TIER_2 failures (S-57 + S-58 territory).
- Settings hygiene review beyond what's needed for the processor (handled by S-56 Stream B).
- Auto-merging dependency-refresh PRs (still operator-review).
- Replacing `docs/ACCESS-REQUESTS.md` with a database or alternative format — keep markdown for simplicity and grep-ability.

## Robot mode (autonomous execution)

When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
doctrine v4. All three streams parallel. Coordinator merges to
`wave/S-59-access-requests-processor` not main.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-59-ACCESS-REQUESTS-PROCESSOR.md as orchestrator.`
