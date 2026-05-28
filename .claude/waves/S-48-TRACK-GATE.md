# S-48-TRACK-GATE — Track-status invariant + orphan-file detection

## Goal
Install a CI gate that enforces: **every file on disk is in exactly one of three
states — tracked, explicitly gitignored, or on a documented allowlist.** No
fourth "silently untracked" state. Plus an orphan-file detector that flags
tracked files with zero inbound references after a grace window. This wave
also uses the new gate to clean up the existing tracked runtime files and
`backend/static` self-TODO.

## Context
- The 2026-05-27 audit found `uv.lock` silently untracked for months, plus
  `.mypy_cache/`, `.ruff_cache/`, `.claude/worktrees/`, and an unfinished
  `backend/static` self-TODO in `.gitignore` line 46.
- `.gitignore` is silent: you can leave an important file untracked indefinitely
  and not notice. The gate makes silent state loud.
- The allowlist is the positive statement of "yes this is intentionally local."
  That documents *intent*; `.gitignore` only documents *pattern*.
- Depends on S-46 having merged (S-46 Stream C edits `.gitignore`; running this
  wave after avoids merge conflicts and lets the new check test the cleaned-up
  state).

## Rules to follow
- The gate must integrate with the existing `ms-enforce` system as a TIER_1 check
  (same tier as `check_file_size_ratchet`). Single CI gate is the preferred shape.
- The allowlist file lives at `.track-allowlist` (top of repo). Each entry has a
  trailing `# reason: <why>` comment — entries without a reason fail the check.
- Orphan detection runs as a **warning**, not a failure. False positives are
  expected (docs that reference files by URL fragment, ADRs that name historical
  files). Failures would create churn; warnings let humans triage.
- The cleanup in Stream C must happen AFTER Streams A and B land, so the new
  gate fires on the cleanup as a sanity check. This is the only intra-wave
  ordering — A and B are fully parallel.

## Parallelization

**Models:** coordinator = **opus**, subagents = **sonnet**. Rationale: this wave
introduces new tooling with meaningful API design (`.track-allowlist` reason-comment
format, grace-window semantics, ms-enforce TIER_1 integration, warning-vs-failure
semantics). Coordinator decisions shape downstream usage; stream implementation
is mechanical. Pass `model: "sonnet"` in each `Agent` call.

**You are the coordinator agent.** Streams A and B are fully parallel — dispatch
them concurrently as `Agent` subagents in worktrees in one message. Stream C
runs **after** A and B merge (it depends on the new gate being installed to
verify the cleanup). Do not dispatch C until A and B are merged to your
coordinator branch.

| Stream | Subagent type | Order | Scope |
|---|---|---|---|
| A — track-status gate | `general-purpose` in worktree | parallel | `tools/check_track_status.py`, `.track-allowlist`, `ms-enforce` registration, tests |
| B — orphan-file detector | `general-purpose` in worktree | parallel | `tools/check_referenced_files.py`, `ms-enforce` registration, tests |
| C — cleanup using new gate | `general-purpose` in worktree | after A+B merge | `.gitignore` (additions), `git rm --cached` for `backend/static` + `data/tailscale/*` |

## Deliverables

### Stream A — `tools/check_track_status.py`

Pure-Python stdlib. Behavior:
1. Run `git ls-files --others --exclude-standard` to list untracked-not-ignored paths.
2. Read `.track-allowlist` — each line is either blank, a `#` comment, or
   `<glob>    # reason: <text>`. Entries missing the reason comment are
   themselves an error (forces intent).
3. For each untracked path, check if it matches an allowlist glob.
4. **Fail (exit 1)** if any path is neither tracked, gitignored, nor allowlisted.
5. Output: list each violating path with the guidance string
   "Add to .gitignore, .track-allowlist (with reason), or `git add` it."

`.track-allowlist` initial contents:
```
# Files allowed to exist untracked. Each entry MUST end with `# reason: ...`.
# `git add` your file unless it's per-developer scratch or contains secrets.

memory/**                # reason: auto-memory output if user has it pointed here (deprecated; canonical path is ~/.claude/projects/)
```

`ms-enforce` integration: register `check_track_status` at TIER_1 alongside
`check_file_size_ratchet`. Same exit-code propagation pattern.

Tests `tests/test_track_status.py`:
- Tracked file → pass
- Gitignored file → pass
- Allowlisted file (with reason) → pass
- Allowlisted file (no reason comment) → check itself errors with a clear message
- Untracked-not-ignored-not-allowlisted file → fail with path listed

### Stream B — `tools/check_referenced_files.py`

Pure-Python stdlib. Behavior:
1. For every file in `git ls-files`, grep the rest of the repo for its
   basename or path fragment. Excluded extensions are configurable; default
   targets are `.md`, `.yml`, `.yaml`, `.py`, `.ts`, `.vue`, `.json`, `.sh`,
   `.toml`, `.cfg`, `.ini`.
2. A file with zero inbound references is "orphan."
3. **Allowlist `.orphan-allowlist`** for known-orphan-but-intentional files
   (entry-point scripts, top-level README, etc.). Same reason-comment pattern
   as `.track-allowlist`.
4. **Grace window: file must be older than 30 days AND have zero references**
   to be flagged. `git log --diff-filter=A --format=%at -- <path> | head -1`
   gives birth time.
5. **Output WARNING (not failure) to stdout.** Exit 0 even with flags.

`ms-enforce` integration: register `check_referenced_files` at TIER_1 but mark
it as warning-only (matches the tests-over-1000 pattern in `check_linecount`).

Tests `tests/test_referenced_files.py`:
- File with inbound reference → no warning
- Truly orphan file older than 30 days, not in allowlist → warning printed, exit 0
- Orphan file in allowlist → no warning
- Orphan file under 30 days old → no warning (grace window)

### Stream C — Cleanup using new gate (runs after A+B merge)

After Streams A and B merge to coordinator branch:
1. **`backend/static/`** — the `.gitignore` line 46 self-TODO says "Run
   `git rm -r --cached backend/static/` before next release." Do it now. Remove
   the now-stale TODO comment from `.gitignore`.
2. **`data/tailscale/tailscaled.log1.txt`, `log2.txt`, `tailscaled.state`** —
   verify these contain no secrets (device IDs are OK to remove from a public
   repo but not actively dangerous). Then `git rm --cached` them and add the
   pattern `data/tailscale/*.log*` + `data/tailscale/tailscaled.state` to
   `.gitignore`. Keep `data/tailscale/tailscaled.log.conf` (config, intentional).
3. Run `python3 ms-enforce` — both new checks must pass on the cleaned-up tree.
4. Run `tools/check_track_status.py` directly to confirm no regressions.

## Verification

After all three streams merge:
1. `python3 ms-enforce` exits 0 (track-status pass + orphan warnings printed).
2. `git ls-files --others --exclude-standard` returns ONLY paths covered by
   `.track-allowlist`.
3. `.venv/bin/pytest tests/test_track_status.py tests/test_referenced_files.py -v` — all pass.
4. `git ls-files | grep backend/static` returns nothing (untracked).
5. `git ls-files | grep data/tailscale/.*\.log` returns nothing (untracked).
6. The `.gitignore` line 46 self-TODO comment is gone.
7. Throwaway test: `touch foo.txt && python3 ms-enforce` → fails with foo.txt named.

## Out of scope
- Dep refresh train (S-49)
- ADR / docs/MAP (S-50)
- Rules-to-tests migration (S-50)
- Splitting any oversize file (parked in OPTIONAL-FILE-SIZE-REMEDIATION.md)
- Auto-fixing orphan files — flagging only (humans triage)
